"use strict";
const Workflows = (() => {
  let capture = null,
    backToken = null,
    queue = Promise.resolve(),
    debounce,
    batch = null;
  const post = (path, data) =>
    api(path, {
      method: "POST",
      ...(data ? { body: JSON.stringify(data) } : {}),
    });
  const form = () => $("add-form");
  const fields = () => {
    const data = {};
    for (const key of [
      "name",
      "number",
      "set_name",
      "language",
      "hp",
      "finish",
      "stamp",
      "stamp_state",
      "distribution",
      "distribution_state",
      "reason",
      "notes",
      "album_id",
      "page",
      "position",
    ])
      data[key] = form().elements[key].value;
    for (const key of ["page", "position"]) data[key] = Number(data[key]);
    data.hp = data.hp === "" ? null : Number(data.hp);
    data.chosen_catalog_id = intakeState.chosen;
    data.human_confirmed = $("intake-confirm").checked;
    if (!data.name) delete data.name;
    return data;
  };
  const image = (src, label) => {
    const figure = el("figure"),
      img = el("img");
    img.src = src;
    img.alt = label;
    img.loading = "lazy";
    figure.append(CardMedia.zoomButton(img), el("figcaption", label));
    return figure;
  };
  function attach(session) {
    capture = session;
    backToken = session?.data.back_token || null;
    $("series-banner").hidden = !capture;
    $("series-back").hidden = !capture;
    $("duplicate-alert").hidden = true;
    $("duplicate-alert").replaceChildren();
    if (capture) {
      const data = capture.data;
      form().elements.album_id.value = capture.album_id;
      form().elements.album_id.disabled = true;
      form().elements.page.value = data.page;
      form().elements.position.value = data.position;
      $("intake-title").textContent = "Saisie en série";
      $("intake-save").textContent = "Enregistrer et passer à la suivante";
      $("series-progress").textContent =
        `${data.completed} carte(s) enregistrée(s) · Page ${data.page}, pochette ${data.position}/${capture.slots}`;
      $("series-sync").textContent =
        "Recto → verso facultatif → vérification → carte suivante";
    }
    renderBack();
  }
  function renderBack() {
    $("series-back-preview").replaceChildren();
    $("series-back-remove").hidden = !backToken;
    if (backToken)
      $("series-back-preview").append(
        image(`/api/intake/${backToken}/photo`, "Verso de la carte en cours"),
      );
  }
  function persist(extra = {}) {
    clearTimeout(debounce);
    if (!capture || !intakeState.token) return queue;
    const sid = capture.id,
      token = intakeState.token;
    const data = {
      fields: fields(),
      page: Number(form().elements.page.value),
      position: Number(form().elements.position.value),
      front_token: token,
      back_token: backToken,
      ...extra,
    };
    // Capture each form snapshot immediately, serialize writes and version updates.
    const pending = queue.then(async () => {
      if (!capture || capture.id !== sid)
        throw Error("La série a changé. Reprenez-la avant de continuer.");
      const updated = await api(`/capture-sessions/${sid}`, {
        method: "PATCH",
        body: JSON.stringify({ expected_version: capture.version, ...data }),
      });
      capture = updated;
      $("series-sync").textContent =
        "Carte en cours conservée. Vous pouvez fermer et reprendre.";
      return updated;
    });
    // A failed request must remain visible; the next attempt may retry explicitly.
    queue = pending.catch(() => {});
    return pending;
  }
  function changed() {
    $("duplicate-alert").hidden = true;
    $("duplicate-alert").replaceChildren();
    if (!capture) return;
    $("series-sync").textContent = "Enregistrement de la carte en cours…";
    clearTimeout(debounce);
    debounce = setTimeout(
      () =>
        persist().catch((e) => {
          $("series-sync").textContent =
            `Enregistrement interrompu : ${e.message}`;
        }),
      350,
    );
  }
  async function restore(session) {
    const saved = session.data.fields;
    if (session.data.front_token) {
      const meta = await api(`/intake/${session.data.front_token}`);
      const latest = meta.searches.at(-1);
      if (latest) showIntakeCandidates(latest);
      if (saved.chosen_catalog_id) {
        const candidate = $("intake-candidates").querySelectorAll(
          ".intake-candidate",
        );
        const ids = (latest?.candidates || []).map((c) => c.id);
        const index = ids.indexOf(saved.chosen_catalog_id);
        if (index >= 0) candidate[index]?.click();
      }
    }
    for (const [key, value] of Object.entries(saved))
      if (form().elements[key]) form().elements[key].value = value ?? "";
    intakeState.chosen = saved.chosen_catalog_id || null;
    if (!intakeState.chosen) clearIntakeChoice();
    $("intake-confirm").checked = Boolean(saved.human_confirmed);
    if (intakeState.chosen) $("intake-confirm-label").hidden = false;
    backToken = session.data.back_token;
    renderBack();
    await persist();
  }
  async function refresh() {
    $("capture-series").hidden = !editAllowed();
    selection();
    $("capture-resume").replaceChildren();
    if (!editAllowed()) {
      $("capture-resume").hidden = true;
      return;
    }
    const sessions = await api("/capture-sessions");
    $("capture-resume").hidden = !sessions.length;
    for (const session of sessions) {
      const album =
        state.summary.albums.find((a) => a.id === session.album_id)?.name ||
        "Album";
      const row = el("div", undefined, "workflow-actions");
      row.append(
        el(
          "span",
          `${album} · P.${session.data.page} #${session.data.position} · ${session.data.completed} carte(s)`,
        ),
      );
      const resume = el("button", "Reprendre la série");
      resume.onclick = async () => {
        try {
          let latest = await api(`/capture-sessions/${session.id}`);
          if (latest.status === "paused")
            latest = await api(`/capture-sessions/${session.id}`, {
              method: "PATCH",
              body: JSON.stringify({
                expected_version: latest.version,
                status: "active",
              }),
            });
          await startIntake(null, latest);
        } catch (e) {
          toast(e.message);
        }
      };
      const close = el("button", "Terminer cette série");
      close.onclick = async () => {
        try {
          const latest = await api(`/capture-sessions/${session.id}`);
          await api(`/capture-sessions/${session.id}`, {
            method: "PATCH",
            body: JSON.stringify({
              expected_version: latest.version,
              status: "closed",
            }),
          });
          if (capture?.id === session.id) attach(null);
          await refresh();
        } catch (e) {
          toast(e.message);
        }
      };
      row.append(resume, close);
      $("capture-resume").append(row);
    }
  }
  async function prepareSave(data) {
    if (capture) {
      await queue;
      const latest = await api(`/capture-sessions/${capture.id}`);
      if (latest.data.last_token === intakeState.token) {
        capture = latest;
        return {
          url: `/capture-sessions/${capture.id}/save`,
          data: {
            ...data,
            expected_version: capture.version,
            token: intakeState.token,
          },
        };
      }
    }
    if (intakeState.existing)
      return { url: `/intake/${intakeState.token}/save`, data };
    const matches = await post(`/intake/${intakeState.token}/duplicates`, data);
    const accepted = new Set(
      Array.from($("duplicate-alert").querySelectorAll("input:checked")).map(
        (i) => i.value,
      ),
    );
    if (matches.some((m) => !accepted.has(m.acknowledgment))) {
      const alert = $("duplicate-alert");
      alert.replaceChildren();
      alert.hidden = false;
      alert.append(el("h3", "Vérifier les exemplaires proches"));
      for (const match of matches) {
        const row = el("div");
        row.append(
          el(
            "p",
            `${match.name} · ${match.album} P.${match.page} #${match.position} — ${match.reasons.join(" ; ")}`,
          ),
        );
        const open = el("button", "Ouvrir cet exemplaire");
        open.type = "button";
        open.onclick = async () => {
          $("add-dialog").close();
          await openDetail(match.id);
        };
        row.append(open);
        const label = el("label", undefined, "check-label"),
          check = el("input");
        check.type = "checkbox";
        check.value = match.acknowledgment;
        check.checked = accepted.has(match.acknowledgment);
        label.append(
          check,
          document.createTextNode(
            "J’ai vérifié : j’ajoute un exemplaire physique distinct.",
          ),
        );
        row.append(label);
        alert.append(row);
      }
      alert.scrollIntoView({ block: "nearest" });
      throw Error(
        "Vérifiez les alertes et confirmez chaque exemplaire distinct avant d’enregistrer.",
      );
    }
    data.duplicate_acknowledgments = matches.map((m) => m.acknowledgment);
    if (!capture) return { url: `/intake/${intakeState.token}/save`, data };
    await persist();
    return {
      url: `/capture-sessions/${capture.id}/save`,
      data: {
        ...data,
        expected_version: capture.version,
        token: intakeState.token,
      },
    };
  }
  async function next(session) {
    const token = intakeState.token;
    intakeState.token = null;
    attach(null);
    if (session.status === "closed") {
      $("add-dialog").close();
      await refresh();
      return;
    }
    // Keep the dialogue open so Android can immediately take the next photo.
    await startIntake(null, session);
    if (token) api(`/intake/${token}`, { method: "DELETE" }).catch(() => {});
    $("intake-status").textContent =
      "Carte enregistrée. Photographiez la suivante ; vérifiez son emplacement.";
    $("add-dialog").scrollTop = 0;
    await refresh();
  }
  function selection() {
    $("batch-photos").hidden = !editAllowed();
    $("batch-photos").textContent = state.selected.size
      ? "Préparer les photos sélectionnées"
      : "Photos par lot";
    $("batch-preview-button").disabled = !state.selected.size;
  }
  async function backupStatus() {
    if (state.user?.role !== "admin") return;
    const data = await api("/backup/status"),
      target = $("backup-status");
    target.replaceChildren();
    const date = (item) => new Date(item.verified_at).toLocaleString("fr-FR");
    target.append(
      el(
        "p",
        data.local
          ? `Locale restaurée et vérifiée : ${date(data.local)} · ${data.local.copies} exemplaires`
          : "Aucune sauvegarde quotidienne vérifiée pour l’instant.",
      ),
    );
    target.append(
      el(
        "p",
        data.external
          ? `Copie Drive : ${date(data.external)} · ${{ "download-decrypt-sha256-restore": "chiffrée, puis téléchargée, déchiffrée, SHA-256 et restauration vérifiés", "download-sha256-restore": "non chiffrée ; téléchargée, SHA-256 et restauration vérifiés" }[data.external.verification] || "taille vérifiée"}`
          : "Copie Drive en attente.",
      ),
    );
    target.append(
      el(
        "p",
        "Sauvegarde locale chaque jour à 3 h ; copie Drive automatique à 3 h 15, avec deux nouvelles tentatives en cas d’échec. Le portable et une session utilisateur doivent être actifs ; Internet est nécessaire pour Drive.",
        "help",
      ),
    );
    const link = el("a", "Ouvrir le dossier privé Drive", "button");
    link.href = data.drive_folder_url;
    link.target = "_blank";
    link.rel = "noopener";
    target.append(link);
    if (data.last_error) target.append(el("p", data.last_error, "error"));
    for (const [key, label] of [
      ["local", "locale"],
      ["external", "Drive"],
    ]) {
      if (
        data[key] &&
        Date.now() - Date.parse(data[key].verified_at) > 36 * 3600000
      )
        target.append(
          el(
            "p",
            `La sauvegarde ${label} date de plus de 36 heures. Vérifiez la dernière exécution.`,
            "error",
          ),
        );
    }
  }
  function renderBatch(job) {
    batch = job;
    $("batch-results").replaceChildren();
    for (const item of job.data.items) {
      const row = el("section", undefined, "batch-card"),
        label = el("label", undefined, "check-label"),
        check = el("input");
      check.type = "checkbox";
      check.value = item.id;
      check.checked = Boolean(item.result);
      check.disabled = !item.result || job.status !== "preview";
      label.append(
        check,
        document.createTextNode(
          item.name + (item.location ? " · " + item.location : ""),
        ),
      );
      row.append(label);
      if (item.result) {
        const compare = el("div", undefined, "intake-comparison");
        for (const [view, title] of [
          ["before", "Avant"],
          ["result", "Après"],
        ])
          compare.append(
            image(
              `/api/photo-batches/${job.id}/photo/${item.id}/${view}`,
              title,
            ),
          );
        row.append(compare);
        row.append(el("p", item.processing.message, "help"));
        if (item.fallback)
          row.append(
            el(
              "p",
              "Photo entière indisponible : simulation à partir de la photo enregistrée.",
              "help",
            ),
          );
      } else row.append(el("p", "Photo absente pour cette face.", "help"));
      $("batch-results").append(row);
    }
    $("batch-apply").hidden = job.status !== "preview";
    $("batch-undo").hidden = job.status !== "applied";
  }
  $("display-mode").onchange = () => {
    state.offset = 0;
    syncLocation("push");
    loadCards().catch((e) => toast(e.message));
  };
  $("capture-series").onclick = () => {
    $("series-error").textContent = "";
    options(
      $("series-form").elements.album_id,
      state.summary.albums,
      state.summary.albums[0]?.id,
    );
    $("series-dialog").showModal();
  };
  $("series-form").onsubmit = async (event) => {
    event.preventDefault();
    const submit = event.submitter;
    submit.disabled = true;
    try {
      const form = event.target;
      let album = form.elements.album_id.value;
      if (form.elements.album_name.value.trim()) {
        const created = await post("/albums", {
          name: form.elements.album_name.value,
        });
        album = created.id;
        await refreshSummary();
      }
      const session = await post("/capture-sessions", {
        album_id: album,
        slots: Number(form.elements.slots.value),
        page: Number(form.elements.page.value),
        position: Number(form.elements.position.value),
      });
      $("series-dialog").close();
      await startIntake(null, session);
      await refresh();
    } catch (e) {
      $("series-error").textContent = e.message;
    } finally {
      submit.disabled = false;
    }
  };
  $("add-form").addEventListener("input", (event) => {
    if (!$("duplicate-alert").contains(event.target)) changed();
  });
  $("add-form").addEventListener("change", (event) => {
    if (!$("duplicate-alert").contains(event.target)) changed();
  });
  $("series-pause").onclick = async () => {
    try {
      await persist({ status: "paused" });
      $("add-dialog").close();
      await refresh();
    } catch (e) {
      toast(e.message);
    }
  };
  async function uploadBack(file) {
    if (!file || !capture || intakeState.busy) return;
    const sid = capture.id,
      old = backToken;
    intakeBusy(true, "Préparation du verso…");
    try {
      const result = await api("/intake/photo", {
        method: "POST",
        body: file,
        headers: CardMedia.photoHeaders(file),
      });
      if (capture?.id !== sid) return;
      backToken = result.token;
      await persist();
      renderBack();
      if (old) api(`/intake/${old}`, { method: "DELETE" }).catch(() => {});
    } catch (e) {
      $("add-error").textContent = e.message;
    } finally {
      intakeBusy(false);
    }
  }
  $("series-back-camera").onclick = () => CardMedia.capture(uploadBack);
  $("series-back-file").onchange = (event) => {
    const file = event.target.files[0];
    event.target.value = "";
    uploadBack(file);
  };
  $("series-back-remove").onclick = async () => {
    const previous = backToken;
    backToken = null;
    try {
      await persist();
      renderBack();
      if (previous) await api(`/intake/${previous}`, { method: "DELETE" });
    } catch (e) {
      backToken = previous;
      toast(e.message);
    }
  };
  $("backup-now").onclick = async (event) => {
    event.target.disabled = true;
    $("backup-error").textContent = "";
    try {
      await post("/backup/daily");
      await backupStatus();
    } catch (e) {
      $("backup-error").textContent = e.message;
    } finally {
      event.target.disabled = false;
    }
  };
  $("batch-photos").onclick = async () => {
    $("batch-dialog").showModal();
    $("batch-error").textContent = "";
    $("batch-results").replaceChildren();
    $("batch-apply").hidden = true;
    $("batch-undo").hidden = true;
    $("batch-history").replaceChildren();
    try {
      const jobs = await api("/photo-batches");
      for (const job of jobs) {
        const resume = el(
          "button",
          `${new Date(job.created_at).toLocaleString("fr-FR")} · ${job.data.items.length} photo(s) · ${{ preview: "simulation", applied: "appliqué", undone: "annulé" }[job.status]}`,
        );
        resume.onclick = async () => {
          try {
            renderBatch(await api(`/photo-batches/${job.id}`));
          } catch (e) {
            $("batch-error").textContent = e.message;
          }
        };
        $("batch-history").append(resume);
      }
    } catch (e) {
      $("batch-error").textContent = e.message;
    }
  };
  $("batch-form").onsubmit = async (event) => {
    event.preventDefault();
    event.submitter.disabled = true;
    $("batch-error").textContent = "";
    try {
      if (state.selected.size > 20)
        throw Error(
          "Limitez la sélection à 20 exemplaires pour ce traitement.",
        );
      const form = event.target;
      renderBatch(
        await post("/photo-batches", {
          copies: [...state.selected.values()].map((c) => ({
            id: c.id,
            expected_version: c.version,
          })),
          side: form.elements.side.value,
          options: Object.fromEntries(
            ["crop", "perspective", "balance"].map((k) => [
              k,
              form.elements[k].checked,
            ]),
          ),
        }),
      );
    } catch (e) {
      $("batch-error").textContent = e.message;
    } finally {
      event.submitter.disabled = false;
    }
  };
  for (const action of ["apply", "undo"])
    $("batch-" + action).onclick = async (event) => {
      if (!batch) return;
      event.target.disabled = true;
      $("batch-error").textContent = "";
      try {
        const ids = Array.from(
          $("batch-results").querySelectorAll("input:checked"),
        ).map((c) => c.value);
        renderBatch(
          await post(
            `/photo-batches/${batch.id}/${action}`,
            action === "apply" ? { copy_ids: ids } : null,
          ),
        );
        state.selected.clear();
        await loadCards();
        toast(
          action === "apply"
            ? "Photos appliquées. Sauvegarde conservée ; retour arrière disponible ici."
            : "Traitement annulé.",
        );
      } catch (e) {
        $("batch-error").textContent = e.message;
      } finally {
        event.target.disabled = false;
      }
    };
  return {
    get capture() {
      return capture;
    },
    attach,
    persist,
    changed,
    restore,
    refresh,
    prepareSave,
    next,
    selection,
    backupStatus,
  };
})();
