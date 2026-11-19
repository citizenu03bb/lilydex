"use strict";
for (const button of document.querySelectorAll("[data-close]"))
  button.addEventListener("click", () => $(button.dataset.close).close());
for (const button of document.querySelectorAll("[data-view]"))
  button.addEventListener("click", async () => {
    changeView(button.dataset.view);
    try {
      if (button.dataset.view === "sales") await loadSales();
      if (button.dataset.view === "settings") await loadUsers();
      if (button.dataset.view === "audience") await loadAudience();
    } catch (e) {
      toast(e.message);
    }
  });
$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("login-error").textContent = "";
  const data = Object.fromEntries(new FormData(e.target));
  try {
    const user = await api(state.setup ? "/setup" : "/login", {
      method: "POST",
      body: JSON.stringify(data),
    });
    state.setup = false;
    state.lastError = null; // V1.1 : l'erreur d'avant la connexion ne concerne plus rien.
    e.target.reset();
    await showWorkspace(user);
  } catch (err) {
    $("login-error").textContent = err.message;
  }
});
$("logout").addEventListener("click", async () => {
  try {
    if (typeof Workflows !== "undefined") await Workflows.persist();
    await api("/logout", { method: "POST" });
    showAccess();
  } catch (e) {
    toast(e.message);
  }
});
let searchTimer;
window.addEventListener("popstate", async () => {
  clearTimeout(searchTimer);
  ++state.request;
  if (!state.user) return;
  restoreLocation();
  try {
    await loadCards();
    if (state.view === "sales") await loadSales();
    if (state.view === "settings") await loadUsers();
    if (state.view === "audience") await loadAudience();
  } catch (error) {
    toast(error.message);
  }
});
$("search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.offset = 0;
    loadCards().catch((e) => toast(e.message));
  }, 200);
});
for (const id of [
  "album-filter",
  "stock-filter",
  "status-filter",
  "variant-filter",
  "sort-order",
  "review-filter",
  "review-threshold",
])
  $(id).addEventListener("change", () => {
    if (id === "review-threshold") $(id).value = String(reviewThreshold());
    state.offset = 0;
    syncLocation("push");
    loadCards().catch((e) => toast(e.message));
  });
$("sales-filter")?.addEventListener("change", () => {
  loadSales().catch((e) => toast(e.message));
});
$("previous").addEventListener("click", () => {
  state.offset = Math.max(0, state.offset - state.limit);
  syncLocation("push");
  loadCards().catch((e) => toast(e.message));
});
$("next").addEventListener("click", () => {
  state.offset += state.limit;
  syncLocation("push");
  loadCards().catch((e) => toast(e.message));
});
// 44 pages are too many to walk: a page number goes straight there.
$("page-number").addEventListener("change", () => {
  const pages = Math.max(1, Math.ceil(state.total / state.limit));
  const page = Math.min(pages, Math.max(1, Math.round(Number($("page-number").value)) || 1));
  state.offset = (page - 1) * state.limit;
  syncLocation("push");
  loadCards().catch((e) => toast(e.message));
});
$("select-page").addEventListener("click", () => {
  if (!editAllowed()) return;
  for (const card of state.visibleCards)
    if (!card.deleted_at && (!state.lotMode || card.stock_state === "available"))
      state.selected.set(card.id, card);
  selectionBar();
});
$("change-variant").addEventListener("click", () => {
  if (!state.selected.size || state.priceRun) return;
  $("variant-error").textContent = "";
  for (const radio of $("variant-form").elements.foil) radio.checked = false;
  $("variant-summary").textContent =
    `${$("selection-count").textContent}. Les cartes déjà dans la variante choisie restent inchangées.`;
  $("variant-dialog").showModal();
});
$("variant-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.priceRun) return;
  const form = event.target,
    submit = form.querySelector("[type=submit]");
  const foil = form.elements.foil.value === "true",
    reason = form.elements.reason.value.trim();
  state.priceRun = true;
  submit.disabled = true;
  try {
    const result = await runVariantChange(
      [...state.selected.values()],
      foil,
      (card) =>
        api(`/copies/${card.id}`, {
          method: "PATCH",
          body: JSON.stringify({ expected_version: card.version, reason, foil }),
        }),
      (card) =>
        api(`/copies/${card.id}/price-refresh`, {
          method: "POST",
          body: JSON.stringify({ expected_version: card.version }),
        }),
      (done, total) => (submit.textContent = `Correction ${done}/${total}…`),
    );
    for (const card of result.updated)
      if (state.selected.has(card.id)) {
        const { price_snapshot, ...fields } = card;
        state.selected.set(card.id, { ...state.selected.get(card.id), ...fields });
      }
    const parts = [
      `${result.updated.length} carte(s) passée(s) en ${foil ? "Foil" : "Standard"}`,
    ];
    if (result.unchanged) parts.push(`${result.unchanged} déjà dans cette variante`);
    if (result.unpriced.length)
      parts.push(`${result.unpriced.length} sans nouveau prix (relevé à refaire)`);
    if (result.failed.length)
      parts.push(
        `${result.failed.length} échec(s) : ${result.failed
          .slice(0, 3)
          .map((f) => `${f.card.name} (${f.message})`)
          .join(" ; ")}`,
      );
    if (!result.failed.length) $("variant-dialog").close();
    else $("variant-error").textContent = parts.at(-1);
    toast(parts.join(" · ") + ".");
    await refreshSummary();
    await loadCards();
  } finally {
    state.priceRun = false;
    submit.disabled = false;
    submit.textContent = "Appliquer à la sélection";
    selectionBar();
  }
});
$("refresh-prices").addEventListener("click", async () => {
  if (state.priceRun || !editAllowed()) return;
  state.priceRun = true;
  const button = $("refresh-prices");
  button.disabled = true;
  try {
    const result = await runPriceRefresh(
      [...state.selected.values()],
      (card) =>
        api(`/copies/${card.id}/price-refresh`, {
          method: "POST",
          body: JSON.stringify({ expected_version: card.version }),
        }),
      (done, total) => (button.textContent = `Relevé ${done}/${total}…`),
    );
    // Keep the selection usable: later actions need the new versions.
    for (const card of result.updated)
      if (state.selected.has(card.id)) {
        const { price_snapshot, ...fields } = card;
        state.selected.set(card.id, { ...state.selected.get(card.id), ...fields });
      }
    const parts = [`${result.updated.length} prix relevé(s)`];
    if (result.warned) parts.push(`${result.warned} avec alertes à vérifier`);
    if (result.skipped)
      parts.push(`${result.skipped} ignorée(s) : édition non confirmée`);
    if (result.failed.length)
      parts.push(
        `${result.failed.length} échec(s) : ${result.failed
          .slice(0, 3)
          .map((f) => `${f.card.name} (${f.message})`)
          .join(" ; ")}`,
      );
    toast(parts.join(" · ") + ". Ouvrez une fiche pour voir les alertes.");
    await refreshSummary();
    await loadCards();
  } finally {
    state.priceRun = false;
    selectionBar();
  }
});
$("clear-selection").addEventListener("click", () => {
  state.selected.clear();
  selectionBar();
});
for (const id of ["create-lot", "sales-create-lot"])
  $(id).addEventListener("click", () =>
    startLot().catch((e) => toast(e.message)),
  );
$("select-visible").addEventListener("click", () => {
  if (!editAllowed()) return;
  for (const card of state.visibleCards)
    if (card.stock_state === "available" && !card.deleted_at)
      state.selected.set(card.id, card);
  selectionBar();
});
$("cancel-lot").addEventListener("click", () => {
  state.selected.clear();
  state.lotMode = false;
  selectionBar();
});
$("prepare-sale").addEventListener("click", prepareLot);
$("publish-selection").addEventListener("click", async () => {
  const button = $("publish-selection");
  const availableIds = [...state.selected.values()]
    .filter((c) => c.stock_state === "available" && !c.deleted_at)
    .map((c) => c.id);
  if (!availableIds.length) return;
  button.disabled = true;
  try {
    const result = await api("/listings", {
      method: "POST",
      body: JSON.stringify({ copy_ids: availableIds }),
    });
    const parts = [`${result.published.length} publiée(s) en vitrine`];
    if (result.refused.length)
      parts.push(`${result.refused.length} refusée(s) : ${result.refused[0].reason}`);
    toast(parts.join(" · "));
    await loadCards();
  } catch (e) {
    toast(e.message);
  } finally {
    selectionBar();
  }
});

$("publish-lot").addEventListener("click", async () => {
  const floor = selectionFloor();
  const promptVars = {
    count: state.selected.size,
    floor: formatEuros(floor.floorCents),
  };
  const promptFallback = `Prix du lot de ${promptVars.count} cartes, en euros (minimum autorisé : ${promptVars.floor}) :`;
  const price = prompt(
    typeof t === "function"
      ? t("lot.floor.prompt", promptVars, promptFallback)
      : promptFallback,
  );
  if (!price) return;
  const normalized = price.trim().replace(",", ".");
  const priceCents = Math.round(Number(normalized) * 100);
  if (!Number.isFinite(priceCents) || priceCents < floor.floorCents) {
    toast(
      selectionFloorRefusal(
        Number.isFinite(priceCents) ? priceCents : 0,
        floor,
      ),
    );
    return;
  }
  try {
    await api("/listings", {
      method: "POST",
      body: JSON.stringify({
        copy_ids: [...state.selected.keys()],
        lot: true,
        price_eur: normalized,
      }),
    });
    toast(`Lot de ${state.selected.size} cartes publié en vitrine.`);
    await loadCards();
  } catch (e) {
    toast(e.message);
  }
});
$("finish-lot").addEventListener("click", prepareLot);
$("sale-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(e.target));
  data.amount_eur = Number(data.amount_eur);
  for (const key of ["asking_eur", "target_eur", "minimum_eur"])
    data[key] = data[key] === "" ? null : Number(data[key]);
  data.copy_ids = [...state.selected.keys()];
  if (!editAllowed() || !data.copy_ids.length) {
    $("sale-error").textContent =
      "Choisissez au moins un exemplaire disponible.";
    return;
  }
  const floor = selectionFloor();
  for (const key of ["amount_eur", "asking_eur", "target_eur", "minimum_eur"]) {
    if (data[key] === null) continue;
    const fieldCents = Math.round(Number(data[key]) * 100);
    if (!Number.isFinite(fieldCents) || fieldCents < floor.floorCents) {
      $("sale-error").textContent = selectionFloorRefusal(
        Number.isFinite(fieldCents) ? fieldCents : 0,
        floor,
      );
      return;
    }
  }
  if ($("save-lot").disabled) return;
  $("save-lot").disabled = true;
  try {
    await api("/sales", { method: "POST", body: JSON.stringify(data) });
    $("sale-dialog").close();
    e.target.reset();
    state.selected.clear();
    state.lotMode = false;
    if (
      $("sales-filter") &&
      !matchesSalesFilter({ status: "draft" }, $("sales-filter").value)
    )
      $("sales-filter").value = "active";
    await loadCards();
    await loadSales();
    changeView("sales");
    $("sales-view").scrollIntoView({ behavior: "smooth", block: "start" });
    toast(
      "Lot enregistré en brouillon. Les cartes restent disponibles jusqu’à réservation.",
    );
  } catch (err) {
    $("sale-error").textContent = err.message;
  } finally {
    $("save-lot").disabled = false;
  }
});
