"use strict";
// Close-up shots in series (decision 0048): the review agent's requests, card
// after card in binder order. A shot goes up in the background while the next
// card shows; the shots of one card go one after the other.
const Closeups = (() => {
  const GRIDS = { "2x2": [2, 2], "3x3": [3, 3], "3x4": [3, 4], "4x3": [4, 3], single: [1, 1] };
  let scope = null,
    queue = null,
    index = 0,
    viewIndex = 0,
    shownAt = 0;
  const times = [],
    chains = new Map(),
    failures = [];
  let inFlight = 0;
  const post = (path, data) => api(path, { method: "POST", body: JSON.stringify(data) });

  function status() {
    const text = [];
    if (inFlight) text.push(t("closeups.sending", { count: inFlight }));
    if (failures.length) text.push(t("closeups.failed", { count: failures.length }));
    $("closeups-status").textContent = text.join(" · ");
  }

  // -- Sending ---------------------------------------------------------------
  // Each card's shots chain on the version the previous one returned.
  function upload(step, view, file) {
    const previous = chains.get(step.copy_id) || Promise.resolve(step.version);
    inFlight++;
    status();
    const sent = previous
      .catch(() => null)
      .then(async (version) => {
        const current = version ?? (await api(`/copies/${step.copy_id}`)).version;
        const result = await api(
          `/closeups/${step.copy_id}/shot?version=${current}&view=${view.view}`,
          { method: "PUT", body: file, headers: { "Content-Type": file.type || "image/jpeg" } },
        );
        return result.version;
      });
    chains.set(step.copy_id, sent);
    sent
      .catch((error) => failures.push({ step, view, file, error: error.message }))
      .finally(() => {
        inFlight--;
        status();
        if (index >= (queue?.steps.length || 0) && $("closeups-form").hidden) finish();
      });
  }

  // -- One step ----------------------------------------------------------------
  function pocketGrid(step) {
    const [cols, rows] = GRIDS[step.grid] || GRIDS["3x3"];
    const grid = el("div", null, "closeup-grid");
    grid.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;
    grid.setAttribute("aria-hidden", "true");
    for (let cell = 1; cell <= cols * rows; cell++) {
      const pocket = el("span");
      if (cell === step.position) pocket.className = "here";
      grid.append(pocket);
    }
    return grid;
  }

  function show() {
    const steps = queue.steps;
    if (index >= steps.length) return finish();
    const step = steps[index],
      view = step.views[viewIndex];
    if (viewIndex === 0) shownAt = Date.now();
    $("closeups-summary").hidden = true;
    const box = $("closeups-step");
    box.hidden = false;
    box.replaceChildren();
    const head = el("p", t("closeups.progress", { index: index + 1, count: steps.length }), "help");
    const place = el("h3", t("closeups.place", { page: step.page, position: step.position }));
    const where = el("div", null, "closeup-where");
    where.append(pocketGrid(step));
    if (step.has_photo) {
      const img = el("img");
      img.src = `/api/copies/${step.copy_id}/photo?size=thumb`;
      img.alt = `${step.name} ${step.number}`;
      where.append(img);
    }
    const card = el("p");
    card.append(el("strong", `${step.name} ${step.number}`), document.createTextNode(` · ${step.set_name}`));
    const what = el("p", t(`closeups.view.${view.view}`), "closeup-what");
    const reason = el("p", view.reason, "help");
    const more =
      step.views.length > 1
        ? el("p", t("closeups.shot_of", { index: viewIndex + 1, count: step.views.length }), "help")
        : null;
    const take = el("button", t("closeups.take"), "primary");
    take.type = "button";
    take.id = "closeups-take";
    take.onclick = () =>
      CardMedia.capture((file) => {
        upload(step, view, file);
        next(true);
      });
    const skip = el("button", t("closeups.skip"));
    skip.type = "button";
    skip.onclick = () => next(false);
    const actions = el("div", null, "intake-actions");
    actions.append(take, skip);
    box.append(head, place, where, card, what, ...(more ? [more] : []), reason, actions);
    take.focus();
  }

  function next(shot) {
    const step = queue.steps[index];
    if (!step) return finish();
    if (shot && viewIndex + 1 < step.views.length) {
      viewIndex++;
      return show();
    }
    if (shot) times.push((Date.now() - shownAt) / 1000);
    index++;
    viewIndex = 0;
    show();
  }

  // -- The end -----------------------------------------------------------------
  const median = (values) => {
    const sorted = [...values].sort((a, b) => a - b);
    return sorted.length ? sorted[Math.floor((sorted.length - 1) / 2)] : 0;
  };

  function finish() {
    $("closeups-step").hidden = true;
    $("closeups-step").replaceChildren();
    const box = $("closeups-summary");
    box.hidden = false;
    box.replaceChildren();
    box.append(
      el(
        "p",
        queue.steps.length
          ? t("closeups.done", { cards: times.length, seconds: Math.round(median(times)) })
          : t("closeups.empty"),
      ),
      el("p", queue.apply ? t("closeups.applied") : t("closeups.simulated"), "help"),
    );
    if (failures.length) {
      const retry = el("button", t("closeups.retry", { count: failures.length }), "primary");
      retry.type = "button";
      retry.onclick = () => {
        for (const failed of failures.splice(0)) {
          chains.delete(failed.step.copy_id);
          upload(failed.step, failed.view, failed.file);
        }
        finish();
      };
      box.append(retry);
    }
    if (queue.handed.length) {
      box.append(el("h3", t("closeups.handed", { count: queue.handed.length })));
      const list = el("ol");
      for (const card of queue.handed)
        list.append(
          el(
            "li",
            `${card.name} ${card.number} · ${t("closeups.place", { page: card.page, position: card.position })} · ${card.reason}`,
          ),
        );
      box.append(list);
    }
    const verdicts = el("button", t("closeups.verdicts"));
    verdicts.type = "button";
    verdicts.onclick = () => results().catch((e) => toast(e.message));
    const again = el("button", t("closeups.again"));
    again.type = "button";
    again.onclick = () => start(scope).catch((e) => toast(e.message));
    const choose = el("button", t("closeups.choose"));
    choose.type = "button";
    choose.onclick = () => {
      $("closeups-form").hidden = false;
      $("closeups-summary").hidden = true;
    };
    const actions = el("div", null, "intake-actions");
    actions.append(verdicts, again, choose);
    box.append(actions, el("ol", null, "closeup-verdicts"));
  }

  async function results() {
    const rows = await post("/closeups/results", scope);
    const list = $("closeups-summary").querySelector(".closeup-verdicts");
    list.replaceChildren();
    for (const row of rows) {
      const outcome = row.verdict?.outcome || "pending";
      list.append(
        el(
          "li",
          `${row.name} ${row.number} · ${t("closeups.place", { page: row.page, position: row.position })} · ` +
            t(`closeups.outcome.${outcome}`) +
            (row.verdict?.reason ? ` · ${row.verdict.reason}` : ""),
        ),
      );
    }
  }

  // -- Opening -----------------------------------------------------------------
  async function start(chosen) {
    scope = chosen;
    $("closeups-error").textContent = "";
    $("closeups-step").hidden = true;
    $("closeups-summary").hidden = true;
    $("closeups-status").textContent = t("closeups.loading");
    queue = await post("/closeups/queue", scope);
    // During the series, the step stays at the top, the photo button in reach.
    $("closeups-form").hidden = true;
    index = viewIndex = 0;
    times.length = 0;
    status();
    $("closeups-count").textContent = t("closeups.count", {
      cards: queue.steps.length,
      shots: queue.shots,
      handed: queue.handed.length,
      pending: queue.pending.length,
    });
    show();
  }

  async function open(chosen) {
    const select = $("closeups-scope");
    select.replaceChildren();
    const add = (value, label) => {
      const option = el("option", label);
      option.value = JSON.stringify(value);
      select.append(option);
    };
    if (state.selected.size)
      add({ copy_ids: [...state.selected.keys()] }, t("closeups.scope.selection", { count: state.selected.size }));
    // A series link (/gestion?prises=…) brings its own list of copies.
    if (chosen?.copy_ids && !state.selected.size)
      add(chosen, t("closeups.scope.link", { count: chosen.copy_ids.length }));
    try {
      for (const item of (await api("/binder-imports")).filter((i) => i.status !== "closed"))
        add({ import_id: item.id }, t("closeups.scope.import", { album: item.album, date: item.created_at.slice(0, 10) }));
    } catch {
      // No import listed: the albums remain.
    }
    for (const album of state.summary?.albums || []) add({ album: album.id }, t("closeups.scope.album", { album: album.name }));
    if (chosen) select.value = JSON.stringify(chosen);
    $("closeups-form").hidden = false;
    $("closeups-step").hidden = true;
    $("closeups-summary").hidden = true;
    $("closeups-count").textContent = "";
    $("closeups-dialog").showModal();
    if (chosen) await start(chosen);
  }

  function attach() {
    const button = $("capture-closeups");
    if (!button) return;
    button.hidden = state.user?.role !== "admin";
    button.onclick = () => open().catch((e) => toast(e.message));
    $("closeups-form").onsubmit = (event) => {
      event.preventDefault();
      start(JSON.parse($("closeups-scope").value)).catch((e) => {
        $("closeups-error").textContent = e.message;
      });
    };
  }

  return Object.freeze({ attach, open });
})();
