"use strict";
async function openDetail(id) {
  const c = await api("/copies/" + id + "?threshold=" + reviewThreshold());
  state.detail = c;
  $("detail-body").replaceChildren();
  const layout = el("div", undefined, "detail-layout"),
    photo = el("div", undefined, "detail-photo"),
    form = el("form", undefined, "detail-fields");
  const faces = el("div", undefined, "card-faces");
  faces.setAttribute("data-media-group", "");
  for (const [side, label, key] of [
    ["front", "Recto", "photo"],
    ["back", "Verso", "back_photo"],
  ]) {
    const figure = el("figure");
    figure.append(el("figcaption", label));
    if (c[key]) {
      const image = el("img");
      image.src = `/api/copies/${id}/photo?side=${side}&v=${c.version}`;
      image.alt = `${label} de ${c.name}`;
      figure.append(image);
    } else
      figure.append(
        el("p", `Photo du ${label.toLowerCase()} absente.`, "help"),
      );
    if (editAllowed() && !c.deleted_at) {
      const actions = el("div", undefined, "intake-actions");
      const capture = el(
        "button",
        `Prendre une photo du ${label.toLowerCase()}`,
      );
      capture.type = "button";
      capture.addEventListener("click", () =>
        CardMedia.capture((file) => openPhotoPreparation(file, c, side)),
      );
      const upload = el(
        "label",
        `Téléverser le ${label.toLowerCase()}`,
        "button",
      );
      const input = el("input");
      input.type = "file";
      input.accept = "image/jpeg,image/png,image/webp";
      input.setAttribute("aria-label", `Téléverser le ${label.toLowerCase()}`);
      input.addEventListener("change", () => {
        const file = input.files[0];
        input.value = "";
        if (file) openPhotoPreparation(file, c, side);
      });
      upload.append(input);
      actions.append(capture, upload);
      figure.append(actions);
    }
    faces.append(figure);
  }
  photo.append(faces);
  if (c.catalog_id) renderCatalogueFigure(faces, c);
  photo.append(
    el(
      "span",
      c.deleted_at ? "Corbeille" : stockLabels[c.stock_state],
      "badge " + c.stock_state,
    ),
  );
  if (editAllowed() && !c.deleted_at) {
    const identify = el("button", "Identifier la carte", "primary");
    identify.type = "button";
    identify.addEventListener("click", () => {
      $("detail-dialog").close();
      startIntake(c).catch((e) => toast(e.message));
    });
    photo.append(identify);
  }
  if (!c.deleted_at) {
    // Folded until a result exists: three long panels otherwise bury the fiche.
    const tools = el("details", undefined, "detail-tools");
    tools.open = Boolean(c.variant_checks?.length || c.edition_checks?.length || c.condition_assessments?.length);
    tools.append(el("summary", "Contrôles assistés : finition, édition, état"));
    renderVariantCheck(tools, c);
    renderEditionCheck(tools, c);
    renderConditionAssessment(tools, c);
    photo.append(tools);
  }
  // Away from the everyday actions; its own form cannot sit inside the fiche's.
  const danger = el("div", undefined, "detail-danger");
  renderCopyRemoval(danger, c);
  form.append(
    el("h2", c.name),
    el(
      "p",
      `${c.number || "Sans référence"} · ${statusLabels[c.identification_status]}`,
      "subtitle",
    ),
  );
  form.addEventListener(
    "invalid",
    (e) => e.target.closest?.("details")?.setAttribute("open", ""),
    true,
  );
  const makeSection = (titleText, isOpen = true) => {
    const sec = el("details", undefined, "detail-section");
    sec.open = Boolean(isOpen);
    sec.append(el("summary", titleText, "detail-section-summary"));
    return sec;
  };
  const identitySection = makeSection("1. Identité & édition", true);
  field(identitySection, "name", "Nom", c.name).required = true;
  field(identitySection, "set_name", "Extension", c.set_name);
  let row = pair(identitySection);
  field(row, "number", "Référence", c.number);
  field(row, "language", "Langue", c.language, "text", [
    ["fr", "Français"],
    ["en", "Anglais"],
    ["ja", "Japonais"],
    ["de", "Allemand"],
    ["es", "Espagnol"],
    ["it", "Italien"],
    ["pt", "Portugais"],
    ["ko", "Coréen"],
    ["zh", "Chinois"],
    ["unknown", "Inconnue"],
  ]);
  const technical = el("details");
  technical.append(el("summary", "Identifiant catalogue et PV"));
  row = pair(technical);
  field(row, "catalog_id", "Identifiant catalogue (facultatif)", c.catalog_id);
  const hp = field(row, "hp", "PV", c.hp, "number");
  hp.min = "0";
  hp.max = "5000";
  field(
    identitySection,
    "identification_status",
    "Identification",
    c.identification_status,
    "text",
    [
      ["confirmed", "Identité confirmée"],
      ["review", "À vérifier"],
      ["unresolved", "À identifier"],
      ["failed", "Lecture échouée"],
    ],
  );
  identitySection.append(technical);
  form.append(identitySection);

  const physicalSection = makeSection(
    "2. Examen physique : état, finition & tampon",
    true,
  );
  row = pair(physicalSection);
  field(row, "condition", "État", c.condition, "text", [
    ["", "Inconnu"],
    ["NM", "NM"],
    ["EX", "EX"],
    ["GD", "GD"],
    ["LP", "LP"],
    ["PL", "PL"],
    ["PO", "PO"],
    ["NM/EX", "NM/EX"],
  ]);
  const checkLabel = el("label", undefined, "check-label");
  const check = el("input");
  check.type = "checkbox";
  check.name = "condition_confirmed";
  check.checked = Boolean(c.condition_confirmed);
  check.disabled = !editAllowed() || Boolean(c.deleted_at);
  checkLabel.append(
    check,
    document.createTextNode("État vérifié sur la carte"),
  );
  row.append(checkLabel);
  const markStates = [["unobserved", "Non examiné"], ["absent", "Absence constatée"], ["present", "Présent sur la carte"]];
  const stampState = field(physicalSection, "stamp_state", "Observation du tampon", c.stamp_state || "unobserved", "text", markStates);
  const stampText = field(physicalSection, "stamp", "Texte du tampon (conservé tel que lu)", c.stamp);
  stampText.maxLength = 120;
  const showStamp = () => {
    stampText.parentElement.hidden = stampState.value !== "present" && !stampText.value;
  };
  stampState.addEventListener("change", showStamp);
  showStamp();
  const marks = el("details");
  marks.append(el("summary", "Autre marque de distribution (facultatif)"));
  field(marks, "distribution_state", "Observation d’une marque de produit", c.distribution_state || "unobserved", "text", markStates);
  field(marks, "distribution", "Texte ou marque du produit", c.distribution || "").maxLength = 120;
  physicalSection.append(marks);
  const finish = field(physicalSection, "finish", "Finition observée sur la carte", c.finish || "", "text", [
    ["", "À déterminer"],
    ["non_holo", "Non holo (mate)"],
    ["holo", "Holo dans l’illustration"],
    ["holo_border", "Holo avec cadre brillant (Prime, LV.X…)"],
    ["reverse", "Reverse (fond brillant)"],
    ["special", "Autre finition / variante spéciale"],
  ]);
  const priceVariant = field(physicalSection, "foil", "Catégorie de prix", String(Boolean(c.foil)), "text", [
    ["false", "Standard (version normale de l’édition, mate ou holo d’origine)"],
    ["true", "Foil (reverse ou holo parallèle)"],
  ]);
  const categoryHint = el("p", undefined, "help");
  physicalSection.append(categoryHint);
  const displayCategory = (decision) => {
    priceVariant.parentElement.hidden = decision?.mode === "automatic";
    priceVariant.parentElement.firstChild.textContent = "Catégorie enregistrée · à vérifier";
    priceVariant.disabled = decision?.mode === "automatic" || !editAllowed() || Boolean(c.deleted_at);
    if (decision?.mode === "automatic") priceVariant.value = String(decision.foil);
    categoryHint.textContent = decision?.mode === "automatic"
      ? `Catégorie de prix calculée : ${decision.foil ? "Foil" : "Standard"} · ${decision.reason}`
      : `${decision?.reason || "Renseignez la finition observée."} La sélection manuelle est réservée aux cas particuliers.`;
  };
  displayCategory(c.price_category);
  const referenceHint = el("p", undefined, "help");
  const displayReference = (resolution) => {
    const states = { ambiguous: "plusieurs correspondances possibles", conflict: "correspondance contestée", provisional: "correspondance provisoire" };
    const status = states[resolution?.market_status];
    referenceHint.textContent = status ? `Produit Cardmarket : ${status}.${resolution.diagnostic ? ` ${resolution.diagnostic}` : ""}` : "";
  };
  displayReference(c.reference_resolution);
  physicalSection.append(referenceHint);
  // Never used in practice: kept only where an old observation exists.
  if (c.variant_observation)
    field(physicalSection, "variant_observation", "Observations de vérification", c.variant_observation, "textarea").maxLength = 1000;
  const variantLabel = el("label", undefined, "check-label");
  const variantCheck = el("input");
  variantCheck.type = "checkbox";
  variantCheck.name = "variant_confirmed";
  variantCheck.checked = Boolean(c.variant_confirmed);
  variantCheck.disabled = !editAllowed() || Boolean(c.deleted_at);
  variantLabel.append(variantCheck, document.createTextNode("Variante et tampon vérifiés sur la carte physique"));
  physicalSection.append(variantLabel);
  if (c.variant_confirmed)
    physicalSection.append(el("p", `Vérifiée par ${c.variant_verified_by} le ${new Date(c.variant_verified_at).toLocaleString("fr-FR")}.`, "help"));
  form.append(physicalSection);

  for (const key of ["name", "set_name", "number", "language", "catalog_id", "identification_status", "foil", "stamp", "stamp_state", "distribution", "distribution_state", "finish"])
    form.elements[key].addEventListener("change", () => { variantCheck.checked = false; });
  let categoryRequest = 0;
  for (const key of ["finish", "stamp", "stamp_state", "distribution", "distribution_state", "catalog_id", "identification_status", "number", "set_name", "language"])
    form.elements[key].addEventListener("change", async () => {
      const request = ++categoryRequest;
      const fields = Object.fromEntries(["finish", "stamp", "stamp_state", "distribution", "distribution_state", "catalog_id", "identification_status", "number", "set_name", "language"].map((name) => [name, form.elements[name].value || (name === "catalog_id" ? null : "")]));
      try {
        const decision = await api(`/copies/${id}/variant-preview`, { method: "POST", body: JSON.stringify(fields) });
        if (request === categoryRequest) { displayCategory(decision); displayReference(decision.reference_resolution); }
      } catch (err) {
        if (request === categoryRequest) { priceVariant.disabled = true; categoryHint.textContent = err.message; }
      }
    });

  const priceSection = makeSection(
    "3. Prix de référence, cotations & vitrine",
    true,
  );
  // renderPriceSnapshot(parent, card) reads parent.elements to preserve unsaved price inputs.
  priceSection.elements = form.elements;
  row = pair(priceSection);
  const price = field(
    row,
    "reference_price_eur",
    c.valuation?.price_variant_issue ? "Ancien prix de référence (€) · catégorie à corriger" : "Prix de référence (€)",
    c.reference_cents === null ? "" : c.reference_cents / 100,
    "number",
  );
  price.step = ".01";
  price.min = "0";
  priceSection.append(
    el(
      "p",
      c.price_date
        ? `${c.price_source || "Source non renseignée"} · ${new Date(c.price_date).toLocaleDateString("fr-FR")}. Une correction d’identité ou de variante retire le prix à revérifier.`
        : "Un prix vide reste indisponible. Le prix de vente se définit dans un lot.",
      "subtitle",
    ),
  );
  renderPriceSnapshot(priceSection, c);
  form.append(priceSection);

  const binderSection = makeSection("4. Classeur & notes", Boolean(c.notes));
  field(
    binderSection,
    "album_id",
    "Album",
    c.album_id,
    "text",
    state.summary.albums.map((a) => [a.id, a.name]),
  );
  row = pair(binderSection);
  for (const [name, label, max] of [
    ["page", "Page", 1000],
    ["position", "Pochette", 100],
  ]) {
    const input = field(row, name, label, c[name], "number");
    input.min = "1";
    input.max = String(max);
    input.required = true;
  }
  field(binderSection, "notes", "Notes", c.notes, "textarea");
  form.append(binderSection);

  const saveBar = el("div", undefined, "detail-save-bar");
  if (editAllowed() && !c.deleted_at) {
    const reason = field(saveBar, "reason", "Motif (facultatif)", "");
    reason.placeholder = "Correction manuelle";
    reason.maxLength = 1000;
    const save = el("button", "Enregistrer la correction", "primary");
    save.type = "submit";
    saveBar.append(save);
  }
  const error = el("p", "", "error");
  error.setAttribute("role", "alert");
  saveBar.append(error);
  form.append(saveBar);

  const source = el("details", undefined, "detail-section detail-archive");
  source.append(el("summary", "Lecture et référence d’origine", "detail-section-summary"));
  const raw = el(
    "pre",
    c.source
      ? JSON.stringify(c.source.data, null, 2)
      : "Exemplaire ajouté dans l’application.",
    "source-data",
  );
  source.append(raw);
  form.append(source);
  const history = el("details", undefined, "detail-section detail-archive");
  history.append(
    el(
      "summary",
      `Historique · ${c.history.length} événement${c.history.length > 1 ? "s" : ""}`,
    ),
  );
  const labels = {
    name: "Nom",
    set_name: "Extension",
    number: "Référence",
    catalog_id: "Catalogue",
    language: "Langue",
    hp: "PV",
    condition: "État",
    condition_confirmed: "État vérifié",
    finish: "Finition observée",
    variant_confirmed: "Variante vérifiée physiquement",
    variant_verified_at: "Date de vérification de variante",
    variant_verified_by: "Auteur de vérification de variante",
    variant_observation: "Observations de variante",
    identification_status: "Identification",
    foil: "Foil",
    stamp: "Tampon",
    album_id: "Album",
    page: "Page",
    position: "Pochette",
    reference_cents: "Prix de référence",
    price_source: "Source du prix",
    stock_state: "Stock",
    deleted_at: "Date de suppression",
    notes: "Notes",
    photo: "Photo",
  };
  for (const event of c.history) {
    const entry = el("div", undefined, "history-entry");
    entry.append(
      el(
        "strong",
        `${event.actor} · ${new Date(event.created_at).toLocaleString("fr-FR")}`,
      ),
      el("p", event.reason),
    );
    // Older series back photos recorded a null "before" state.
    const before = JSON.parse(event.before_json) || {},
      after = JSON.parse(event.after_json) || {};
    for (const [key, label] of Object.entries(labels)) {
      if (before[key] !== after[key] && event.kind !== "import") {
        const show = (v) =>
          key === "reference_cents"
            ? money(v)
            : v === null || v === undefined || v === ""
              ? "—"
              : String(v);
        entry.append(
          el("p", `${label} : ${show(before[key])} → ${show(after[key])}`),
        );
      }
    }
    history.append(entry);
  }
  form.append(history);
  const prices = el("details");
  prices.append(el("summary", `Relevés de prix · ${c.prices.length}`));
  for (const p of c.prices)
    prices.append(
      el(
        "p",
        `${money(p.amount_cents)} · ${p.variant === "foil" ? "Foil" : "Standard"} · ${p.source || "Source non renseignée"} · ${p.observed_at || "Date non renseignée"}`,
      ),
    );
  form.append(prices);
  if (c.bound_quotes?.length) {
    const history = el("details");
    history.append(el("summary", "Cotations liées au référentiel (historique)"));
    for (const q of c.bound_quotes)
      history.append(el("p", `${money(q.amount_cents)} · ${q.metric} · ${q.source} · ${q.observed_at}`));
    form.append(history);
  }
  if (c.deleted_at)
    for (const input of form.querySelectorAll("input, select, textarea"))
      input.disabled = true;
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    error.textContent = "";
    const data = new FormData(form),
      changes = { expected_version: c.version, reason: data.get("reason").trim() || "Correction manuelle" };
    for (const key of [
      "name",
      "set_name",
      "number",
      "language",
      "catalog_id",
      "identification_status",
      "condition",
      "album_id",
      "notes",
      "stamp",
      "stamp_state",
      "distribution",
      "distribution_state",
      "finish",
      "variant_observation",
    ]) {
      if (!form.elements[key]) continue; // A field the fiche no longer shows.
      let value = data.get(key);
      if (key === "catalog_id" && !value) value = null;
      if (value !== (c[key] ?? (key === "catalog_id" ? null : "")))
        changes[key] = value;
    }
    for (const key of ["page", "position", "hp"]) {
      const value = data.get(key) === "" ? null : Number(data.get(key));
      if (value !== c[key]) changes[key] = value;
    }
    for (const key of ["foil", "condition_confirmed", "variant_confirmed"]) {
      const value = key === "foil" ? priceVariant.value === "true" : data.has(key);
      if (value !== Boolean(c[key])) changes[key] = value;
    }
    // An explicit re-check can accompany a changed identity/print in this save.
    if (data.has("variant_confirmed") && ["name", "set_name", "number", "language", "catalog_id", "identification_status", "foil", "stamp", "stamp_state", "distribution", "distribution_state", "finish"].some((key) => key in changes))
      changes.variant_confirmed = true;
    const amount =
      data.get("reference_price_eur") === ""
        ? null
        : Number(data.get("reference_price_eur"));
    if (
      amount !== (c.reference_cents === null ? null : c.reference_cents / 100)
    ) {
      changes.reference_price_eur = amount;
      changes.price_source = amount === null ? "" : "Saisie manuelle";
    }
    try {
      await api("/copies/" + id, {
        method: "PATCH",
        body: JSON.stringify(changes),
      });
      await refreshSummary();
      await loadCards();
      await openDetail(id);
      toast("Correction enregistrée avec son historique.");
    } catch (err) {
      error.textContent = err.message;
    }
  });
  layout.append(photo, form);
  $("detail-body").append(layout, danger);
  if (!$("detail-dialog").open) $("detail-dialog").showModal();
}
