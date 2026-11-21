"use strict";
const $ = (id) => document.getElementById(id);
const state = {
  user: null,
  setup: false,
  summary: null,
  offset: 0,
  limit: 40,
  selected: new Map(),
  lotMode: false,
  visibleCards: [],
  total: 0,
  detail: null,
  request: 0,
  view: "collection",
};
const money = (cents) =>
  cents === null || cents === undefined
    ? "Prix indisponible"
    : new Intl.NumberFormat("fr-FR", {
        style: "currency",
        currency: "EUR",
      }).format(cents / 100);
const intakeState = {
  token: null,
  existing: null,
  chosen: null,
  busy: false,
  saving: false,
  hasPhoto: false,
  generation: 0,
};
const photoState = {
  token: null,
  card: null,
  busy: false,
  saving: false,
  generation: 0,
  side: "front",
};
const stockLabels = {
  available: "Disponible",
  reserved: "Réservé",
  sold: "Vendu",
};
const statusLabels = {
  confirmed: "Identité confirmée",
  review: "À vérifier",
  unresolved: "À identifier",
  failed: "À identifier",
};
const saleLabels = {
  draft: "Brouillon",
  reserved: "Réservé",
  sold: "Vendu",
  shipped: "Expédié",
  completed: "Clôturé",
  cancelled: "Annulé",
  returned: "Retourné",
};
const editAllowed = () => state.user && state.user.role !== "reader";
function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
async function api(path, options = {}) {
  const response = await fetch("/api" + path, {
    credentials: "same-origin",
    ...options,
    headers: {
      ...(options.body && typeof options.body === "string"
        ? { "Content-Type": "application/json" }
        : {}),
      ...options.headers,
    },
  });
  const body = await response.text();
  let result;
  try {
    result = body.trim() ? JSON.parse(body) : null;
  } catch {
    if (response.ok)
      throw new Error(
        `Réponse illisible du serveur (HTTP ${response.status}). Actualisez la page puis réessayez.`,
      );
  }
  if (!response.ok) {
    let detail =
      result?.detail || `La demande n’a pas abouti (HTTP ${response.status}).`;
    if (Array.isArray(detail))
      detail = detail
        .map((x) => `${x.loc.slice(1).join(" ")} : ${x.msg}`)
        .join(" · ");
    if (response.status === 401 && path !== "/login" && path !== "/session")
      showAccess();
    // V1.1, contexte de la question (fiche 0036) : la dernière erreur, pour le chat.
    // Datée : le chat ne la joint que tant qu'elle est récente (assistant.js).
    if (typeof state !== "undefined")
      state.lastError = { text: String(detail || "Erreur de connexion."), at: Date.now() };
    throw new Error(detail || "Erreur de connexion.");
  }
  if (result === null)
    throw new Error(
      `Réponse vide du serveur (HTTP ${response.status}). Actualisez la page puis réessayez.`,
    );
  return result;
}
function toast(message) {
  $("toast").textContent = message;
  $("toast").hidden = false;
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => ($("toast").hidden = true), 5000);
}
function options(select, albums, current = "", all = false) {
  select.replaceChildren();
  if (all) select.append(new Option("Tous les albums", ""));
  for (const a of albums) select.append(new Option(a.name, a.id));
  select.value = current;
}
function showAccess() {
  if (typeof Workflows !== "undefined") Workflows.attach(null);
  if (typeof Assistant !== "undefined") Assistant.attach(null);
  state.user = null;
  state.selected.clear();
  state.lotMode = false;
  selectionBar();
  $("workspace").hidden = true;
  $("access").hidden = false;
  for (const d of document.querySelectorAll("dialog[open]")) d.close();
}
async function refreshSummary() {
  state.summary = await api("/summary");
  const s = state.summary;
  $("stats").replaceChildren();
  for (const [value, label] of [
    [s.copies, "exemplaires"],
    [s.editions, "éditions identifiées"],
    [s.available, "disponibles"],
    [s.confirmed_without_price, "identifiées sans prix"],
    ...(s.bulk ? [[s.bulk, "énergies de base en vrac"]] : []),
  ]) {
    const box = el("div", undefined, "stat");
    box.append(el("strong", value), el("span", label));
    $("stats").append(box);
  }
  renderValuationTotals($("collection-values"), s.valuation_totals);
  options($("album-filter"), s.albums, $("album-filter").value, true);
  // Keep the selection: during a series this locked field holds its album.
  options(
    $("add-form").elements.album_id,
    s.albums,
    $("add-form").elements.album_id.value,
  );
}
// An alert's link (/gestion?demande=…) opens that request, ready to answer.
// Read once, on opening the workspace and before syncLocation rewrites the
// address, not at load: the module must also run without a browser URL API.
let requestToFocus;
function focusedRequest() {
  if (requestToFocus === undefined) requestToFocus = new URLSearchParams(location.search).get("demande");
  return requestToFocus;
}
// A close-up series link (/gestion?prises=id,id,…, decision 0048) opens the
// series on those copies; read once, like the request link above.
let closeupsToOpen;
function closeupLink() {
  if (closeupsToOpen === undefined) {
    const ids = (new URLSearchParams(location.search).get("prises") || "")
      .split(",")
      .filter((id) => /^[0-9a-f-]{36}$/.test(id));
    closeupsToOpen = ids.length && ids.length <= 500 ? ids : null;
  }
  return closeupsToOpen;
}
async function showWorkspace(user) {
  state.user = user;
  $("access").hidden = true;
  $("workspace").hidden = false;
  $("account-label").textContent = user.username;
  $("settings-nav").hidden = user.role !== "admin";
  $("audience-nav").hidden = user.role !== "admin";
  $("backup-link").hidden = user.role !== "admin";
  $("add-card").hidden = !editAllowed();
  $("create-lot").hidden = !editAllowed();
  $("sales-create-lot").hidden = !editAllowed();
  $("trash-filter").hidden = user.role !== "admin";
  $("select-page").hidden = !editAllowed();
  const requestLink = focusedRequest();
  const closeupIds = closeupLink();
  await refreshSummary();
  refreshPhotoRequests().catch((e) => toast(e.message));
  refreshFloorRequests().catch((e) => toast(e.message));
  if (typeof refreshTodo === "function") refreshTodo().catch((e) => toast(e.message));
  if (typeof Assistant !== "undefined") Assistant.attach(user);
  if (typeof BinderImport !== "undefined") BinderImport.attach();
  if (typeof Closeups !== "undefined") {
    Closeups.attach();
    if (closeupIds && user.role === "admin")
      Closeups.open({ copy_ids: closeupIds }).catch((e) => toast(e.message));
  }
  restoreLocation();
  if (requestLink) changeView("sales", false);
  await loadCards();
  if (state.view === "sales") await loadSales();
  if (state.view === "settings") await loadUsers();
  if (state.view === "audience") await loadAudience();
  if (typeof Workflows !== "undefined") await Workflows.refresh();
}
function collectionQuery() {
  return new URLSearchParams({
    q: $("search").value,
    album: $("album-filter").value,
    stock: $("stock-filter").value,
    status: $("status-filter").value,
    variant: $("variant-filter").value,
    sort: $("sort-order").value,
    review: $("review-filter").value,
    threshold: reviewThreshold(),
    limit: state.limit,
    offset: state.offset,
  });
}
function reviewThreshold() {
  const value = Number($("review-threshold").value);
  return Number.isFinite(value) &&
    value >= 0.01 && value <= 10000 &&
    Math.abs(value * 100 - Math.round(value * 100)) < 0.000001
    ? value : 10;
}
function renderValuationTotals(target, values) {
  target.replaceChildren();
  // Each total has its own source: "missing" names what each copy lacks.
  for (const key of ["trend", "prudent", "sale_estimate"]) {
    const box = el("div", undefined, "valuation-total");
    box.title = t(`valuation.${key}.help`);
    const parts = [
      t("valuation.coverage", { known: values[key + "_known"], count: values.copies }),
      t(`valuation.${key}.missing`, { count: values[key + "_missing"] }),
    ];
    if (values.bulk_copies) parts.push(t("valuation.bulk", { count: values.bulk_copies }));
    box.append(
      el("span", t(`valuation.${key}`)),
      el("strong", money(values[key + "_cents"])),
      el("small", parts.join(" · ")),
    );
    target.append(box);
  }
}
function syncLocation(mode = "replace") {
  const query = collectionQuery();
  for (const key of ["q", "album", "stock", "status", "variant", "review"])
    if (!query.get(key)) query.delete(key);
  if (query.get("sort") === "name") query.delete("sort");
  if (query.get("threshold") === "10") query.delete("threshold");
  if (state.offset === 0) query.delete("offset");
  if (state.limit === 40) query.delete("limit");
  if (state.view !== "collection") query.set("view", state.view);
  if ($("display-mode")?.value === "editions") query.set("display", "editions");
  const url = "/gestion" + (query.size ? "?" + query.toString() : "");
  if (location.pathname + location.search !== url)
    history[mode === "push" ? "pushState" : "replaceState"]({}, "", url);
}
function restoreLocation() {
  const query = new URLSearchParams(location.search);
  if ($("display-mode"))
    $("display-mode").value =
      query.get("display") === "editions" ? "editions" : "copies";
  $("search").value = (query.get("q") || "").slice(0, 300);
  for (const [key, id] of [
    ["album", "album-filter"],
    ["stock", "stock-filter"],
    ["status", "status-filter"],
    ["variant", "variant-filter"],
    ["sort", "sort-order"],
    ["review", "review-filter"],
  ]) {
    const select = $(id),
      fallback = key === "sort" ? "name" : "",
      value = query.get(key) || fallback;
    select.value = Array.from(select.options).some((o) => o.value === value)
      ? value
      : fallback;
  }
  const threshold = query.get("threshold") || "10";
  $("review-threshold").value = /^\d+(?:\.\d{1,2})?$/.test(threshold) &&
    Number(threshold) >= 0.01 && Number(threshold) <= 10000 ? threshold : "10";
  const number = (key, fallback, max) =>
    /^\d+$/.test(query.get(key) || "")
      ? Math.min(max, Number(query.get(key)))
      : fallback;
  state.limit = Math.max(1, number("limit", 40, 200));
  state.offset = number("offset", 0, Number.MAX_SAFE_INTEGER);
  const view = query.get("view");
  if ($("stock-filter").value === "deleted" && state.user?.role !== "admin")
    $("stock-filter").value = "";
  changeView(
    view === "sales" ||
      (["settings", "audience"].includes(view) && state.user?.role === "admin")
      ? view
      : "collection",
    false,
  );
}
async function loadCards() {
  const generation = ++state.request;
  syncLocation();
  const query = collectionQuery();
  const grouped = $("display-mode")?.value === "editions";
  $("cards").setAttribute("aria-busy", "true");
  let data;
  try {
    data = await api((grouped ? "/editions?" : "/copies?") + query);
  } finally {
    if (generation === state.request) $("cards").removeAttribute("aria-busy");
  }
  if (generation !== state.request) return;
  state.total = data.total;
  state.visibleCards = grouped
    ? data.items.flatMap((g) => g.copies)
    : data.items;
  $("result-count").textContent =
    `${grouped ? data.copies_total : data.total} exemplaire(s) · ${data.editions} édition(s) identifiée(s) · ${data.available} disponible(s)`;
  $("result-value").textContent =
    `${data.valuation_totals.review_count} à examiner · seuil ${money(Math.round(reviewThreshold() * 100))}`;
  renderValuationTotals($("result-values"), data.valuation_totals);
  // A re-render keeps keyboard focus on the same copy when it is still shown.
  const focused = document.activeElement?.closest?.("#cards .card")?.dataset
    .copyId;
  $("cards").replaceChildren();
  $("cards").classList.toggle("edition-list", grouped);
  for (const entry of data.items) {
    let container = $("cards");
    if (grouped) {
      const group = el("details", undefined, "edition-group");
      const counts = entry.stock_counts;
      group.append(
        el(
          "summary",
          `${entry.name} · ${entry.set_name || "Extension à vérifier"} · ${entry.number} · ${entry.language.toUpperCase()} — ${entry.quantity} exemplaire(s) affiché(s) ; ${counts.available} disponible(s), ${counts.reserved} réservé(s), ${counts.sold} vendu(s)`,
        ),
      );
      if (entry.global_quantity !== entry.quantity)
        group.append(
          el(
            "p",
            `${entry.global_quantity} exemplaire(s) au total dans la collection`,
            "help",
          ),
        );
      container = el("div", undefined, "card-grid");
      group.append(container);
      $("cards").append(group);
    }
    for (const card of grouped ? entry.copies : [entry]) {
      const box = el("article", undefined, "card");
      box.dataset.copyId = card.id;
      box.classList.toggle("selected", state.selected.has(card.id));
      if (
        editAllowed() &&
        !card.deleted_at &&
        (!state.lotMode || card.stock_state === "available")
      ) {
        const label = el("label", undefined, "card-select");
        const check = el("input");
        check.type = "checkbox";
        check.checked = state.selected.has(card.id);
        check.setAttribute(
          "aria-label",
          `Sélectionner ${card.name}, ${card.album}, page ${card.page}, pochette ${card.position}`,
        );
        check.addEventListener("change", () => {
          selectCopy(card, check.checked);
        });
        label.append(check);
        box.append(label);
      }
      box.append(
        el("span", (card.language || "?").toUpperCase(), "card-language"),
      );
      const button = el("button", undefined, "card-open");
      button.type = "button";
      button.setAttribute(
        "aria-label",
        `Ouvrir ${card.name}, ${card.number}, page ${card.page}, pochette ${card.position}`,
      );
      const image = el("div", undefined, "card-image");
      if (card.photo) {
        const img = el("img");
        img.src = `/api/copies/${card.id}/photo?size=thumb&v=${card.version}`;
        img.dataset.full = `/api/copies/${card.id}/photo?v=${card.version}`;
        img.alt = card.name;
        img.loading = "lazy";
        img.decoding = "async";
        image.append(img);
      } else image.append(el("span", "Photo à ajouter", "no-photo"));
      const info = el("div", undefined, "card-info");
      info.append(
        el(
          "span",
          statusLabels[card.identification_status],
          "badge" +
            (card.identification_status === "confirmed" ? "" : " review"),
        ),
        el("h3", card.name),
        el(
          "p",
          `${card.set_name || "Extension à préciser"} · ${card.number || "Référence à préciser"}`,
          "card-set",
        ),
      );
      const bottom = el("div", undefined, "card-bottom");
      bottom.append(
        el("span", `P.${card.page} · #${card.position} · ${card.album}`),
        el(
          "span",
          `${card.condition || "État inconnu"}${card.foil ? " · Foil" : ""}${card.stamp ? " · Tampon" : ""}`,
        ),
      );
      if (card.variant_confirmed)
        bottom.append(el("span", "Variante vérifiée", "badge"));
      if (card.valuation?.is_valuable)
        bottom.append(el("span", "Carte de valeur", "badge"));
      if (card.price_alerts || card.variant_check || (card.variant_catalog_warning && card.variant_confirmed))
        bottom.append(
          el(
            "span",
            card.variant_check ? "⚠ Variante à vérifier" : card.variant_catalog_warning && card.variant_confirmed ? "Variante confirmée · catalogue discordant" : `${card.price_alerts} signal(aux) de prix`,
            "card-alert",
          ),
        );
      info.append(bottom);
      const price = el("div", undefined, "card-price");
      if (card.valuation?.needs_review) {
        const badge = el("span", "À examiner", "badge review");
        badge.title = card.valuation.reasons.map((r) => r.label).join(" · ");
        bottom.append(badge);
        info.append(el("p", badge.title, "review-reasons"));
      }
      price.append(
        el(
          "span",
          `Prudente : ${money(card.valuation?.prudent_cents)}`,
          card.valuation?.prudent_cents == null ? "unknown-price" : "",
        ),
      );
      price.append(
        document.createTextNode(" "),
        el(
          "span",
          card.deleted_at ? "Corbeille" : stockLabels[card.stock_state],
          "badge " + card.stock_state,
        ),
      );
      info.append(price);
      if (card.valuation?.needs_review)
        info.append(el("p", `Valeur en jeu : ${money(card.valuation.risk_cents)}${card.valuation.risk_incomplete ? " · incomplète" : ""}`, "risk-value"));
      if (card.photo) {
        const zoom = CardMedia.zoomButton(image.firstElementChild);
        zoom.classList.add("card-image");
        box.append(zoom);
      } else button.append(image);
      button.append(info);
      button.addEventListener("click", () =>
        openDetail(card.id).catch((e) => toast(e.message)),
      );
      box.append(button);
      container.append(box);
    }
  }
  if (!data.items.length)
    $("cards").append(
      el("p", "Aucun exemplaire ne correspond à cette recherche.", "empty"),
    );
  $("previous").disabled = state.offset === 0;
  $("next").disabled = state.offset + state.limit >= data.total;
  const pages = Math.max(1, Math.ceil(data.total / state.limit));
  $("page-number").max = String(pages);
  $("page-number").value = String(Math.floor(state.offset / state.limit) + 1);
  $("page-count").textContent = `sur ${pages}`;
  $("page-label").textContent = data.total
    ? `Cartes ${state.offset + 1}–${Math.min(state.offset + state.limit, data.total)} sur ${data.total}`
    : "0 résultat";
  document.querySelector(".pagination").hidden = false;
  selectionBar();
  for (const bar of document.querySelectorAll("lilydex-filter-bar"))
    bar.refreshChips?.();
  if (typeof Workflows !== "undefined") Workflows.selection();
  if (typeof Gallery !== "undefined") Gallery.rendered(focused);
}
function selectionBar() {
  if (typeof Workflows !== "undefined") Workflows.selection();
  const active = editAllowed() && (state.lotMode || state.selected.size);
  $("selection-bar").hidden = !active;
  $("lot-builder").hidden = !state.lotMode || !editAllowed();
  const saleReady =
    state.selected.size > 0 &&
    [...state.selected.values()].every(
      (c) => c.stock_state === "available" && !c.deleted_at,
    );
  const publishableCopies = [...state.selected.values()].filter(
    (c) => c.stock_state === "available" && !c.deleted_at,
  );
  $("prepare-sale").disabled = !saleReady;
  if ($("move-selection")) $("move-selection").disabled = !saleReady;
  if ($("move-preview-button"))
    $("move-preview-button").disabled = !state.selected.size;
  $("publish-selection").disabled = !publishableCopies.length;
  $("publish-lot").disabled = !saleReady || state.selected.size < 2;
  $("finish-lot").disabled = !saleReady;

  $("change-variant").disabled = !state.selected.size || state.priceRun;
  if (!state.priceRun) {
    const priceable = [...state.selected.values()].filter(canRefreshPrice);
    $("refresh-prices").disabled = !priceable.length;
    $("refresh-prices").textContent = `Relever les prix (${priceable.length})`;
  }
  $("select-visible").disabled = !state.visibleCards.some(
    (c) =>
      c.stock_state === "available" &&
      !c.deleted_at &&
      !state.selected.has(c.id),
  );
  $("selection-count").textContent =
    `${state.selected.size} exemplaire${state.selected.size > 1 ? "s" : ""} sélectionné${state.selected.size > 1 ? "s" : ""}`;
  const floor = selectionFloor();
  $("lot-summary").textContent = state.selected.size
    ? `${$("selection-count").textContent} · ${selectionFloorLabel(floor)} · Vous pouvez retirer chaque exemplaire ci-dessous.`
    : "Aucune carte choisie. Cochez les cases en haut à gauche des photos.";
  $("lot-selected").replaceChildren();
  for (const card of state.selected.values()) {
    const button = el("button", cardLocation(card) + " ×", "lot-chip");
    button.type = "button";
    button.setAttribute("aria-label", "Retirer du lot " + cardLocation(card));
    button.addEventListener("click", () => selectCopy(card, false));
    $("lot-selected").append(button);
  }
  for (const box of document.querySelectorAll(".card[data-copy-id]")) {
    const selected = state.selected.has(box.dataset.copyId);
    box.classList.toggle("selected", selected);
    const check = box.querySelector(".card-select input");
    if (check) check.checked = selected;
  }
}
function formatEuros(cents) {
  if (typeof money === "function") return money(cents);
  return `${(cents / 100).toFixed(2).replace(".", ",")} €`;
}
// Same rule as listings.reference_cents (decision 0026).
function cardReferenceCents(card) {
  if (!card) return 0;
  const positive = (v) =>
    typeof v === "number" && Number.isFinite(v) && v > 0 ? Math.round(v) : 0;
  if (card.valuation?.price_variant_issue) {
    // A variant to check: the lowest quote among the possible variants.
    const quotes = [
      positive(card.reference_cents),
      ...(card.valuation.hypotheses || []).map((h) => positive(h.trend_cents)),
    ].filter(Boolean);
    return quotes.length ? Math.min(...quotes) : 0;
  }
  for (const v of [
    card.reference_cents,
    card.valuation?.trend_cents,
    card.valuation?.prudent_cents,
  ]) {
    if (typeof v === "number" && Number.isFinite(v) && v > 0)
      return Math.round(v);
  }
  return 0;
}
function selectionFloor(cards = [...state.selected.values()]) {
  const rawMargin = state.summary?.lot_max_margin;
  const margin =
    typeof rawMargin === "number" && Number.isFinite(rawMargin)
      ? Math.max(0, Math.min(50, Math.trunc(rawMargin)))
      : 15;
  let referenceCents = 0;
  let unpricedCount = 0;
  for (const card of cards) {
    const ref = cardReferenceCents(card);
    if (ref > 0) referenceCents += ref;
    else unpricedCount += 1;
  }
  const refFloor = Math.ceil((referenceCents * (100 - margin)) / 100);
  const floorCents = Math.max(50, refFloor);
  return {
    margin,
    referenceCents,
    unpricedCount,
    floorCents,
    count: cards.length,
  };
}
function selectionFloorLabel(floor = selectionFloor()) {
  const vars = {
    floor: formatEuros(floor.floorCents),
    reference: formatEuros(floor.referenceCents),
    margin: floor.margin,
    unpriced: floor.unpricedCount,
  };
  if (!floor.referenceCents) {
    const fallback = `Plancher autorisé : ${vars.floor} (aucune valeur de référence ; minimum ${vars.floor})`;
    return typeof t === "function"
      ? t("lot.floor.unrated", vars, fallback)
      : fallback;
  }
  if (floor.unpricedCount > 0) {
    const fallback = `Plancher autorisé : ${vars.floor} (référence ${vars.reference} sur les cartes cotées, marge max ${vars.margin} % ; ${vars.unpriced} sans référence)`;
    return typeof t === "function"
      ? t("lot.floor.partial", vars, fallback)
      : fallback;
  }
  const fallback = `Plancher autorisé : ${vars.floor} (référence ${vars.reference}, marge max ${vars.margin} %)`;
  return typeof t === "function"
    ? t("lot.floor.reference", vars, fallback)
    : fallback;
}
function selectionFloorRefusal(priceCents, floor = selectionFloor()) {
  const vars = {
    price: formatEuros(priceCents),
    floor: formatEuros(floor.floorCents),
    reference: formatEuros(floor.referenceCents),
    margin: floor.margin,
  };
  if (!floor.referenceCents) {
    const fallback = `Prix refusé (${vars.price}) : aucune valeur de référence, le minimum autorisé est ${vars.floor}.`;
    return typeof t === "function"
      ? t("lot.floor.refused_unrated", vars, fallback)
      : fallback;
  }
  const fallback = `Prix refusé (${vars.price}) : le minimum autorisé est ${vars.floor} (référence ${vars.reference}, marge max ${vars.margin} %).`;
  return typeof t === "function"
    ? t("lot.floor.refused", vars, fallback)
    : fallback;
}
function canRefreshPrice(card) {
  return (
    !card.deleted_at &&
    card.identification_status === "confirmed" &&
    Boolean(card.catalog_id)
  );
}
// One request per card: a failure (tunnel, TCGdex, changed card) never stops
// the others, and each card keeps its own audited correction.
async function runPriceRefresh(cards, refresh, progress = () => {}) {
  const result = { updated: [], skipped: 0, failed: [], warned: 0 };
  const priceable = cards.filter(canRefreshPrice);
  result.skipped = cards.length - priceable.length;
  for (const [index, card] of priceable.entries()) {
    progress(index + 1, priceable.length);
    try {
      const updated = await refresh(card);
      result.updated.push(updated);
      if (updated.price_snapshot?.warnings?.length) result.warned++;
    } catch (error) {
      result.failed.push({ card, message: error.message });
    }
  }
  return result;
}
// Variant correction for a selection: an audited patch per card, then a new
// price snapshot, since a variant change clears the reference price.
async function runVariantChange(cards, foil, patch, refresh, progress = () => {}) {
  const result = { updated: [], unchanged: 0, failed: [], unpriced: [] };
  const changing = cards.filter((card) => Boolean(card.foil) !== foil);
  result.unchanged = cards.length - changing.length;
  for (const [index, card] of changing.entries()) {
    progress(index + 1, changing.length);
    let patched;
    try {
      patched = await patch(card);
    } catch (error) {
      result.failed.push({ card, message: error.message });
      continue;
    }
    try {
      result.updated.push(
        canRefreshPrice(patched) ? await refresh(patched) : patched,
      );
    } catch (error) {
      result.updated.push(patched);
      result.unpriced.push({ card: patched, message: error.message });
    }
  }
  return result;
}
function cardLocation(card) {
  return `${card.name} · ${card.number || "Référence à préciser"} · ${card.album} · P.${card.page} #${card.position}`;
}
function selectCopy(card, selected) {
  if (
    !editAllowed() ||
    (selected &&
      (card.deleted_at || (state.lotMode && card.stock_state !== "available")))
  )
    return;
  selected ? state.selected.set(card.id, card) : state.selected.delete(card.id);
  selectionBar();
}
function changeView(view, remember = true) {
  state.view = view;
  for (const button of document.querySelectorAll("[data-view]"))
    button.classList.toggle("active", button.dataset.view === view);
  for (const name of ["collection", "sales", "settings", "audience"])
    $(name + "-view").hidden = name !== view;
  if (typeof assistantShown === "function" && $("assistant"))
    $("assistant").hidden = !assistantShown();
  if (remember) syncLocation("push");
}
async function startLot() {
  if (!editAllowed()) return;
  state.lotMode = true;
  for (const [id, card] of state.selected)
    if (card.stock_state !== "available" || card.deleted_at)
      state.selected.delete(id);
  state.offset = 0;
  $("stock-filter").value = "available";
  changeView("collection");
  selectionBar();
  await loadCards();
  $("lot-builder").scrollIntoView({ behavior: "smooth", block: "start" });
}
function prepareLot() {
  if (!editAllowed() || !state.selected.size) return;
  const floor = selectionFloor();
  const minEur = (floor.floorCents / 100).toFixed(2);
  const form = $("sale-form");
  if (form?.elements) {
    for (const name of ["amount_eur", "asking_eur", "target_eur", "minimum_eur"]) {
      if (form.elements[name]) form.elements[name].min = minEur;
    }
  }
  $("sale-selection").replaceChildren(
    el("strong", $("selection-count").textContent),
    el("p", selectionFloorLabel(floor), "help"),
    ...[...state.selected.values()].map((c) => el("p", cardLocation(c))),
  );
  $("sale-error").textContent = "";
  $("sale-dialog").showModal();
}
function field(form, name, label, value, type = "text", choices = null) {
  const wrapper = el("label", label);
  let input;
  if (choices) {
    input = el("select");
    for (const [v, l] of choices) input.append(new Option(l, v));
    input.value = value ?? "";
  } else {
    input = el(type === "textarea" ? "textarea" : "input");
    if (type !== "textarea") input.type = type;
    input.value = value ?? "";
  }
  input.name = name;
  if (!editAllowed()) input.disabled = true;
  wrapper.append(input);
  form.append(wrapper);
  return input;
}
function pair(form) {
  const row = el("div", undefined, "form-row");
  form.append(row);
  return row;
}
