"use strict";
function showPhotoPreparation(prefix, token, processing) {
  $(`${prefix}-preview`).src = `/api/intake/${token}/photo?v=${Date.now()}`;
  $(`${prefix}-preview`).hidden = false;
  $(`${prefix}-photo-options`).hidden = !processing;
  if (!processing) return;
  for (const key of ["crop", "perspective", "balance"])
    $(`${prefix}-${key}`).checked = processing[key];
  $(`${prefix}-processing`).textContent = processing.message;
}
async function changePhotoPreparation(prefix, token) {
  const options = Object.fromEntries(
    ["crop", "perspective", "balance"].map((key) => [
      key,
      $(`${prefix}-${key}`).checked,
    ]),
  );
  if (!options.crop) options.perspective = false;
  return api(`/intake/${token}/photo-options`, {
    method: "POST",
    body: JSON.stringify(options),
  });
}
function photoBusy(busy, message = "") {
  photoState.busy = busy;
  $("photo-save").disabled = busy || !photoState.token;
  for (const key of ["crop", "perspective", "balance"])
    $(`photo-${key}`).disabled =
      busy ||
      !photoState.token ||
      (key === "perspective" && !$("photo-crop").checked);
  $("photo-status").textContent = message;
}
async function openPhotoPreparation(file, card, side = "front") {
  if (photoState.busy || photoState.saving) return;
  if (file.size > 8 * 1024 * 1024) {
    toast("Photo limitée à 8 Mo.");
    return;
  }
  const generation = ++photoState.generation;
  photoState.card = card;
  photoState.side = side;
  photoState.file = file;
  $("detail-dialog").close();
  $("photo-error").textContent = "";
  $("photo-title").textContent =
    `Préparer le ${side === "back" ? "verso" : "recto"} de l’exemplaire`;
  $("photo-preview").alt =
    `Aperçu du ${side === "back" ? "verso" : "recto"} à enregistrer`;
  $("photo-preview").hidden = true;
  $("photo-photo-options").hidden = true;
  $("photo-dialog").showModal();
  photoBusy(true, "Préparation de la photo…");
  try {
    const result = await api("/intake/photo", {
      method: "POST",
      body: file,
      headers: CardMedia.photoHeaders(file),
    });
    if (generation !== photoState.generation) {
      await api(`/intake/${result.token}`, { method: "DELETE" });
      return;
    }
    photoState.token = result.token;
    photoState.prepared = Boolean(result.photo_processing);
    showPhotoPreparation("photo", result.token, result.photo_processing);
  } catch (error) {
    if (generation === photoState.generation)
      $("photo-error").textContent = error.message;
  } finally {
    if (generation === photoState.generation) photoBusy(false);
  }
}
for (const key of ["crop", "perspective", "balance"]) {
  $(`intake-${key}`).addEventListener("change", async () => {
    if (intakeState.busy || !intakeState.token) return;
    const generation = intakeState.generation;
    intakeBusy(true, "Préparation de la photo…");
    $("add-error").textContent = "";
    try {
      const result = await changePhotoPreparation("intake", intakeState.token);
      if (generation !== intakeState.generation) return;
      showPhotoPreparation("intake", intakeState.token, result);
      clearIntakeChoice();
      $("intake-candidates").replaceChildren();
      $("intake-catalogue-message").textContent = "";
      intakeBusy(
        false,
        "Réglages modifiés. Relisez la carte ou recherchez l’extension avant de confirmer.",
      );
    } catch (error) {
      if (generation === intakeState.generation) {
        intakeBusy(false);
        $("add-error").textContent = error.message;
      }
    }
  });
  $(`photo-${key}`).addEventListener("change", async () => {
    if (photoState.busy || !photoState.token) return;
    const generation = photoState.generation;
    photoBusy(true, "Préparation de la photo…");
    $("photo-error").textContent = "";
    try {
      const result = await changePhotoPreparation("photo", photoState.token);
      if (generation === photoState.generation)
        showPhotoPreparation("photo", photoState.token, result);
    } catch (error) {
      if (generation === photoState.generation)
        $("photo-error").textContent = error.message;
    } finally {
      if (generation === photoState.generation) photoBusy(false);
    }
  });
}
$("photo-dialog").addEventListener("cancel", (event) => {
  if (photoState.saving) event.preventDefault();
});
$("photo-dialog").addEventListener("close", () => {
  ++photoState.generation;
  const token = photoState.token;
  photoState.token = null;
  photoState.file = null;
  photoState.busy = false;
  $("photo-preview").removeAttribute("src");
  if (token) api(`/intake/${token}`, { method: "DELETE" }).catch(() => {});
});
$("photo-save").addEventListener("click", async () => {
  if (photoState.busy || !photoState.token) return;
  const card = photoState.card;
  photoState.saving = true;
  const close = $("photo-dialog").querySelector("[data-close]");
  close.disabled = true;
  photoBusy(true, "Enregistrement de la photo…");
  try {
    if (photoState.prepared)
      await api(`/copies/${card.id}/photo-from-intake`, {
        method: "POST",
        body: JSON.stringify({
          token: photoState.token,
          expected_version: card.version,
          side: photoState.side,
        }),
      });
    else
      await api(
        `/copies/${card.id}/photo?version=${card.version}&side=${photoState.side}`,
        {
          method: "PUT",
          body: photoState.file,
          headers: { "Content-Type": photoState.file.type },
        },
      );
    $("photo-dialog").close();
    await openDetail(card.id);
    await loadCards();
    toast(
      photoState.prepared
        ? "Photo enregistrée ; photo entière conservée dans la sauvegarde."
        : "Photo enregistrée.",
    );
  } catch (error) {
    $("photo-error").textContent = error.message;
  } finally {
    photoState.saving = false;
    close.disabled = false;
    photoBusy(false);
  }
});
function intakeBusy(busy, message = null) {
  intakeState.busy = busy;
  $("intake-read").disabled = busy || !intakeState.hasPhoto;
  $("intake-search").disabled = busy;
  $("intake-save").disabled = busy;
  for (const field of $("add-form").elements) {
    if (
      ["name", "number", "set_name", "language", "hp", "reason"].includes(
        field.name,
      )
    )
      field.disabled = busy;
  }
  $("intake-confirm").disabled = busy;
  for (const button of $("intake-candidates").querySelectorAll("button"))
    button.disabled = busy;
  for (const id of ["intake-camera", "intake-file"])
    $(id).disabled = busy || Boolean(intakeState.existing);
  for (const key of ["crop", "perspective", "balance"])
    $(`intake-${key}`).disabled =
      busy ||
      !intakeState.hasPhoto ||
      (key === "perspective" && !$("intake-crop").checked);
  if (message !== null) $("intake-status").textContent = message;
}
function clearIntakeChoice() {
  intakeState.chosen = null;
  $("intake-confirm").checked = false;
  $("intake-confirm-label").hidden = true;
  $("intake-comparison").hidden = true;
  $("intake-comparison").replaceChildren();
  for (const button of $("intake-candidates").querySelectorAll(
    ".intake-candidate",
  ))
    button.classList.remove("selected");
}
async function discardIntake() {
  if (typeof Workflows !== "undefined" && Workflows.capture) return;
  const token = intakeState.token;
  intakeState.token = null;
  if (token) {
    try {
      await api(`/intake/${token}`, { method: "DELETE" });
    } catch {
      /* Expired drafts need no cleanup. */
    }
  }
}
async function startIntake(existing = null, series = null) {
  if (!editAllowed()) return;
  if (typeof Workflows !== "undefined") {
    await Workflows.persist();
    Workflows.attach(null);
  }
  const generation = ++intakeState.generation;
  await discardIntake();
  if (generation !== intakeState.generation) return;
  intakeState.existing = existing;
  intakeState.hasPhoto = false;
  const form = $("add-form");
  form.reset();
  clearIntakeChoice();
  $("intake-candidates").replaceChildren();
  $("intake-catalogue-message").textContent = "";
  $("add-error").textContent = "";
  $("intake-preview").hidden = true;
  $("intake-preview").removeAttribute("src");
  $("intake-photo-options").hidden = true;
  $("intake-title").textContent = existing
    ? "Identifier cet exemplaire"
    : "Ajouter une carte";
  $("intake-save").textContent = existing
    ? "Enregistrer l’identification"
    : "Ajouter l’exemplaire";
  form.querySelector(".intake-actions").hidden = Boolean(existing);
  if (existing) {
    for (const key of [
      "name",
      "number",
      "set_name",
      "language",
      "hp",
      "stamp",
      "stamp_state",
      "finish",
      "distribution",
      "distribution_state",
      "album_id",
      "page",
      "position",
      "notes",
    ])
      form.elements[key].value = existing[key] ?? "";
    form.elements.reason.value = "Identification assistée de cet exemplaire";
  }
  for (const key of ["album_id", "page", "position"])
    form.elements[key].disabled = Boolean(existing);
  if (typeof Workflows !== "undefined") Workflows.attach(series);
  $("add-dialog").showModal();
  intakeBusy(true, "Préparation de la saisie…");
  try {
    const result = series?.data.front_token
      ? await api(`/intake/${series.data.front_token}`)
      : await api(
          existing ? `/copies/${existing.id}/intake` : "/intake/drafts",
          { method: "POST" },
        );
    if (generation !== intakeState.generation) {
      await api(`/intake/${result.token}`, { method: "DELETE" });
      return;
    }
    intakeState.token = result.token;
    intakeState.hasPhoto = result.has_photo;
    if (result.has_photo) {
      showPhotoPreparation("intake", result.token, result.photo_processing);
    }
    if (series && typeof Workflows !== "undefined")
      await Workflows.restore(series);
    intakeBusy(
      false,
      existing
        ? result.has_photo
          ? "La photo enregistrée est prête. Cliquez sur « Lire la carte » ou recherchez l’extension à partir de la saisie."
          : "Saisissez le nom et la référence pour retrouver l’extension. La photo peut être ajoutée depuis la fiche."
        : "Ajoutez une photo ou saisissez le nom et la référence pour retrouver l’extension.",
    );
  } catch (e) {
    if (generation === intakeState.generation) {
      intakeBusy(false, "");
      $("add-error").textContent = e.message;
    }
  }
}
const intakeNumberKey = (value) =>
  String(value || "")
    .replace(/\s+/g, "")
    .toUpperCase()
    .split("/")
    .map((part) => (/^\d+$/.test(part) ? String(Number(part)) : part))
    .join("/");
function intakeNotes(notes, observation) {
  const lines = [
    observation.notes?.trim() && "Lecture Gemini : " + observation.notes.trim(),
    observation.flaws?.trim() &&
      "Défauts visibles (lecture Gemini) : " + observation.flaws.trim(),
  ].filter((line) => line && !notes.includes(line));
  return [notes.trimEnd(), ...lines].filter(Boolean).join("\n");
}
// A reading is a proposal: an empty or unknown value never erases the entry.
function intakeReading(current, observation) {
  const next = { ...current };
  for (const key of ["name", "number", "language", "hp"]) {
    const value = String(observation[key] ?? "").trim();
    if (value && value !== "unknown") next[key] = value;
  }
  if (
    current.number &&
    intakeNumberKey(next.number) !== intakeNumberKey(current.number)
  )
    next.set_name = "";
  // A printed stamp marks a promo variant: proposed, never silently dropped.
  const stamp = (observation.stamp_text || "").trim();
  if (stamp) {
    next.stamp = stamp;
    if (current.stamp_state === "absent") next.stamp_state = "unobserved";
  }
  next.notes = intakeNotes(current.notes || "", observation);
  return next;
}
// Choosing an edition fills the entry; a value the catalogue lacks is kept,
// except the extension, which the server compares with the edition's own.
function intakeCandidateFields(current, candidate) {
  return {
    ...current,
    name: candidate.printed_name || candidate.name || current.name,
    number: candidate.printed_number || candidate.number || current.number,
    set_name: candidate.set_name ?? current.set_name,
    language: candidate.language || current.language,
    hp: candidate.hp == null ? current.hp : String(candidate.hp),
  };
}
function intakeFormValues(keys) {
  const form = $("add-form");
  return Object.fromEntries(keys.map((key) => [key, form.elements[key].value]));
}
function setIntakeFormValues(values) {
  const form = $("add-form");
  for (const [key, value] of Object.entries(values))
    form.elements[key].value = value ?? "";
}
function showIntakeCandidates(result) {
  clearIntakeChoice();
  $("intake-candidates").replaceChildren();
  // Without a proposal, the image says why (prints without image, too close).
  const imageNote =
    result.image_proposal && !result.candidates.length
      ? ` ${result.image_proposal.reason}`
      : "";
  $("intake-catalogue-message").textContent = result.message + imageNote;
  const choices = [];
  for (const candidate of result.candidates) {
    const entry = el("article", undefined, "intake-candidate-entry");
    const button = el("button", undefined, "intake-candidate");
    button.type = "button";
    button.setAttribute(
      "aria-label",
      `Choisir ${candidate.name}, ${candidate.set_name}, ${candidate.number}`,
    );
    const choose = () => {
      const shown = () =>
        intakeFormValues(["name", "number", "set_name", "language", "hp"]);
      // Choosing it again after an edit restores the edition's values.
      if (intakeState.chosen === candidate.id) {
        setIntakeFormValues(intakeCandidateFields(shown(), candidate));
        return;
      }
      clearIntakeChoice();
      intakeState.chosen = candidate.id;
      setIntakeFormValues(intakeCandidateFields(shown(), candidate));
      button.classList.add("selected");
      if (candidate.image && intakeState.hasPhoto) {
        for (const [label, src] of [
          ["Votre exemplaire", $("intake-preview").src],
          ["Carte du catalogue", candidate.image],
        ]) {
          const figure = el("figure");
          const image = el("img");
          image.src = src;
          image.alt = label;
          figure.append(image, el("figcaption", label));
          $("intake-comparison").append(figure);
        }
        $("intake-comparison").hidden = false;
      }
      $("intake-confirm-label").hidden = false;
      if (typeof Workflows !== "undefined") Workflows.changed();
    };
    if (candidate.image) {
      const image = el("img");
      image.src = candidate.image;
      image.alt = `Illustration catalogue de ${candidate.name}`;
      image.loading = "lazy";
      // Enlarging an illustration also chooses it.
      const zoom = CardMedia.zoomButton(image);
      zoom.addEventListener("click", choose);
      entry.append(zoom);
    }
    button.append(
      el("strong", candidate.name),
      el("span", candidate.set_name),
      el("span", `${candidate.number} · ${candidate.language.toUpperCase()}`),
    );
    if (candidate.proposed_by === "image")
      button.append(
        el("span", "Proposée par l’image, à confirmer", "intake-image-proposal"),
      );
    button.addEventListener("click", choose);
    entry.append(button);
    $("intake-candidates").append(entry);
    choices.push(choose);
  }
  // A single exact edition is preselected; confirming it stays a human gesture.
  if (result.exact && choices.length === 1) {
    choices[0]();
    $("intake-catalogue-message").textContent =
      "Une seule édition correspond exactement : elle est présélectionnée. Comparez l’illustration, puis cochez la confirmation.";
  }
}
// Editing the entry keeps the chosen edition but asks for a new confirmation.
for (const key of ["name", "number", "set_name", "language", "hp"]) {
  for (const event of ["input", "change"])
    $("add-form").elements[key].addEventListener(event, () => {
      $("intake-confirm").checked = false;
    });
}
$("add-card").addEventListener("click", () =>
  startIntake().catch((e) => toast(e.message)),
);
$("add-dialog").addEventListener("close", () => {
  ++intakeState.generation;
  if (typeof Workflows !== "undefined" && Workflows.capture) {
    Workflows.persist()
      .then(() => Workflows.refresh())
      .catch((e) => toast(e.message));
  } else discardIntake();
});
$("add-dialog").addEventListener("cancel", (e) => {
  if (intakeState.saving) e.preventDefault();
});
async function uploadIntakePhoto(file) {
  if (!file || intakeState.busy || intakeState.existing) return;
  const generation = intakeState.generation;
  $("add-error").textContent = "";
  if (file.size > 8 * 1024 * 1024) {
    $("add-error").textContent = "Photo limitée à 8 Mo.";
    return;
  }
  intakeBusy(true, "Préparation de la photo…");
  try {
    const result = await api("/intake/photo", {
      method: "POST",
      body: file,
      headers: CardMedia.photoHeaders(file),
    });
    if (generation !== intakeState.generation) {
      await api(`/intake/${result.token}`, { method: "DELETE" });
      return;
    }
    const previous = intakeState.token;
    await discardIntake();
    intakeState.token = result.token;
    intakeState.hasPhoto = true;
    clearIntakeChoice();
    $("intake-candidates").replaceChildren();
    $("intake-catalogue-message").textContent = "";
    showPhotoPreparation("intake", result.token, result.photo_processing);
    if (typeof Workflows !== "undefined") await Workflows.persist();
    if (
      previous &&
      previous !== result.token &&
      typeof Workflows !== "undefined" &&
      Workflows.capture
    )
      await api(`/intake/${previous}`, { method: "DELETE" });
    intakeBusy(
      false,
      "Photo prête. Cliquez sur « Lire la carte » ou complétez la saisie manuellement.",
    );
  } catch (e) {
    if (generation === intakeState.generation) {
      intakeBusy(false, "");
      $("add-error").textContent = e.message;
    }
  }
}
$("intake-file").addEventListener("change", (event) => {
  const file = event.target.files[0];
  event.target.value = "";
  uploadIntakePhoto(file);
});
$("intake-camera").addEventListener("click", () => {
  if (intakeState.busy || intakeState.existing) return;
  const generation = intakeState.generation;
  CardMedia.capture((file) => {
    if (generation === intakeState.generation) uploadIntakePhoto(file);
  });
});
async function runIntake(analysis) {
  if (!intakeState.token || intakeState.busy) return;
  const generation = intakeState.generation;
  const form = $("add-form");
  const query = {
    name: form.elements.name.value.trim(),
    number: form.elements.number.value.trim(),
    language: form.elements.language.value,
    hp: form.elements.hp.value === "" ? null : Number(form.elements.hp.value),
  };
  if (!analysis && !query.name) {
    $("add-error").textContent = "Saisissez le nom imprimé avant la recherche.";
    return;
  }
  $("add-error").textContent = "";
  clearIntakeChoice();
  intakeBusy(
    true,
    analysis
      ? "Lecture de la photo… Cela peut prendre quelques secondes."
      : "Recherche de l’extension…",
  );
  try {
    const result = await api(
      `/intake/${intakeState.token}/${analysis ? "analyze" : "catalogue"}`,
      // A reading sends the entry too: an unread field keeps what is shown.
      { method: "POST", body: JSON.stringify(query) },
    );
    if (generation !== intakeState.generation) return;
    if (result.observation) {
      const keys = ["name", "number", "language", "hp", "set_name"];
      setIntakeFormValues(
        intakeReading(
          intakeFormValues([...keys, "stamp", "stamp_state", "notes"]),
          result.observation,
        ),
      );
    }
    showIntakeCandidates(result);
    if (typeof Workflows !== "undefined") Workflows.changed();
    intakeBusy(
      false,
      result.observation
        ? "Lecture proposée : vérifiez les champs." +
            (result.observation.notes?.trim() || result.observation.flaws?.trim()
              ? " Les remarques et défauts lus sont ajoutés aux notes."
              : "")
        : "Recherche terminée.",
    );
  } catch (e) {
    if (generation === intakeState.generation) {
      intakeBusy(false, "La saisie manuelle reste disponible.");
      $("add-error").textContent = e.message;
    }
  }
}
$("intake-read").addEventListener("click", () => runIntake(true));
$("intake-search").addEventListener("click", () => runIntake(false));
$("add-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (intakeState.busy || !intakeState.token) return;
  const generation = intakeState.generation;
  const data = Object.fromEntries(new FormData(e.target));
  for (const key of ["album_id", "page", "position"])
    data[key] = e.target.elements[key].value;
  for (const key of ["page", "position"]) data[key] = Number(data[key]);
  data.hp = data.hp === "" ? null : Number(data.hp);
  data.chosen_catalog_id = intakeState.chosen;
  data.human_confirmed = $("intake-confirm").checked;
  $("add-error").textContent = "";
  intakeState.saving = true;
  document.querySelector('[data-close="add-dialog"]').disabled = true;
  intakeBusy(true, "Enregistrement de l’exemplaire…");
  try {
    const preparation =
      typeof Workflows !== "undefined"
        ? await Workflows.prepareSave(data)
        : { url: `/intake/${intakeState.token}/save`, data };
    const result = await api(preparation.url, {
      method: "POST",
      body: JSON.stringify(preparation.data),
    });
    const c = result.card || result;
    if (generation !== intakeState.generation) return;
    if (result.session && typeof Workflows !== "undefined")
      await Workflows.next(result.session);
    else $("add-dialog").close();
    await refreshSummary();
    await loadCards();
    if (!result.session) await openDetail(c.id);
    toast(
      "Exemplaire enregistré. Son état physique et son prix restent à évaluer séparément.",
    );
  } catch (err) {
    if (generation === intakeState.generation)
      $("add-error").textContent = err.message;
  } finally {
    intakeState.saving = false;
    document.querySelector('[data-close="add-dialog"]').disabled = false;
    if (generation === intakeState.generation) intakeBusy(false);
  }
});
$("user-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/users", {
      method: "POST",
      body: JSON.stringify(Object.fromEntries(new FormData(e.target))),
    });
    e.target.reset();
    $("user-message").textContent = "Compte créé.";
    await loadUsers();
  } catch (err) {
    $("user-message").textContent = err.message;
  }
});
$("payment-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/settings/payment", {
      method: "PUT",
      body: JSON.stringify(Object.fromEntries(new FormData(e.target))),
    });
    await loadPayment();
    $("payment-message").textContent = "Moyens de paiement enregistrés.";
  } catch (err) {
    $("payment-message").textContent = err.message;
  }
});
$("floor-margin-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/settings/floor-margin", {
      method: "PUT",
      body: JSON.stringify({ margin: Number(e.target.elements.margin.value) }),
    });
    state.summary = await api("/summary");
    await loadFloorMargin();
    $("floor-margin-message").textContent = "Marge enregistrée.";
  } catch (err) {
    $("floor-margin-message").textContent = err.message;
  }
});
$("lot-rotation-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/settings/lot-rotation", {
      method: "PUT",
      body: JSON.stringify({ days: Number(e.target.elements.days.value) }),
    });
    await loadLotRotation();
    $("lot-rotation-message").textContent = t("lot_rotation.saved");
  } catch (err) {
    $("lot-rotation-message").textContent = err.message;
  }
});
$("album-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/albums", {
      method: "POST",
      body: JSON.stringify(Object.fromEntries(new FormData(e.target))),
    });
    e.target.reset();
    $("album-message").textContent = "Album ajouté.";
    await refreshSummary();
  } catch (err) {
    $("album-message").textContent = err.message;
  }
});
