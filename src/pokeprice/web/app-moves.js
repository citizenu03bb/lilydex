"use strict";

let activeMoveBatch = null;
let lastAppliedMoveBatch = null;

function syncMoveUndoBar() {
  const bar = $("move-undo-bar");
  if (!bar) return;
  const visible = Boolean(
    editAllowed() &&
      lastAppliedMoveBatch &&
      lastAppliedMoveBatch.status === "applied",
  );
  bar.hidden = !visible;
  if (visible) {
    $("move-undo-summary").textContent = t("move.last_banner", {
      count: lastAppliedMoveBatch.data.items.length,
      album: lastAppliedMoveBatch.data.album_name,
    });
  }
}

function renderMoveBatch(job) {
  activeMoveBatch = job;
  if (job.status === "applied") {
    lastAppliedMoveBatch = job;
  } else if (lastAppliedMoveBatch?.id === job.id) {
    lastAppliedMoveBatch = null;
  }
  syncMoveUndoBar();
  const container = $("move-results");
  container.replaceChildren();
  const data = job.data;
  container.append(
    el(
      "p",
      t("move.summary", {
        count: data.items.length,
        album: data.album_name,
        status: t(`move.status.${job.status}`),
      }),
    ),
  );
  if (data.has_collisions && job.status === "preview") {
    container.append(
      el(
        "p",
        t("move.collision_warning", { count: data.collisions_count }),
        "error",
      ),
    );
  }
  const list = el("ol", undefined, "move-preview-list");
  for (const item of data.items) {
    const row = el("li", undefined, item.collision ? "move-item collision" : "move-item");
    const label = item.number ? `${item.name} (${item.number})` : item.name;
    row.append(
      el("strong", label),
      document.createTextNode(
        " · " +
          t("move.from_to", {
            from_album: item.from_album,
            from_page: item.from_page,
            from_position: item.from_position,
            to_album: item.to_album,
            to_page: item.to_page,
            to_position: item.to_position,
          }),
      ),
    );
    if (item.collision) {
      const occupants = item.occupied_by
        .map((o) => (o.number ? `${o.name} (${o.number})` : o.name))
        .join(", ");
      row.append(
        document.createTextNode(" · "),
        el("span", t("move.slot_occupied_by", { occupants }), "error"),
      );
    }
    if (item.published) {
      row.append(
        document.createTextNode(" · "),
        el("span", t("move.published_note"), "help"),
      );
    }
    list.append(row);
  }
  container.append(list);
  $("move-apply").hidden = job.status !== "preview";
  $("move-apply").disabled = Boolean(data.has_collisions);
  $("move-undo").hidden = job.status !== "applied";
  $("move-undo").disabled = false;
}

async function loadMoveHistory() {
  const history = $("move-history");
  if (!history) return;
  history.replaceChildren();
  const jobs = await api("/move-batches");
  for (const job of jobs) {
    const button = el(
      "button",
      t("move.history_item", {
        date: new Date(job.created_at).toLocaleString("fr-FR"),
        album: job.data.album_name,
        count: job.data.items.length,
        status: t(`move.status.${job.status}`),
      }),
    );
    button.type = "button";
    button.onclick = async () => {
      $("move-error").textContent = "";
      try {
        renderMoveBatch(await api(`/move-batches/${job.id}`));
      } catch (e) {
        $("move-error").textContent = e.message;
      }
    };
    history.append(button);
  }
}

async function requestMovePreview() {
  if (!state.selected.size || !$("move-album")?.value) return;
  const job = await api("/move-batches", {
    method: "POST",
    body: JSON.stringify({
      copies: [...state.selected.values()].map((c) => ({
        id: c.id,
        expected_version: c.version,
      })),
      album_id: $("move-album").value,
      mode: $("move-mode").value,
      start_page: Number($("move-start-page").value) || 1,
      start_position: Number($("move-start-position").value) || 1,
      slots: Number($("move-slots").value) || 9,
      reason: $("move-reason").value.trim() || t("move.default_reason"),
    }),
  });
  renderMoveBatch(job);
}

if ($("move-mode")) {
  $("move-mode").addEventListener("change", () => {
    $("move-slot-fields").hidden = $("move-mode").value !== "from_slot";
  });
}

if ($("move-selection")) {
  $("move-selection").addEventListener("click", async () => {
    const albums = state.summary?.albums || [];
    const firstCard = [...state.selected.values()][0];
    const preferred =
      albums.find((a) => a.id !== firstCard?.album_id)?.id || albums[0]?.id || "";
    options($("move-album"), albums, preferred);
    if (!$("move-reason").value.trim()) {
      $("move-reason").value = t("move.default_reason");
    }
    $("move-slot-fields").hidden = $("move-mode").value !== "from_slot";
    $("move-error").textContent = "";
    $("move-results").replaceChildren();
    $("move-apply").hidden = true;
    $("move-undo").hidden = true;
    $("move-dialog").showModal();
    try {
      await requestMovePreview();
      await loadMoveHistory();
    } catch (e) {
      $("move-error").textContent = e.message;
    }
  });
}

if ($("move-form")) {
  $("move-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (event.submitter) event.submitter.disabled = true;
    $("move-error").textContent = "";
    try {
      await requestMovePreview();
      await loadMoveHistory();
    } catch (e) {
      $("move-error").textContent = e.message;
    } finally {
      if (event.submitter) event.submitter.disabled = !state.selected.size;
    }
  });
}

if ($("move-apply")) {
  $("move-apply").addEventListener("click", async (event) => {
    if (!activeMoveBatch) return;
    event.target.disabled = true;
    $("move-error").textContent = "";
    try {
      const job = await api(`/move-batches/${activeMoveBatch.id}/apply`, {
        method: "POST",
        body: JSON.stringify({
          reason: $("move-reason").value.trim() || t("move.default_reason"),
        }),
      });
      renderMoveBatch(job);
      state.selected.clear();
      await refreshSummary();
      await loadCards();
      await loadMoveHistory();
      toast(t("move.applied_toast"));
    } catch (e) {
      $("move-error").textContent = e.message;
      event.target.disabled = Boolean(activeMoveBatch?.data?.has_collisions);
    }
  });
}

async function undoMoveJob(jobId, errorTarget) {
  const job = await api(`/move-batches/${jobId}/undo`, { method: "POST" });
  if (activeMoveBatch?.id === job.id && $("move-results")) {
    renderMoveBatch(job);
  } else if (lastAppliedMoveBatch?.id === job.id) {
    lastAppliedMoveBatch = null;
    syncMoveUndoBar();
  }
  await refreshSummary();
  await loadCards();
  if ($("move-dialog")?.open) await loadMoveHistory();
  toast(t("move.undone_toast"));
  if (errorTarget) errorTarget.textContent = "";
}

if ($("move-undo")) {
  $("move-undo").addEventListener("click", async (event) => {
    if (!activeMoveBatch) return;
    event.target.disabled = true;
    $("move-error").textContent = "";
    try {
      await undoMoveJob(activeMoveBatch.id, $("move-error"));
    } catch (e) {
      $("move-error").textContent = e.message;
      event.target.disabled = false;
    }
  });
}

if ($("move-undo-last")) {
  $("move-undo-last").addEventListener("click", async (event) => {
    if (!lastAppliedMoveBatch) return;
    event.target.disabled = true;
    try {
      await undoMoveJob(lastAppliedMoveBatch.id, null);
    } catch (e) {
      toast(e.message);
    } finally {
      event.target.disabled = false;
    }
  });
}

