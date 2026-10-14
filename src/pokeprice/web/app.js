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
async function showWorkspace(user) {
  state.user = user;
  $("access").hidden = true;
  $("workspace").hidden = false;
  $("account-label").textContent = user.username;
  $("settings-nav").hidden = user.role !== "admin";
  $("backup-link").hidden = user.role !== "admin";
  $("add-card").hidden = !editAllowed();
  $("create-lot").hidden = !editAllowed();
  $("sales-create-lot").hidden = !editAllowed();
  $("trash-filter").hidden = user.role !== "admin";
  $("select-page").hidden = !editAllowed();
  await refreshSummary();
  restoreLocation();
  await loadCards();
  if (state.view === "sales") await loadSales();
  if (state.view === "settings") await loadUsers();
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
  for (const [key, label, description] of [
    ["trend", "Tendance", "Tendance TCGdex de la variante enregistrée."],
    ["prudent", "Valeur prudente", "Minimum entre tendance et moyenne à 30 jours. Les deux prix sont nécessaires ; aucune décote d’état."],
    ["sale_estimate", "Estimation de vente", "Dernières offres collées pour l’identité, la variante et l’état actuels. Prix demandés, hors frais et port."],
  ]) {
    const box = el("div", undefined, "valuation-total");
    box.title = description;
    box.append(
      el("span", label),
      el("strong", money(values[key + "_cents"])),
      el("small", `${values[key + "_known"]}/${values.copies} exemplaires · ${values[key + "_missing"]} sans prix`),
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
  const url = "/" + (query.size ? "?" + query.toString() : "");
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
    view === "sales" || (view === "settings" && state.user?.role === "admin")
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
  const data = await api((grouped ? "/editions?" : "/copies?") + query);
  if (generation !== state.request) return;
  state.visibleCards = grouped
    ? data.items.flatMap((g) => g.copies)
    : data.items;
  $("result-count").textContent =
    `${grouped ? data.copies_total : data.total} exemplaire(s) · ${data.editions} édition(s) identifiée(s) · ${data.available} disponible(s)`;
  $("result-value").textContent =
    `${data.valuation_totals.review_count} à examiner · seuil ${money(Math.round(reviewThreshold() * 100))}`;
  renderValuationTotals($("result-values"), data.valuation_totals);
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
        img.src = `/api/copies/${card.id}/photo?v=${card.version}`;
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
  $("page-label").textContent = data.total
    ? `${state.offset + 1}–${Math.min(state.offset + state.limit, data.total)} sur ${data.total}`
    : "0 résultat";
  selectionBar();
  if (typeof Workflows !== "undefined") Workflows.selection();
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
  $("prepare-sale").disabled = !saleReady;
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
  $("lot-summary").textContent = state.selected.size
    ? $("selection-count").textContent +
      " · Vous pouvez retirer chaque exemplaire ci-dessous."
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
  for (const name of ["collection", "sales", "settings"])
    $(name + "-view").hidden = name !== view;
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
  $("sale-selection").replaceChildren(
    el("strong", $("selection-count").textContent),
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
// "Rare" and "Rare Holo" share the star symbol: tell what the standard print is.
function standardVariantHint(snapshot) {
  const variants = snapshot?.variants;
  if (!variants || !Object.keys(variants).length)
    return "Relevez le prix pour savoir, selon TCGdex, si la version standard de cette carte est holo ou mate.";
  const standard =
    variants.holo && !variants.normal
      ? "holo d’origine (illustration et parfois cadre brillants)"
      : variants.normal
        ? "mate"
        : "inconnue";
  const reverse = variants.reverse ? " Une reverse existe." : "";
  return `Selon TCGdex : ${snapshot.rarity || "rareté inconnue"}, version standard ${standard}.${reverse} Standard comprend les Rare Holo, Prime et LV.X d’origine. Foil correspond à une reverse ou une holo spéciale d’une édition normalement mate. Le catalogue peut être incomplet : la confirmation physique reste prioritaire.`;
}
function renderPriceSnapshot(parent, card) {
  const section = el("section", undefined, "price-panel");
  section.setAttribute("aria-label", "Relevé de prix");
  if (card.reference_cents != null && card.price_source && card.price_date && !card.valuation?.price_variant_issue)
    section.append(el("p", `Référence enregistrée : ${money(card.reference_cents)} · ${card.price_source} · ${card.price_date.slice(0, 10)}`));
  if (card.valuation) {
    const value = card.valuation;
    section.append(el("p", `Tendance : ${money(value.trend_cents)} · Prudente : ${money(value.prudent_cents)} · Estimation de vente : ${money(value.sale_estimate_cents)}`));
    section.append(el("p", `Valeur en jeu : ${money(value.risk_cents)}${value.risk_incomplete ? " · prix incomplets" : ""} · seuil ${money(value.threshold_cents)}. Maximum prudent des variantes et éditions plausibles, sans décote d’état.`, "help"));
    if (value.manual_price)
      section.append(el("p", `Valeur manuelle : TCGdex ne fournit pas de prix prudent, la référence saisie (${money(value.manual_price.amount_cents)}, ${value.manual_price.source}) en tient lieu. Sans moyenne à 30 jours, elle reste marquée incomplète.`, "help"));
    if (card.variant_confirmed && value.variant_catalog_warning)
      section.append(el("p", "Variante confirmée physiquement ; TCGdex ne répertorie pas cette variante. La confirmation humaine est conservée.", "help"));
    if (value.market_unstable)
      section.append(el("p", "Marché instable : les moyennes divergent. Ce signal de prix ne remet pas en cause l’examen physique.", "help"));
    if (value.needs_review) {
      const reasons = el("ul", undefined, "price-warnings");
      for (const reason of value.reasons) reasons.append(el("li", reason.label));
      section.append(reasons);
    }
  }
  const snapshot = card.price_snapshot;
  const euros = (v) => (v === null || v === undefined ? "—" : money(Math.round(v * 100)));
  if (snapshot) {
    const m = snapshot.metrics;
    section.append(
      el(
        "p",
        `Dernier relevé TCGdex · ${new Date(snapshot.updated || snapshot.observed_at).toLocaleDateString("fr-FR")} · variante ${snapshot.variant}`,
        "help",
      ),
      el(
        "p",
        `Bas ${euros(m.low)} · Moyenne 30 j ${euros(m.avg30)} · Moyenne 7 j ${euros(m.avg7)} · Tendance ${euros(m.trend)}`,
      ),
    );
    if (snapshot.warnings.length) {
      const list = el("ul", undefined, "price-warnings");
      for (const warning of snapshot.warnings) {
        if (card.variant_confirmed && !card.valuation?.price_variant_issue && warning.startsWith("TCGdex ne connaît pas de version Foil")) continue;
        if (card.variant_confirmed && !card.valuation?.price_variant_issue && warning.startsWith("L’autre variante cote")) {
          list.append(el("li", warning.replace(" : une erreur de variante changerait fortement la valeur.", " · comparaison catalogue ; autre catégorie écartée après vérification physique.")));
          continue;
        }
        list.append(el("li", warning));
      }
      section.append(list);
    }
  } else
    section.append(
      el(
        "p",
        card.identification_status === "confirmed" && card.catalog_id
          ? "Aucun relevé détaillé : relevez le prix pour voir le prix bas, les moyennes et les alertes."
          : "Identifiez et confirmez l’édition pour relever son prix.",
        "help",
      ),
    );
  const actions = el("div", undefined, "workflow-actions");
  if (
    editAllowed() &&
    !card.deleted_at &&
    card.identification_status === "confirmed" &&
    card.catalog_id
  ) {
    const refresh = el("button", "Relever le prix (TCGdex)");
    refresh.type = "button";
    refresh.addEventListener("click", async () => {
      if (parent.elements && ["name", "set_name", "number", "language", "catalog_id", "identification_status", "stamp", "stamp_state", "distribution", "distribution_state", "finish"].some((key) => (parent.elements[key]?.value || "") !== (card[key] || ""))) {
        toast("Enregistrez d’abord les observations modifiées, puis relevez le prix.");
        return;
      }
      if (parent.elements?.foil && !parent.elements.foil.disabled && (parent.elements.foil.value === "true") !== Boolean(card.foil)) {
        toast("Enregistrez d’abord la catégorie manuelle, puis relevez le prix.");
        return;
      }
      refresh.disabled = true;
      try {
        await api(`/copies/${card.id}/price-refresh`, {
          method: "POST",
          body: JSON.stringify({ expected_version: card.version }),
        });
        await refreshSummary();
        await openDetail(card.id);
        await loadCards();
        toast("Prix relevé. La référence reste une tendance, pas un prix de vente.");
      } catch (e) {
        refresh.disabled = false;
        toast(e.message);
      }
    });
    actions.append(refresh);
  }
  if (card.cardmarket_url) {
    const link = el("a", "Voir les offres Cardmarket");
    link.href = card.cardmarket_url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    actions.append(link);
    section.append(
      el(
        "p",
        card.stamp
          ? `Variante tamponnée « ${card.stamp} » : Cardmarket la range avec les Foil, mélangée aux reverses. Ne retenez que les offres dont le commentaire mentionne le tampon (« stamp »).`
          : `Filtre : langue de l’exemplaire${card.condition ? `, état ${card.condition} ou meilleur` : ""}${card.foil ? ", offres Foil uniquement" : ""}. Comparez des offres de même variante.`,
        "help",
      ),
    );
  } else if (card.cardmarket_search_url) {
    const link = el("a", "Chercher sur Cardmarket");
    link.href = card.cardmarket_search_url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    actions.append(link);
    section.append(
      el(
        "p",
        "Lien déduit du nom anglais et du numéro : TCGdex ne fournit pas le produit Cardmarket. Vérifiez l’édition sur la page ouverte avant de relever la tendance.",
        "help",
      ),
    );
  }
  if (actions.children.length) section.append(actions);
  renderMarketProduct(section, card);
  renderBoundQuote(section, card);
  renderSaleEstimate(section, card);
  parent.append(section);
}
// TCGdex may give two cards of a set one Cardmarket product (Darkrai GE 3/4).
// A person checks the page and records a verdict for this catalogue id.
function renderMarketProduct(parent, card) {
  const market = card.valuation?.market_product;
  if (!market) return;
  const box = el("div", undefined, "market-product");
  // TCGdex names are English (Airmure is Skarmory): lead with the number.
  const others = (market.shared_with || [])
    .map((o) => `n° ${o.catalog_id.split("-").at(-1)} (${o.name || "?"} en anglais${o.hp ? `, ${o.hp} PV` : ""})`)
    .join(", ");
  const own = (card.catalog_id || "").split("-").at(-1);
  if (market.verdict === "wrong")
    box.append(el("p", `Produit Cardmarket n° ${market.id_product} signalé incorrect : les prix TCGdex de cette carte sont écartés. Relevez la tendance sur la bonne page et saisissez-la comme prix de référence.`, "price-warnings"));
  else if (market.verdict === "verified")
    box.append(el("p", `Produit Cardmarket n° ${market.id_product} vérifié.`, "help"));
  else if (others)
    box.append(el("p", `TCGdex donne aussi ce produit Cardmarket à une autre carte de l’extension : ${others}. Ouvrez la page et vérifiez qu’elle montre votre n° ${own} (PV, niveau, illustration).`, "price-warnings"));
  if (editAllowed() && !card.deleted_at) {
    const details = el("details");
    details.open = Boolean(others) && !market.verdict;
    details.append(el("summary", others && !market.verdict ? "Confirmer ou rejeter ce produit Cardmarket" : "Verdict sur le produit Cardmarket"));
    // Distinct from the form's own "Motif de la modification" field below.
    const label = el("label", "Motif du verdict (obligatoire)");
    const reason = el("input");
    reason.placeholder = "Ex. page BCR 95 conforme ; ou page Lv.38, carte Lv.40";
    reason.maxLength = 1000;
    reason.addEventListener("input", () => reason.setCustomValidity(""));
    label.append(reason);
    // The box sits inside the detail form: Enter must not save the whole form.
    reason.addEventListener("keydown", (event) => {
      if (event.key === "Enter") event.preventDefault();
    });
    const error = el("p", "", "error");
    const buttons = el("div", undefined, "workflow-actions");
    const choices = [
      ["verified", "Produit vérifié", "Produit Cardmarket vérifié."],
      ["wrong", "Produit incorrect", "Produit signalé incorrect ; prix TCGdex retiré."],
      ["", "Annuler le verdict", "Verdict annulé."],
    ].filter(([verdict]) => verdict !== market.verdict && (verdict || market.verdict));
    for (const [verdict, label, done] of choices) {
      const button = el("button", label);
      button.type = "button";
      button.addEventListener("click", async () => {
        if (!reason.value.trim()) {
          // Not `required`: an empty verdict box must not block the main form.
          reason.setCustomValidity("Indiquez le motif du verdict.");
          reason.reportValidity();
          reason.focus();
          return;
        }
        button.disabled = true;
        error.textContent = "";
        try {
          await api(`/copies/${card.id}/market-product`, {
            method: "POST",
            body: JSON.stringify({ expected_version: card.version, verdict, reason: reason.value.trim() }),
          });
          await refreshSummary();
          await openDetail(card.id);
          await loadCards();
          toast(done);
        } catch (e) {
          button.disabled = false;
          error.textContent = e.message;
        }
      });
      buttons.append(button);
    }
    details.append(label, buttons, error);
    box.append(details);
  }
  parent.append(box);
}
// A proven market binding: the metrics of its family are read together on the
// product page and recorded as one acquisition (trend and 30-day average).
function renderBoundQuote(parent, card) {
  const binding = card.reference_binding;
  if (!binding || !editAllowed() || card.deleted_at) return;
  const labels = { trend: "Tendance des prix", avg30: "Prix moyen 30 jours" };
  const box = el("div", undefined, "bound-quote");
  const details = el("details");
  details.append(
    el("summary", "Saisir un relevé Cardmarket lié au référentiel"),
    el("p", `Produit ${binding.product_ref.split(":")[1]}, filtres ${Object.entries(binding.filters).map(([k, v]) => `${k}=${v}`).join(", ")}. Ouvrez « Voir les offres Cardmarket » et recopiez le cadre Info de cette page, toutes les valeurs ensemble.`, "help"),
  );
  const inputs = {};
  // Same order as Cardmarket's Info box: the trend comes before the averages.
  const order = ["trend", "avg30"];
  const metrics = Object.keys(binding.metric_family.metrics).sort((a, b) => (order.indexOf(a) + 1 || 99) - (order.indexOf(b) + 1 || 99) || a.localeCompare(b));
  for (const metric of metrics) {
    const label = el("label", `${labels[metric] || metric} (€)`);
    const input = el("input");
    input.type = "number";
    input.min = "0";
    input.step = "0.01";
    label.append(input);
    inputs[metric] = input;
    details.append(label);
  }
  const dayLabel = el("label", "Date du relevé");
  const day = el("input");
  day.type = "date";
  day.value = new Date().toISOString().slice(0, 10);
  dayLabel.append(day);
  const captureLabel = el("label", "Empreinte de la capture archivée (facultatif)");
  const capture = el("input");
  capture.placeholder = "SHA-256 donné par reference-archive";
  captureLabel.append(capture);
  const reasonLabel = el("label", "Motif (obligatoire)");
  const reason = el("input");
  reason.maxLength = 1000;
  reasonLabel.append(reason);
  // Inside the detail form: no `required`, and Enter must not save the whole form.
  for (const input of [...Object.values(inputs), day, capture, reason])
    input.addEventListener("keydown", (event) => { if (event.key === "Enter") event.preventDefault(); });
  const run = el("button", "Enregistrer le relevé lié");
  run.type = "button";
  const error = el("p", "", "error");
  error.setAttribute("role", "alert");
  run.addEventListener("click", async () => {
    const missing = Object.values(inputs).find((input) => input.value === "");
    if (missing || !reason.value.trim() || !day.value) {
      error.textContent = "Saisissez toutes les valeurs, la date et le motif.";
      return;
    }
    run.disabled = true;
    error.textContent = "";
    try {
      await api(`/copies/${card.id}/bound-quote`, {
        method: "POST",
        body: JSON.stringify({
          expected_version: card.version,
          metrics: Object.fromEntries(Object.entries(inputs).map(([k, input]) => [k, input.value])),
          observed_on: day.value,
          capture_sha256: capture.value.trim(),
          reason: reason.value.trim(),
        }),
      });
      await refreshSummary();
      await openDetail(card.id);
      await loadCards();
      toast("Relevé lié enregistré.");
    } catch (e) {
      run.disabled = false;
      error.textContent = e.message;
    }
  });
  details.append(dayLabel, captureLabel, reasonLabel, run, error);
  box.append(details);
  parent.append(box);
}
// Asking prices pasted from Cardmarket: the server parses them and applies a
// fixed rule (same condition first, else a documented per-step discount).
function renderSaleEstimate(parent, card) {
  const box = el("div", undefined, "sale-estimate");
  const estimate = card.sale_estimate;
  if (estimate) {
    if (card.sale_estimate_stale)
      box.append(el("p", "Estimation ancienne : l’identité, la variante ou l’état a changé. Elle est exclue des totaux ; collez de nouvelles offres pour la refaire.", "price-warnings"));
    box.append(
      el(
        "p",
        `Estimation de vente : ${money(Math.round(estimate.estimate_eur * 100))} (${money(Math.round(estimate.low_eur * 100))} – ${money(Math.round(estimate.high_eur * 100))}) · confiance ${estimate.confidence} · ${estimate.offers_used} offre(s) retenue(s) sur ${estimate.offers_total} · le ${new Date(estimate.observed_at).toLocaleDateString("fr-FR")}`,
        "sale-estimate-value",
      ),
      el("p", estimate.method, "help"),
    );
    if (estimate.warnings.length) {
      const list = el("ul", undefined, "price-warnings");
      for (const warning of estimate.warnings) list.append(el("li", warning));
      box.append(list);
    }
  }
  if (editAllowed() && !card.deleted_at) {
    const details = el("details");
    details.append(
      el(
        "summary",
        estimate ? "Refaire l’estimation avec de nouvelles offres" : "Estimer le prix de vente depuis Cardmarket",
      ),
      el(
        "p",
        "Ouvrez « Voir les offres Cardmarket », sélectionnez toute la page (Ctrl+A), copiez (Ctrl+C) et collez ici. Ce sont des prix demandés, pas des ventes : comptez aussi les frais et le port.",
        "help",
      ),
    );
    const text = el("textarea");
    text.rows = 4;
    text.setAttribute("aria-label", "Offres copiées depuis Cardmarket");
    const run = el("button", "Estimer");
    run.type = "button";
    const error = el("p", "", "error");
    error.setAttribute("role", "alert");
    run.addEventListener("click", async () => {
      if (!text.value.trim()) return;
      run.disabled = true;
      error.textContent = "";
      try {
        await api(`/copies/${card.id}/sale-estimate`, {
          method: "POST",
          body: JSON.stringify({ text: text.value }),
        });
        await openDetail(card.id);
      } catch (e) {
        error.textContent = e.message;
        run.disabled = false;
      }
    });
    details.append(text, run, error);
    box.append(details);
  }
  if (box.children.length) parent.append(box);
}
function renderCopyRemoval(parent, card) {
  if (state.user?.role !== "admin") return;
  const restoring = Boolean(card.deleted_at);
  const section = el("section", undefined, "condition-panel");
  section.setAttribute(
    "aria-label",
    restoring ? "Restaurer l’exemplaire" : "Supprimer l’exemplaire",
  );
  const action = el(
    "button",
    restoring ? "Restaurer cet exemplaire" : "Supprimer cet exemplaire",
  );
  action.type = "button";
  action.disabled = !restoring && card.stock_state !== "available";
  section.append(action);
  const confirmation = el("form");
  confirmation.hidden = true;
  confirmation.append(el("p", cardLocation(card)));
  confirmation.append(
    el(
      "p",
      restoring
        ? "Cet exemplaire retrouvera sa place dans la collection."
        : "Cet exemplaire sera placé dans la corbeille. Ses photos et son historique seront conservés. Vous pourrez le restaurer depuis le filtre Stock → Corbeille.",
      "help",
    ),
  );
  const label = el(
    "label",
    restoring ? "Motif de la restauration" : "Motif de la suppression",
  );
  const reason = el("input");
  reason.required = true;
  reason.maxLength = 1000;
  label.append(reason);
  const confirm = el(
    "button",
    restoring ? "Confirmer la restauration" : "Confirmer la suppression",
    "primary",
  );
  confirm.type = "submit";
  const cancel = el("button", "Annuler");
  cancel.type = "button";
  cancel.addEventListener("click", () => {
    confirmation.hidden = true;
    action.hidden = false;
  });
  const error = el("p", "", "error");
  error.setAttribute("role", "alert");
  confirmation.append(label, confirm, cancel, error);
  action.addEventListener("click", () => {
    action.hidden = true;
    confirmation.hidden = false;
    reason.focus();
  });
  confirmation.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (confirm.disabled) return;
    confirm.disabled = true;
    error.textContent = "";
    try {
      await api(`/copies/${card.id}${restoring ? "/restore" : ""}`, {
        method: restoring ? "POST" : "DELETE",
        body: JSON.stringify({
          expected_version: card.version,
          reason: reason.value,
        }),
      });
      state.selected.delete(card.id);
      selectionBar();
      $("detail-dialog").close();
      await refreshSummary();
      await loadCards();
      toast(
        restoring
          ? "Exemplaire restauré."
          : "Exemplaire placé dans la corbeille.",
      );
    } catch (e) {
      error.textContent = e.message;
    } finally {
      confirm.disabled = false;
    }
  });
  section.append(confirmation);
  parent.append(section);
}
function renderConditionAssessment(parent, card, previous = null) {
  const panel = el("section", undefined, "condition-panel");
  panel.setAttribute("aria-label", "Aide à l’évaluation de l’état");
  panel.append(el("h3", "Aide à l’évaluation de l’état"));
  panel.append(
    el(
      "p",
      `État enregistré : ${card.condition || "inconnu"} · ${card.condition_confirmed ? "vérifié sur la carte" : "à confirmer"}`,
    ),
  );
  const status = el("p", "", "help");
  status.setAttribute("role", "status");
  const error = el("p", "", "error");
  error.setAttribute("role", "alert");
  if (editAllowed()) {
    panel.append(
      el(
        "p",
        "Cette action transmet les photos entières disponibles à Gemini. La proposition ne modifie ni l’état enregistré ni le prix.",
        "help",
      ),
    );
    const evaluate = el("button", "Évaluer l’état", "primary");
    evaluate.type = "button";
    evaluate.disabled = !(card.photo || card.back_photo);
    evaluate.addEventListener("click", async () => {
      evaluate.disabled = true;
      error.textContent = "";
      status.textContent = "Évaluation des photos en cours…";
      try {
        const result = await api(`/copies/${card.id}/condition-assessments`, {
          method: "POST",
          body: JSON.stringify({ expected_version: card.version }),
        });
        card.condition_assessments = [
          result,
          ...(card.condition_assessments || []),
        ];
        if (panel.isConnected) renderConditionAssessment(parent, card, panel);
      } catch (e) {
        error.textContent = e.message;
        status.textContent = "L’état enregistré est conservé.";
      } finally {
        evaluate.disabled = false;
      }
    });
    panel.append(evaluate);
    if (!card.back_photo)
      panel.append(
        el(
          "p",
          "Ajoutez le verso pour examiner les deux faces. Avec une seule face, l’évaluation reste partielle.",
          "help",
        ),
      );
  }
  const assessment = card.condition_assessments?.[0];
  if (assessment) {
    const result = assessment.result;
    panel.append(
      el(
        "h4",
        `Proposition IA : ${result.suggested_condition || "indéterminable"}`,
      ),
    );
    panel.append(
      el(
        "p",
        `Photos ${result.front_usable && result.back_usable ? "recto et verso" : "partielles"} · qualité ${{ adequate: "exploitable", limited: "limitée", unusable: "inexploitable" }[result.quality]} · ${new Date(assessment.created_at).toLocaleString("fr-FR")}`,
        "help",
      ),
    );
    panel.append(el("p", result.explanation));
    for (const [label, flaws] of [
      ["Recto", result.flaws_front],
      ["Verso", result.flaws_back],
    ])
      if (flaws) panel.append(el("p", `${label} : ${flaws}`));
    const limits = el("ul", undefined, "assessment-limits");
    for (const limit of result.limits) limits.append(el("li", limit));
    panel.append(limits);
    if (assessment.stale)
      panel.append(
        el(
          "p",
          "Proposition obsolète : les photos ont changé. Demandez une nouvelle évaluation.",
          "error",
        ),
      );
    else if (editAllowed()) {
      const validation = el("form", undefined, "condition-validation");
      const label = el("label", "État retenu après examen");
      const grade = el("select");
      grade.required = true;
      grade.append(
        new Option("Choisir un état", ""),
        ...["NM", "EX", "GD", "LP", "PL", "PO", "NM/EX"].map(
          (value) => new Option(value, value),
        ),
      );
      grade.value = result.suggested_condition;
      label.append(grade);
      const checkLabel = el("label", undefined, "check-label");
      const check = el("input");
      check.type = "checkbox";
      check.required = true;
      checkLabel.append(
        check,
        document.createTextNode(
          "J’ai examiné la carte en main et je confirme l’état retenu.",
        ),
      );
      const reasonLabel = el("label", "Motif de validation de l’état");
      const reason = el("input");
      reason.required = true;
      reason.maxLength = 1000;
      reason.value = "Examen de la carte et comparaison aux observations IA";
      reasonLabel.append(reason);
      const save = el("button", "Enregistrer l’état vérifié", "primary");
      validation.append(label, checkLabel, reasonLabel, save);
      validation.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (save.disabled || !check.checked) return;
        save.disabled = true;
        error.textContent = "";
        try {
          const changed = await api(
            `/copies/${card.id}/condition-assessments/${assessment.id}/confirm`,
            {
              method: "POST",
              body: JSON.stringify({
                expected_version: card.version,
                condition: grade.value,
                human_confirmed: check.checked,
                reason: reason.value,
              }),
            },
          );
          Object.assign(card, changed);
          const fields = $("detail-body").querySelector(".detail-fields");
          fields.elements.condition.value = card.condition;
          fields.elements.condition_confirmed.checked = Boolean(
            card.condition_confirmed,
          );
          renderConditionAssessment(parent, card, panel);
          await loadCards();
          toast("État vérifié enregistré ; prix conservé.");
        } catch (e) {
          error.textContent = e.message;
        } finally {
          save.disabled = false;
        }
      });
      panel.append(validation);
    }
    if (card.condition_assessments.length > 1) {
      const history = el("details");
      history.append(
        el(
          "summary",
          `Évaluations précédentes (${card.condition_assessments.length - 1})`,
        ),
      );
      for (const past of card.condition_assessments.slice(1))
        history.append(
          el(
            "p",
            `${new Date(past.created_at).toLocaleString("fr-FR")} : ${past.result.suggested_condition || "indéterminable"}${past.stale ? " · photos remplacées" : ""} — ${past.result.explanation}`,
          ),
        );
      panel.append(history);
    }
  } else panel.append(el("p", "Aucune proposition IA enregistrée.", "help"));
  panel.append(status, error);
  if (previous) previous.replaceWith(panel);
  else parent.append(panel);
}
function renderEditionCheck(parent, card, previous = null) {
  const panel = el("section", undefined, "condition-panel");
  panel.setAttribute("aria-label", "Contrôle de l’édition");
  panel.append(el("h3", "Contrôle de l’édition par l’image"));
  const status = el("p", "", "help");
  status.setAttribute("role", "status");
  const error = el("p", "", "error");
  error.setAttribute("role", "alert");
  if (!card.edition_check_available)
    panel.append(
      el(
        "p",
        "Contrôle indisponible sur ce serveur (option vision non installée).",
        "help",
      ),
    );
  else if (editAllowed()) {
    panel.append(
      el(
        "p",
        "Compare la photo du recto, sur cet ordinateur, aux images TCGdex des cartes de même nom. Ne modifie pas la fiche.",
        "help",
      ),
    );
    const run = el("button", "Comparer aux images TCGdex");
    run.type = "button";
    run.disabled =
      !card.photo || !card.catalog_id || card.identification_status !== "confirmed";
    run.addEventListener("click", async () => {
      run.disabled = true;
      error.textContent = "";
      status.textContent =
        "Comparaison en cours (la première fois, téléchargement des images)…";
      try {
        const result = await api(`/copies/${card.id}/edition-checks`, {
          method: "POST",
          body: JSON.stringify({ expected_version: card.version }),
        });
        card.edition_checks = [
          { ...result, current_proposal: result.proposal },
          ...(card.edition_checks || []),
        ];
        if (panel.isConnected) renderEditionCheck(parent, card, panel);
      } catch (e) {
        error.textContent = e.message;
        status.textContent = "La fiche est conservée.";
      } finally {
        run.disabled = false;
      }
    });
    panel.append(run);
  }
  const check = card.edition_checks?.[0];
  if (check) {
    const proposal = check.current_proposal || check.proposal;
    panel.append(
      el(
        "h4",
        {
          agree: "Édition confirmée par l’image",
          undecided: "Image indécise",
          disagree: "Désaccord avec l’édition de la fiche",
          unavailable: "Contrôle à relancer",
        }[proposal.status],
      ),
    );
    panel.append(el("p", proposal.reason));
    const scores = check.result.scores;
    const names = Object.fromEntries(
      check.result.gallery.map((g) => [g.id, g.set_name || g.id]),
    );
    const ranking = Object.keys(scores)
      .sort((a, b) => scores[b] - scores[a])
      .slice(0, 3);
    const list = el("ol", undefined, "help");
    for (const id of ranking)
      list.append(
        el(
          "li",
          `${names[id]} (${id}) · ${scores[id].toFixed(3)}${id === card.catalog_id ? " · édition de la fiche" : ""}`,
        ),
      );
    panel.append(
      list,
      el(
        "p",
        `${Object.keys(scores).length} impressions comparées · ${check.source} ${check.model} · ${new Date(check.created_at).toLocaleString("fr-FR")}`,
        "help",
      ),
    );
    if (check.stale)
      panel.append(
        el(
          "p",
          "Contrôle obsolète : la photo du recto a changé. Relancez la comparaison.",
          "error",
        ),
      );
    else if (check.kept)
      panel.append(
        el("p", "Édition de la fiche conservée après examen de la carte.", "help"),
      );
    else if (proposal.status === "disagree" && editAllowed() && !card.deleted_at) {
      const keep = el("form", undefined, "condition-validation");
      const reasonLabel = el("label", "Motif");
      const reason = el("input");
      reason.required = true;
      reason.maxLength = 1000;
      reason.value = "Édition vérifiée sur la carte malgré le contrôle par l’image";
      reasonLabel.append(reason);
      const save = el("button", "Garder l’édition de la fiche", "primary");
      keep.append(
        el(
          "p",
          "Pour corriger l’édition, utilisez l’identification de la fiche ; le contrôle sera recalculé.",
          "help",
        ),
        reasonLabel,
        save,
      );
      keep.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (save.disabled) return;
        save.disabled = true;
        error.textContent = "";
        try {
          await api(`/copies/${card.id}/edition-checks/${check.id}/keep`, {
            method: "POST",
            body: JSON.stringify({
              expected_version: card.version,
              reason: reason.value,
            }),
          });
          await loadCards();
          await openDetail(card.id);
          toast("Édition conservée ; la carte quitte « À examiner ».");
        } catch (e) {
          error.textContent = e.message;
        } finally {
          save.disabled = false;
        }
      });
      panel.append(keep);
    }
  } else if (card.edition_check_available)
    panel.append(el("p", "Aucun contrôle d’édition enregistré.", "help"));
  panel.append(status, error);
  if (previous) previous.replaceWith(panel);
  else parent.append(panel);
}
const languageNames = {
  fr: "français",
  en: "anglais",
  ja: "japonais",
  de: "allemand",
  es: "espagnol",
  it: "italien",
  pt: "portugais",
  ko: "coréen",
  zh: "chinois",
};
function renderLanguageCheck(panel, card, check, proposal, error) {
  // Readings made before card-finish-v2 do not report the text language.
  if (!check.result.text_language) return;
  panel.append(el("h4", "Langue du texte"));
  panel.append(
    el(
      "p",
      `Texte imprimé (hors nom) : ${languageNames[check.result.text_language] || "langue non lue"}`,
      "help",
    ),
  );
  const conflicts = proposal.language_conflicts || [];
  if (!conflicts.length || check.stale) return;
  if (check.language_kept) {
    panel.append(
      el("p", "Langue de la fiche conservée après examen de la carte.", "help"),
    );
    return;
  }
  const list = el("ul", undefined, "price-warnings");
  for (const conflict of conflicts) list.append(el("li", conflict));
  panel.append(list);
  if (!editAllowed() || card.deleted_at) return;
  const keep = el("form", undefined, "condition-validation");
  const reasonLabel = el("label", "Motif");
  const reason = el("input");
  reason.required = true;
  reason.maxLength = 1000;
  reason.value = "Langue vérifiée sur la carte malgré la lecture";
  reasonLabel.append(reason);
  const save = el("button", "Garder la langue de la fiche");
  keep.append(
    el(
      "p",
      "Pour corriger la langue, modifiez la fiche ; le contrôle sera recalculé.",
      "help",
    ),
    reasonLabel,
    save,
  );
  keep.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (save.disabled) return;
    save.disabled = true;
    error.textContent = "";
    try {
      await api(`/copies/${card.id}/variant-checks/${check.id}/keep-language`, {
        method: "POST",
        body: JSON.stringify({
          expected_version: card.version,
          reason: reason.value,
        }),
      });
      await loadCards();
      await openDetail(card.id);
      toast("Langue conservée ; la carte quitte « À examiner ».");
    } catch (e) {
      error.textContent = e.message;
    } finally {
      save.disabled = false;
    }
  });
  panel.append(keep);
}
const finishLabels = {
  non_holo: "Non holo (mate)",
  holo: "Holo dans l’illustration",
  holo_border: "Holo avec cadre brillant (Prime, LV.X…)",
  reverse: "Reverse (fond brillant)",
  special: "Autre finition / variante spéciale",
};
function renderVariantCheck(parent, card, previous = null) {
  const panel = el("section", undefined, "condition-panel");
  panel.setAttribute("aria-label", "Vérification de la finition et de la langue");
  panel.append(el("h3", "Vérification de la finition et de la langue"));
  panel.append(
    el(
      "p",
      `Fiche : ${finishLabels[card.finish] || "finition à déterminer"} · ${card.foil ? "Foil" : "Standard"} · ${card.variant_confirmed ? "vérifiée sur la carte" : "à confirmer"}`,
    ),
  );
  const status = el("p", "", "help");
  status.setAttribute("role", "status");
  const error = el("p", "", "error");
  error.setAttribute("role", "alert");
  if (editAllowed()) {
    panel.append(
      el(
        "p",
        "Cette action transmet la photo du recto à Gemini. La lecture propose une finition et contrôle la langue du texte ; elle ne modifie ni la fiche ni le prix.",
        "help",
      ),
    );
    const read = el("button", "Lire la finition", "primary");
    read.type = "button";
    read.disabled = !card.photo;
    read.addEventListener("click", async () => {
      read.disabled = true;
      error.textContent = "";
      status.textContent = "Lecture de la photo en cours…";
      try {
        const result = await api(
          `/copies/${card.id}/variant-checks?threshold=${reviewThreshold()}`,
          {
            method: "POST",
            body: JSON.stringify({ expected_version: card.version }),
          },
        );
        // The server recomputes the proposal against the current copy on reload.
        card.variant_checks = [
          { ...result, current_proposal: result.proposal },
          ...(card.variant_checks || []),
        ];
        if (panel.isConnected) renderVariantCheck(parent, card, panel);
      } catch (e) {
        error.textContent = e.message;
        status.textContent = "La fiche est conservée.";
      } finally {
        read.disabled = !card.photo;
      }
    });
    panel.append(read);
  }
  const check = card.variant_checks?.[0];
  if (check) {
    const reading = check.result;
    const proposal = check.current_proposal || check.proposal;
    const headline = {
      proposed: `Proposition : ${finishLabels[proposal.finish]} · ${proposal.foil ? "Foil" : "Standard"}`,
      examine: "Examen physique requis",
      unreadable: "Lecture impossible",
    }[proposal.status];
    panel.append(el("h4", headline));
    panel.append(
      el(
        "p",
        `Illustration ${{ holo: "holo", matte: "mate", unclear: "indéterminée" }[reading.artwork]} · fond ${{ visible: "brillant", not_visible: "mat", unclear: "indéterminé" }[reading.background_shine]} · tampon ${reading.stamp_text ? `« ${reading.stamp_text} »` : "non lu"} · ${check.source} ${check.model} · ${new Date(check.created_at).toLocaleString("fr-FR")}`,
        "help",
      ),
    );
    panel.append(el("p", proposal.reason));
    if (reading.notes) panel.append(el("p", reading.notes, "help"));
    if (proposal.conflicts.length) {
      const conflicts = el("ul", undefined, "price-warnings");
      for (const conflict of proposal.conflicts)
        conflicts.append(el("li", conflict));
      panel.append(conflicts);
    }
    if (check.stale)
      panel.append(
        el(
          "p",
          "Lecture obsolète : la photo du recto a changé. Demandez une nouvelle lecture.",
          "error",
        ),
      );
    else if (editAllowed() && !card.deleted_at) {
      const decision = el("form", undefined, "condition-validation");
      const finishLabel = el("label", "Finition retenue après examen");
      const finish = el("select");
      finish.required = true;
      finish.append(
        new Option("Choisir une finition", ""),
        ...Object.entries(finishLabels).map(
          ([value, label]) => new Option(label, value),
        ),
      );
      // Only a usable proposal pre-fills the choice; an examination starts blank.
      finish.value =
        proposal.status === "proposed" ? proposal.finish : card.finish || "";
      finishLabel.append(finish);
      const stampLabel = el("label", "Observation du tampon");
      const stampState = el("select");
      stampState.append(
        new Option("Non examiné", "unobserved"),
        new Option("Absence constatée", "absent"),
        new Option("Présent sur la carte", "present"),
      );
      stampState.value =
        card.stamp_state !== "unobserved"
          ? card.stamp_state
          : proposal.stamp
            ? "present"
            : "unobserved";
      stampLabel.append(stampState);
      const stampTextLabel = el("label", "Texte du tampon");
      const stamp = el("input");
      stamp.maxLength = 120;
      stamp.value = card.stamp_state !== "unobserved" ? card.stamp : proposal.stamp;
      stampTextLabel.append(stamp);
      const confirmLabel = el("label", undefined, "check-label");
      const confirmed = el("input");
      confirmed.type = "checkbox";
      confirmLabel.append(
        confirmed,
        document.createTextNode(
          "J’ai examiné la carte en main (variante et tampon vérifiés).",
        ),
      );
      const reasonLabel = el("label", "Motif");
      const reason = el("input");
      reason.required = true;
      reason.maxLength = 1000;
      reason.value = "Lecture de la finition comparée à la carte";
      reasonLabel.append(reason);
      const save = el("button", "Enregistrer la finition retenue", "primary");
      decision.append(
        finishLabel,
        stampLabel,
        stampTextLabel,
        confirmLabel,
        reasonLabel,
        save,
      );
      decision.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (save.disabled) return;
        save.disabled = true;
        error.textContent = "";
        try {
          await api(
            `/copies/${card.id}/variant-checks/${check.id}/confirm?threshold=${reviewThreshold()}`,
            {
              method: "POST",
              body: JSON.stringify({
                expected_version: card.version,
                finish: finish.value,
                stamp_state: stampState.value,
                stamp: stampState.value === "present" ? stamp.value : "",
                variant_confirmed: confirmed.checked,
                reason: reason.value,
              }),
            },
          );
          await loadCards();
          await openDetail(card.id);
          toast("Finition enregistrée ; catégorie de prix recalculée.");
        } catch (e) {
          error.textContent = e.message;
        } finally {
          save.disabled = false;
        }
      });
      panel.append(decision);
    }
    renderLanguageCheck(panel, card, check, proposal, error);
    if (card.variant_checks.length > 1) {
      const history = el("details");
      history.append(
        el("summary", `Lectures précédentes (${card.variant_checks.length - 1})`),
      );
      for (const past of card.variant_checks.slice(1))
        history.append(
          el(
            "p",
            `${new Date(past.created_at).toLocaleString("fr-FR")} : illustration ${past.result.artwork}${past.stale ? " · photo remplacée" : ""} — ${past.proposal.reason}`,
          ),
        );
      panel.append(history);
    }
  } else panel.append(el("p", "Aucune lecture de finition enregistrée.", "help"));
  panel.append(status, error);
  if (previous) previous.replaceWith(panel);
  else parent.append(panel);
}
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
  photo.append(
    el("p", `${c.album} · page ${c.page}, pochette ${c.position}`),
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
    renderVariantCheck(photo, c);
    renderEditionCheck(photo, c);
    renderConditionAssessment(photo, c);
  }
  renderCopyRemoval(photo, c);
  form.append(
    el("h2", c.name),
    el(
      "p",
      `${c.number || "Sans référence"} · ${statusLabels[c.identification_status]}`,
      "subtitle",
    ),
  );
  field(form, "name", "Nom", c.name).required = true;
  field(form, "set_name", "Extension", c.set_name);
  let row = pair(form);
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
  row = pair(form);
  field(row, "catalog_id", "Identifiant catalogue (facultatif)", c.catalog_id);
  const hp = field(row, "hp", "PV", c.hp, "number");
  hp.min = "0";
  hp.max = "5000";
  field(
    form,
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
  row = pair(form);
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
  const markStates = [["unobserved", "Non examiné"], ["absent", "Absence constatée"], ["present", "Présent sur la carte"]];
  field(form, "stamp_state", "Observation du tampon", c.stamp_state || "unobserved", "text", markStates);
  const stampText = field(form, "stamp", "Texte du tampon (conservé tel que lu)", c.stamp);
  stampText.maxLength = 120;
  form.append(el("p", "Un ancien texte ou un champ vide ne prouve pas la présence ou l’absence d’un tampon. Choisissez l’état après examen de la carte.", "help"));
  const marks = el("details");
  marks.append(el("summary", "Autre marque de distribution (facultatif)"));
  field(marks, "distribution_state", "Observation d’une marque de produit", c.distribution_state || "unobserved", "text", markStates);
  field(marks, "distribution", "Texte ou marque du produit", c.distribution || "").maxLength = 120;
  form.append(marks);
  const finish = field(form, "finish", "Finition observée sur la carte", c.finish || "", "text", [
    ["", "À déterminer"],
    ["non_holo", "Non holo (mate)"],
    ["holo", "Holo dans l’illustration"],
    ["holo_border", "Holo avec cadre brillant (Prime, LV.X…)"],
    ["reverse", "Reverse (fond brillant)"],
    ["special", "Autre finition / variante spéciale"],
  ]);
  const priceVariant = field(form, "foil", "Catégorie de prix", String(Boolean(c.foil)), "text", [
    ["false", "Standard (version normale de l’édition, mate ou holo d’origine)"],
    ["true", "Foil (reverse ou holo parallèle)"],
  ]);
  const categoryHint = el("p", undefined, "help");
  form.append(categoryHint);
  const displayCategory = (decision) => {
    priceVariant.parentElement.firstChild.textContent = decision?.mode === "automatic" ? "Catégorie de prix calculée" : "Catégorie enregistrée · à vérifier";
    priceVariant.disabled = decision?.mode === "automatic" || !editAllowed() || Boolean(c.deleted_at);
    if (decision?.mode === "automatic") priceVariant.value = String(decision.foil);
    categoryHint.textContent = decision?.mode === "automatic"
      ? `Automatique · ${decision.reason}`
      : `${decision?.reason || "Renseignez la finition observée."} La sélection manuelle est réservée aux cas particuliers.`;
  };
  displayCategory(c.price_category);
  const referenceHint = el("p", undefined, "help");
  const displayReference = (resolution) => {
    if (!resolution) { referenceHint.textContent = ""; return; }
    const states = { verified: "correspondance marchande prouvée", uncovered: "périmètre à documenter", unmapped: "correspondance marchande à documenter", unobserved: "observation manquante", ambiguous: "plusieurs correspondances possibles", conflict: "correspondance contestée", provisional: "correspondance provisoire" };
    referenceHint.textContent = `Audit du référentiel · ${states[resolution.market_status] || "à compléter"}. Les références héritées gardent leur source et leur date ; elles ne sont pas encore certifiées par cet audit.`;
    if (resolution.diagnostic) referenceHint.textContent += ` ${resolution.diagnostic}`;
  };
  displayReference(c.reference_resolution);
  form.append(referenceHint);
  form.append(el("p", "Décrivez ce qui brille sur la carte. L’édition et le tampon permettent de calculer Standard ou Foil / reverse. Si plusieurs impressions restent possibles, précisez le produit dans les observations avant de confirmer.", "help"));
  field(form, "variant_observation", "Observations de vérification (facultatif)", c.variant_observation || "", "textarea").maxLength = 1000;
  const variantLabel = el("label", undefined, "check-label");
  const variantCheck = el("input");
  variantCheck.type = "checkbox";
  variantCheck.name = "variant_confirmed";
  variantCheck.checked = Boolean(c.variant_confirmed);
  variantCheck.disabled = !editAllowed() || Boolean(c.deleted_at);
  variantLabel.append(variantCheck, document.createTextNode("Variante et tampon vérifiés sur la carte physique"));
  form.append(variantLabel);
  if (c.variant_confirmed)
    form.append(el("p", `Vérifiée par ${c.variant_verified_by} le ${new Date(c.variant_verified_at).toLocaleString("fr-FR")}.`, "help"));
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
  form.append(checkLabel);
  field(
    form,
    "album_id",
    "Album",
    c.album_id,
    "text",
    state.summary.albums.map((a) => [a.id, a.name]),
  );
  row = pair(form);
  for (const [name, label, max] of [
    ["page", "Page", 1000],
    ["position", "Pochette", 100],
  ]) {
    const input = field(row, name, label, c[name], "number");
    input.min = "1";
    input.max = String(max);
    input.required = true;
  }
  row = pair(form);
  const price = field(
    row,
    "reference_price_eur",
    c.valuation?.price_variant_issue ? "Ancien prix de référence (€) · catégorie à corriger" : "Prix de référence (€)",
    c.reference_cents === null ? "" : c.reference_cents / 100,
    "number",
  );
  price.step = ".01";
  price.min = "0";
  field(row, "price_source", "Source / métrique du prix", c.price_source);
  form.append(
    el(
      "p",
      c.price_date
        ? `Prix relevé le ${new Date(c.price_date).toLocaleDateString("fr-FR")}. Une correction d’identité ou de variante retire le prix à revérifier.`
        : "Un prix vide reste indisponible. Le prix de vente se définit dans un lot.",
      "subtitle",
    ),
  );
  renderPriceSnapshot(form, c);
  field(form, "notes", "Notes", c.notes, "textarea");
  if (editAllowed() && !c.deleted_at) {
    const reason = field(form, "reason", "Motif de la modification", "");
    reason.required = true;
    reason.maxLength = 1000;
    const save = el("button", "Enregistrer la correction", "primary");
    save.type = "submit";
    form.append(save);
  }
  const error = el("p", "", "error");
  error.setAttribute("role", "alert");
  form.append(error);
  const source = el("details");
  source.append(el("summary", "Lecture et référence d’origine"));
  const raw = el(
    "pre",
    c.source
      ? JSON.stringify(c.source.data, null, 2)
      : "Exemplaire ajouté dans l’application.",
    "source-data",
  );
  source.append(raw);
  form.append(source);
  const history = el("details");
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
      changes = { expected_version: c.version, reason: data.get("reason") };
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
      changes.price_source = data.get("price_source");
    } else if (data.get("price_source") !== c.price_source)
      changes.price_source = data.get("price_source");
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
  $("detail-body").append(layout);
  if (!$("detail-dialog").open) $("detail-dialog").showModal();
}
async function loadSales() {
  const sales = await api("/sales");
  $("sales-list").replaceChildren();
  if (!sales.length) {
    $("sales-list").append(
      el(
        "p",
        editAllowed()
          ? "Aucun lot pour le moment. Cliquez sur « Créer un lot » pour choisir vos cartes."
          : "Aucun lot pour le moment.",
        "empty",
      ),
    );
    return;
  }
  const transitions = {
    draft: [
      ["reserved", "Réserver les cartes"],
      ["cancelled", "Annuler"],
    ],
    reserved: [
      ["sold", "Confirmer la vente"],
      ["cancelled", "Libérer la réservation"],
    ],
    sold: [
      ["shipped", "Marquer expédiée"],
      ["completed", "Clôturer"],
      ["returned", "Enregistrer un retour"],
    ],
    shipped: [
      ["completed", "Clôturer"],
      ["returned", "Enregistrer un retour"],
    ],
    completed: [["returned", "Enregistrer un retour"]],
    cancelled: [],
    returned: [],
  };
  for (const sale of sales) {
    const box = el("article", undefined, "sale");
    const heading = el("div", undefined, "sale-heading");
    heading.append(
      el("h2", sale.title),
      el(
        "span",
        saleLabels[sale.status],
        "badge " +
          (sale.status === "reserved"
            ? "reserved"
            : sale.status === "draft"
              ? "review"
              : "sold"),
      ),
    );
    box.append(
      heading,
      el(
        "p",
        `${sale.items.length} exemplaire${sale.items.length > 1 ? "s" : ""} · ${sale.channel || "Canal à préciser"} · ${money(sale.amount_cents)}`,
        "sale-meta",
      ),
    );
    const items = el("div", undefined, "sale-items");
    for (const item of sale.items) {
      const button = el("button", `${item.name} · ${item.number}`);
      button.addEventListener("click", () =>
        openDetail(item.id).catch((e) => toast(e.message)),
      );
      items.append(button);
    }
    box.append(items);
    if (editAllowed()) {
      const draft = el("a", "Télécharger le brouillon d’annonce", "button");
      draft.href = `/api/sales/${sale.id}/listing-package`;
      box.append(draft);
    }
    box.append(
      el(
        "p",
        `${sale.paid ? "Paiement enregistré · net calculé" : "Net prévu"} : ${money(sale.net_cents)}`,
        "sale-total",
      ),
    );
    if (editAllowed()) {
      const form = el("form"),
        amounts = el("div", undefined, "sale-money");
      for (const [key, label] of [
        ["asking", "Prix affiché (€)"],
        ["target", "Prix cible (€)"],
        ["minimum", "Minimum (€)"],
        ["amount", "Prix (€)"],
        ["fees", "Frais (€)"],
        ["shipping_charged", "Port facturé (€)"],
        ["shipping_cost", "Coût du port (€)"],
        ["packing", "Emballage (€)"],
        ["refund", "Remboursé (€)"],
      ]) {
        const input = field(
          amounts,
          key + "_eur",
          label,
          sale[key + "_cents"] == null ? "" : sale[key + "_cents"] / 100,
          "number",
        );
        input.min = "0";
        input.step = ".01";
        input.required = !["asking", "target", "minimum"].includes(key);
      }
      form.append(amounts);
      field(form, "channel", "Canal", sale.channel);
      field(form, "listing_url", "Lien de l’annonce", sale.listing_url, "url");
      field(
        form,
        "notes",
        "Notes / expédition / retour",
        sale.notes,
        "textarea",
      );
      const paid = el("label", undefined, "check-label"),
        check = el("input");
      check.type = "checkbox";
      check.name = "paid";
      check.checked = Boolean(sale.paid);
      paid.append(check, document.createTextNode("Paiement reçu"));
      form.append(paid);
      const reason = field(form, "reason", "Motif de la mise à jour", "");
      reason.required = true;
      const actions = el("div", undefined, "sale-actions");
      const save = el("button", "Enregistrer");
      save.type = "submit";
      actions.append(save);
      for (const [target, label] of transitions[sale.status]) {
        const button = el(
          "button",
          label,
          target === "reserved" || target === "sold" ? "primary" : "",
        );
        button.type = "submit";
        button.dataset.target = target;
        actions.append(button);
      }
      form.append(actions);
      const error = el("p", "", "error");
      error.setAttribute("role", "alert");
      form.append(error);
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const data = new FormData(form),
          changes = {
            expected_version: sale.version,
            reason: data.get("reason"),
            paid: data.has("paid"),
            channel: data.get("channel"),
            listing_url: data.get("listing_url"),
            notes: data.get("notes"),
          };
        for (const key of [
          "amount",
          "fees",
          "shipping_charged",
          "shipping_cost",
          "packing",
          "refund",
          "asking",
          "target",
          "minimum",
        ])
          changes[key + "_eur"] =
            data.get(key + "_eur") === ""
              ? null
              : Number(data.get(key + "_eur"));
        if (e.submitter.dataset.target)
          changes.status = e.submitter.dataset.target;
        try {
          await api("/sales/" + sale.id, {
            method: "PATCH",
            body: JSON.stringify(changes),
          });
          state.selected.clear();
          state.lotMode = false;
          selectionBar();
          await refreshSummary();
          await loadCards();
          await loadSales();
          toast("Vente et stock mis à jour.");
        } catch (err) {
          error.textContent = err.message;
        }
      });
      box.append(form);
    } else if (sale.notes) box.append(el("p", sale.notes, "sale-meta"));
    $("sales-list").append(box);
  }
}
async function loadUsers() {
  if (typeof Workflows !== "undefined") await Workflows.backupStatus();
  const users = await api("/users");
  $("users-list").replaceChildren();
  for (const u of users) {
    const row = el("form", undefined, "user-access");
    row.append(el("strong", u.username));
    field(row, "role", "Accès", u.role, "text", [
      ["reader", "Consultation"],
      ["editor", "Gestion"],
      ["admin", "Administration"],
    ]);
    const active = el("label", undefined, "check-label"),
      check = el("input");
    check.type = "checkbox";
    check.name = "active";
    check.checked = !u.disabled;
    active.append(check, document.createTextNode("Compte actif"));
    row.append(active);
    const button = el("button", "Modifier l’accès");
    button.type = "submit";
    row.append(button);
    row.addEventListener("submit", async (e) => {
      e.preventDefault();
      const data = new FormData(row);
      try {
        await api("/users/" + u.id, {
          method: "PATCH",
          body: JSON.stringify({
            role: data.get("role"),
            disabled: !data.has("active"),
          }),
        });
        if (u.id === state.user.id) {
          showAccess();
          toast("Accès modifié. Reconnectez-vous.");
        } else {
          await loadUsers();
          toast("Accès mis à jour ; sessions précédentes fermées.");
        }
      } catch (err) {
        toast(err.message);
      }
    });
    $("users-list").append(row);
  }
}
for (const button of document.querySelectorAll("[data-close]"))
  button.addEventListener("click", () => $(button.dataset.close).close());
for (const button of document.querySelectorAll("[data-view]"))
  button.addEventListener("click", async () => {
    changeView(button.dataset.view);
    try {
      if (button.dataset.view === "sales") await loadSales();
      if (button.dataset.view === "settings") await loadUsers();
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
  if ($("save-lot").disabled) return;
  $("save-lot").disabled = true;
  try {
    await api("/sales", { method: "POST", body: JSON.stringify(data) });
    $("sale-dialog").close();
    e.target.reset();
    state.selected.clear();
    state.lotMode = false;
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
function showIntakeCandidates(result) {
  clearIntakeChoice();
  $("intake-candidates").replaceChildren();
  $("intake-catalogue-message").textContent = result.message;
  const form = $("add-form");
  for (const candidate of result.candidates) {
    const entry = el("article", undefined, "intake-candidate-entry");
    const button = el("button", undefined, "intake-candidate");
    button.type = "button";
    button.setAttribute(
      "aria-label",
      `Choisir ${candidate.name}, ${candidate.set_name}, ${candidate.number}`,
    );
    if (candidate.image) {
      const image = el("img");
      image.src = candidate.image;
      image.alt = `Illustration catalogue de ${candidate.name}`;
      image.loading = "lazy";
      entry.append(CardMedia.zoomButton(image));
    }
    button.append(
      el("strong", candidate.name),
      el("span", candidate.set_name),
      el("span", `${candidate.number} · ${candidate.language.toUpperCase()}`),
    );
    button.addEventListener("click", () => {
      clearIntakeChoice();
      intakeState.chosen = candidate.id;
      for (const key of ["name", "number", "set_name", "language", "hp"])
        form.elements[key].value =
          (key === "name"
            ? candidate.printed_name || candidate.name
            : key === "number"
              ? candidate.printed_number || candidate.number
              : candidate[key]) ?? "";
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
    });
    entry.append(button);
    $("intake-candidates").append(entry);
  }
}
for (const key of ["name", "number", "set_name", "language", "hp"]) {
  $("add-form").elements[key].addEventListener("input", clearIntakeChoice);
  $("add-form").elements[key].addEventListener("change", clearIntakeChoice);
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
      { method: "POST", ...(analysis ? {} : { body: JSON.stringify(query) }) },
    );
    if (generation !== intakeState.generation) return;
    if (result.observation) {
      for (const key of ["name", "number", "language", "hp"])
        form.elements[key].value = result.observation[key] ?? "";
      // A printed stamp marks a promo variant: proposed, never silently dropped.
      form.elements.stamp.value = result.observation.stamp_text || "";
      form.elements.stamp_state.value = "unobserved";
      form.elements.set_name.value = "";
    }
    showIntakeCandidates(result);
    if (typeof Workflows !== "undefined") Workflows.changed();
    intakeBusy(
      false,
      result.observation
        ? [
            "Lecture proposée : vérifiez les champs.",
            result.observation.notes,
            result.observation.flaws
              ? "Défauts visibles : " + result.observation.flaws
              : "",
          ]
            .filter(Boolean)
            .join(" ")
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
(async () => {
  try {
    const setup = await api("/setup");
    state.setup = setup.required;
    if (state.setup) {
      $("access-title").textContent = "Créer votre accès privé";
      $("access-help").textContent =
        "Choisissez votre compte administrateur pour commencer. Le mot de passe doit contenir au moins 10 caractères.";
      $("login-submit").textContent = "Créer mon compte";
      $("login-form").elements.password.autocomplete = "new-password";
      showAccess();
    } else {
      try {
        await showWorkspace(await api("/session"));
      } catch {
        showAccess();
      }
    }
  } catch (err) {
    showAccess();
    $("login-error").textContent = err.message;
  }
})();
