/* Keyboard browsing of the collection: grid focus moves and a full-screen viewer. */

"use strict";
const Gallery = (() => {
  // Index of the card above or below `from`, by on-screen position, or -1.
  // It works for the plain grid and for the stacked grids of editions.
  function neighbour(rects, from, direction) {
    const origin = rects[from],
      centre = origin.left + origin.width / 2;
    let best = -1,
      bestRow = Infinity,
      bestGap = Infinity;
    rects.forEach((rect, index) => {
      const row = (rect.top - origin.top) * direction;
      if (index === from || row < 1) return;
      const gap = Math.abs(rect.left + rect.width / 2 - centre);
      if (row < bestRow - 1 || (Math.abs(row - bestRow) <= 1 && gap < bestGap)) {
        best = index;
        bestRow = row;
        bestGap = gap;
      }
    });
    return best;
  }
  // Offset of the result page holding global position `index`.
  function pageOffset(offset, limit, index) {
    return Math.max(0, offset + Math.floor((index - offset) / limit) * limit);
  }
  const lastOffset = () =>
    Math.max(0, pageOffset(state.offset, state.limit, state.total - 1));
  const grouped = () => $("display-mode").value === "editions";
  const binderSort = () => $("sort-order").value === "binder";
  const binderPage = (card) => `${card.album_id ?? card.album}|${card.page}`;
  const typing = (target) =>
    target.isContentEditable ||
    (["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName) &&
      target.type !== "checkbox");

  let busy = false,
    replay = null,
    lastFocused = null;
  const moves = ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End", "PageUp", "PageDown"];
  // Page loads go one at a time. The last move key pressed meanwhile is
  // replayed afterwards, from wherever the load left the focus.
  function waiting(event, handler) {
    if (!busy) return false;
    if (moves.includes(event.key)) {
      event.preventDefault();
      replay = { key: event.key, ctrlKey: event.ctrlKey, handler };
    }
    return true;
  }
  async function exclusive(task) {
    if (busy) return;
    busy = true;
    document.body.classList.add("gallery-loading");
    try {
      await task();
    } catch (error) {
      toast(error.message);
    } finally {
      busy = false;
      document.body.classList.remove("gallery-loading");
    }
    const next = replay;
    replay = null;
    if (next)
      next.handler({
        key: next.key,
        ctrlKey: next.ctrlKey,
        altKey: false,
        metaKey: false,
        target: document.activeElement,
        preventDefault() {},
      });
  }
  async function loadPage(offset) {
    if (offset === state.offset) return;
    state.offset = offset;
    syncLocation("push");
    await loadCards();
  }

  // Grid
  const gridCards = () =>
    Array.from($("cards").querySelectorAll(".card")).filter(
      (card) => card.offsetParent !== null,
    );
  const gridCard = (id) =>
    $("cards").querySelector(`.card[data-copy-id="${CSS.escape(id)}"]`);
  function focusCard(card) {
    card?.querySelector(".card-open")?.focus();
  }
  function focusAt(place) {
    const cards = gridCards();
    focusCard(place === "last" ? cards.at(-1) : cards[Math.min(place, cards.length - 1)]);
  }
  function turnPage(offset, place) {
    return exclusive(async () => {
      await loadPage(offset);
      focusAt(place);
    });
  }
  function gridKey(event) {
    if (event.altKey || event.metaKey || typing(event.target)) return;
    const card = event.target.closest(".card");
    if (!card || waiting(event, gridKey)) return;
    const cards = gridCards(),
      index = cards.indexOf(card),
      more = state.offset + state.limit < state.total,
      control = event.ctrlKey;
    const key = event.key;
    if (control && key !== "Home" && key !== "End") return;
    if (key === "ArrowRight") {
      if (index + 1 < cards.length) focusCard(cards[index + 1]);
      else if (more) turnPage(state.offset + state.limit, 0);
    } else if (key === "ArrowLeft") {
      if (index > 0) focusCard(cards[index - 1]);
      else if (state.offset > 0)
        turnPage(Math.max(0, state.offset - state.limit), "last");
    } else if (key === "ArrowDown" || key === "ArrowUp") {
      const rects = cards.map((c) => c.getBoundingClientRect());
      const target = neighbour(rects, index, key === "ArrowDown" ? 1 : -1);
      if (target >= 0) focusCard(cards[target]);
    } else if (key === "Home") {
      if (control) turnPage(0, 0);
      else focusAt(0);
    } else if (key === "End") {
      if (control) turnPage(lastOffset(), "last");
      else focusAt("last");
    } else if (key === "PageDown") {
      if (more) turnPage(state.offset + state.limit, index);
      else focusAt("last");
    } else if (key === "PageUp") {
      if (state.offset > 0)
        turnPage(Math.max(0, state.offset - state.limit), index);
      else focusAt(0);
    } else if (key === " ") {
      const check = card.querySelector(".card-select input");
      if (!check || event.target === check) return;
      check.click();
    } else if (key === "v" || key === "V") open(card.dataset.copyId);
    else return;
    event.preventDefault();
  }

  // Viewer
  const viewer = { id: null, side: "front", strip: null };
  // Full-size photos already fetched; the elements themselves are reused,
  // since the server forbids caching private photos.
  const photos = new Map();
  const dialog = () => $("viewer-dialog");
  const current = () => state.visibleCards.find((c) => c.id === viewer.id);
  const localIndex = () =>
    state.visibleCards.findIndex((c) => c.id === viewer.id);
  function photoElement(card, side) {
    const key = `${card.id}:${side}:${card.version}`;
    let image = photos.get(key);
    if (!image) {
      image = el("img");
      image.alt = `${side === "front" ? "Recto" : "Verso"} de ${card.name}`;
      image.decoding = "async";
      image.draggable = false;
      image.src = `/api/copies/${card.id}/photo?${side === "back" ? "side=back&" : ""}v=${card.version}`;
      photos.set(key, image);
      if (photos.size > 40) photos.delete(photos.keys().next().value);
    } else {
      photos.delete(key);
      photos.set(key, image);
    }
    return image;
  }
  function preload(index) {
    for (const step of [1, -1, 2, 3, -2]) {
      const card = state.visibleCards[index + step];
      if (card?.photo) photoElement(card, "front");
    }
  }
  function open(id) {
    if (!state.visibleCards.length) return;
    viewer.id = state.visibleCards.some((c) => c.id === id)
      ? id
      : state.visibleCards[0].id;
    viewer.side = "front";
    for (const name of Object.keys(panels))
      dialog().classList.toggle(name + "-open", remembered(name));
    for (const [name, id] of Object.entries(panels))
      $(id).setAttribute("aria-pressed", String(remembered(name)));
    if (!dialog().open) dialog().showModal();
    render();
    $("viewer-photo").focus();
  }
  function show(index) {
    const card = state.visibleCards[Math.max(0, Math.min(index, state.visibleCards.length - 1))];
    if (!card) return;
    viewer.id = card.id;
    viewer.side = "front";
    render();
  }
  async function cardAt(index) {
    let local = index - state.offset;
    if (local < 0 || local >= state.visibleCards.length) {
      await loadPage(pageOffset(state.offset, state.limit, index));
      local = index - state.offset;
    }
    return state.visibleCards[local];
  }
  // Copies are numbered across result pages; editions only within a page.
  function go(target) {
    return exclusive(async () => {
      if (grouped()) {
        const length = state.visibleCards.length;
        if (target >= length && state.offset + state.limit < state.total) {
          await loadPage(state.offset + state.limit);
          target = 0;
        } else if (target < 0 && state.offset > 0) {
          await loadPage(Math.max(0, state.offset - state.limit));
          target = state.visibleCards.length - 1;
        }
        show(target);
        return;
      }
      target = Math.max(0, Math.min(target, state.total - 1));
      await cardAt(target);
      show(target - state.offset);
    });
  }
  function step(delta) {
    const index = localIndex();
    return go(grouped() ? index + delta : state.offset + index + delta);
  }
  function edge(end) {
    if (!grouped()) return go(end ? state.total - 1 : 0);
    return exclusive(async () => {
      await loadPage(end ? lastOffset() : 0);
      show(end ? state.visibleCards.length - 1 : 0);
    });
  }
  // First card of the next, or previous, binder page in the sorted results.
  function binderJump(direction) {
    return exclusive(async () => {
      let index = state.offset + localIndex();
      const start = binderPage(await cardAt(index));
      if (direction > 0) {
        while (index + 1 < state.total) {
          index++;
          if (binderPage(await cardAt(index)) !== start) break;
        }
      } else {
        while (index > 0 && binderPage(await cardAt(index - 1)) === start) index--;
        if (index > 0) {
          const previous = binderPage(await cardAt(--index));
          while (index > 0 && binderPage(await cardAt(index - 1)) === previous)
            index--;
        }
      }
      await cardAt(index);
      show(index - state.offset);
    });
  }
  function jump(direction) {
    if (grouped())
      return exclusive(async () => {
        const more = state.offset + state.limit < state.total;
        if (direction > 0 && more) await loadPage(state.offset + state.limit);
        else if (direction < 0 && state.offset > 0)
          await loadPage(Math.max(0, state.offset - state.limit));
        else if (direction > 0) return show(state.visibleCards.length - 1);
        show(0);
      });
    if (binderSort()) return binderJump(direction);
    return step(10 * direction);
  }
  function toggleSelection() {
    const card = current(),
      check = card && gridCard(card.id)?.querySelector(".card-select input");
    if (!check) return;
    selectCopy(card, !state.selected.has(card.id));
    render();
  }
  function render() {
    const card = current();
    if (!card) return;
    const index = localIndex();
    $("viewer-position").textContent = grouped()
      ? `${index + 1} / ${state.visibleCards.length} sur cette page · éditions ${state.offset + 1}–${Math.min(state.offset + state.limit, state.total)} sur ${state.total}`
      : `${state.offset + index + 1} / ${state.total}`;
    $("viewer-previous").disabled = index === 0 && state.offset === 0;
    $("viewer-next").disabled =
      index === state.visibleCards.length - 1 &&
      state.offset + state.limit >= state.total;

    const side = viewer.side,
      name = side === "front" ? card.photo : card.back_photo;
    $("viewer-photo").replaceChildren(
      name
        ? photoElement(card, side)
        : el("p", `Photo du ${side === "front" ? "recto" : "verso"} absente.`, "no-photo"),
    );
    preload(index);
    $("viewer-flip").textContent = side === "front" ? "Verso" : "Recto";
    $("viewer-flip").setAttribute("aria-label", side === "front" ? "Voir le verso" : "Voir le recto");

    // One line over the photo: enough to name, price and find the card.
    const caption = el("p", undefined, "viewer-caption-name");
    caption.append(
      el("strong", card.name),
      document.createTextNode(
        ` · ${card.set_name || "Extension à préciser"} ${card.number || ""}`.trimEnd(),
      ),
    );
    $("viewer-caption").replaceChildren(
      ...(side === "back" ? [el("span", "Verso", "viewer-side")] : []),
      caption,
      el(
        "span",
        money(card.valuation?.prudent_cents),
        "viewer-caption-price" + (card.valuation?.prudent_cents == null ? " unknown-price" : ""),
      ),
      el("span", `${card.album} · P.${card.page} #${card.position}`, "viewer-caption-place"),
    );

    const info = $("viewer-info");
    info.replaceChildren(
      el("span", (card.language || "?").toUpperCase(), "card-language"),
      el("h3", card.name),
      el(
        "p",
        `${card.set_name || "Extension à préciser"} · ${card.number || "Référence à préciser"}`,
        "card-set",
      ),
      el("p", `${card.album} · page ${card.page}, pochette ${card.position}`),
      el(
        "p",
        `${card.condition || "État inconnu"}${card.foil ? " · Foil" : ""}${card.stamp ? " · Tampon" : ""}`,
      ),
    );
    const badges = el("p", undefined, "viewer-badges");
    badges.append(
      el(
        "span",
        statusLabels[card.identification_status],
        "badge" + (card.identification_status === "confirmed" ? "" : " review"),
      ),
      el(
        "span",
        card.deleted_at ? "Corbeille" : stockLabels[card.stock_state],
        "badge " + card.stock_state,
      ),
    );
    if (card.valuation?.needs_review)
      badges.append(el("span", "À examiner", "badge review"));
    info.append(
      badges,
      el(
        "p",
        `Prudente : ${money(card.valuation?.prudent_cents)}`,
        "viewer-price" + (card.valuation?.prudent_cents == null ? " unknown-price" : ""),
      ),
    );
    if (card.valuation?.needs_review)
      info.append(
        el("p", card.valuation.reasons.map((r) => r.label).join(" · "), "review-reasons"),
      );
    const actions = el("div", undefined, "viewer-actions");
    const detail = el("button", "Ouvrir la fiche", "primary");
    detail.type = "button";
    detail.setAttribute("aria-keyshortcuts", "Enter");
    detail.addEventListener("click", () => openDetail(card.id).catch((e) => toast(e.message)));
    actions.append(detail);
    if (gridCard(card.id)?.querySelector(".card-select input")) {
      const select = el(
        "button",
        state.selected.has(card.id) ? "Retirer de la sélection" : "Sélectionner",
      );
      select.type = "button";
      select.setAttribute("aria-keyshortcuts", "Space");
      select.setAttribute("aria-pressed", String(state.selected.has(card.id)));
      select.addEventListener("click", toggleSelection);
      actions.append(select);
    }
    info.append(
      actions,
      el(
        "p",
        "←/→ carte · Pg↑/Pg↓ saut de 10, ou page de classeur en tri Classeur · Début/Fin · R recto/verso · I informations · T bande · Entrée fiche · Espace sélection · Échap ou V fermer",
        "help viewer-help",
      ),
    );
    renderStrip(index);
  }
  function renderStrip(index) {
    const strip = $("viewer-strip");
    if (viewer.strip !== state.visibleCards) {
      viewer.strip = state.visibleCards;
      strip.replaceChildren(
        ...state.visibleCards.map((card, i) => {
          const button = el("button", undefined, "viewer-thumb");
          button.type = "button";
          button.tabIndex = -1;
          button.setAttribute("aria-label", `${card.name}, ${card.number || "référence à préciser"}`);
          if (card.photo) {
            const image = el("img");
            image.src = `/api/copies/${card.id}/photo?size=thumb&v=${card.version}`;
            image.alt = "";
            image.loading = "lazy";
            button.append(image);
          } else button.append(el("span", card.name, "no-photo"));
          button.addEventListener("click", () => show(i));
          return button;
        }),
      );
    }
    Array.from(strip.children).forEach((button, i) => {
      button.classList.toggle("current", i === index);
      if (i === index) {
        button.setAttribute("aria-current", "true");
        // Scrolls the strip only: scrollIntoView could also move the dialog.
        strip.scrollLeft =
          button.offsetLeft - (strip.clientWidth - button.offsetWidth) / 2;
      } else button.removeAttribute("aria-current");
      button.classList.toggle("selected", state.selected.has(state.visibleCards[i].id));
    });
  }
  function flip() {
    viewer.side = viewer.side === "front" ? "back" : "front";
    render();
  }
  // The photo fills the screen; the details and the strip are shown on
  // demand, and the choice is remembered on this device.
  const panels = { info: "viewer-info-toggle", strip: "viewer-strip-toggle" };
  function remembered(name) {
    try {
      return localStorage.getItem("pokeprice.viewer." + name) === "1";
    } catch {
      return false;
    }
  }
  function toggle(name, open = !dialog().classList.contains(name + "-open")) {
    dialog().classList.toggle(name + "-open", open);
    $(panels[name]).setAttribute("aria-pressed", String(open));
    try {
      localStorage.setItem("pokeprice.viewer." + name, open ? "1" : "0");
    } catch {}
    if (open && name === "strip") renderStrip(localIndex());
  }
  function viewerKey(event) {
    if (event.altKey || event.metaKey || event.ctrlKey || typing(event.target)) return;
    if (waiting(event, viewerKey)) return;
    const onControl = event.target.closest("button, a");
    const key = event.key;
    if (key === "ArrowRight") step(1);
    else if (key === "ArrowLeft") step(-1);
    else if (key === "Home") edge(false);
    else if (key === "End") edge(true);
    else if (key === "PageDown") jump(1);
    else if (key === "PageUp") jump(-1);
    else if (key === "r" || key === "R") flip();
    else if (key === "i" || key === "I") toggle("info");
    else if (key === "t" || key === "T") toggle("strip");
    else if (key === "Enter" && !onControl)
      openDetail(viewer.id).catch((e) => toast(e.message));
    else if (key === " " && !onControl) toggleSelection();
    else if (key === "v" || key === "V") dialog().close();
    else return;
    event.preventDefault();
  }

  function rendered(focusedId) {
    if (dialog()?.open) {
      if (!current()) show(Math.min(Math.max(0, localIndex()), state.visibleCards.length - 1));
      else render();
      if (!state.visibleCards.length) dialog().close();
    } else if (focusedId && !busy && !document.querySelector("dialog[open]"))
      focusCard(gridCard(focusedId));
  }

  $("cards").addEventListener("keydown", gridKey);
  $("cards").addEventListener("focusin", (event) => {
    lastFocused = event.target.closest(".card")?.dataset.copyId ?? lastFocused;
  });
  $("open-viewer").addEventListener("click", () => open(lastFocused));
  dialog().addEventListener("keydown", viewerKey);
  dialog().addEventListener("close", () => {
    const card = gridCard(viewer.id);
    if (card) setTimeout(() => focusCard(card));
  });
  $("viewer-flip").addEventListener("click", flip);
  for (const name of Object.keys(panels))
    $(panels[name]).addEventListener("click", () => toggle(name));
  // With a mouse, the strip shows while the pointer is near the bottom edge.
  dialog().addEventListener("pointermove", (event) => {
    if (event.pointerType !== "mouse") return;
    const near = event.clientY > window.innerHeight - 130;
    if (near !== dialog().classList.contains("strip-peek")) {
      dialog().classList.toggle("strip-peek", near);
      if (near) renderStrip(localIndex());
    }
  });
  $("viewer-previous").addEventListener("click", () => step(-1));
  $("viewer-next").addEventListener("click", () => step(1));
  // Horizontal swipe on the photo, for phones.
  let swipe = null;
  $("viewer-photo").addEventListener("pointerdown", (event) => {
    swipe = { x: event.clientX, y: event.clientY };
  });
  $("viewer-photo").addEventListener("pointerup", (event) => {
    if (!swipe) return;
    const dx = event.clientX - swipe.x,
      dy = event.clientY - swipe.y;
    swipe = null;
    if (Math.abs(dx) > 50 && Math.abs(dx) > 2 * Math.abs(dy)) step(dx < 0 ? 1 : -1);
  });

  return { rendered, open, neighbour, pageOffset };
})();
