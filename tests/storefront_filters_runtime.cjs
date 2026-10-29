// Shared filter URLs, global results, request races and the mobile filter view.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const { t, translator } = require("./i18n_runtime.cjs");
const source = fs.readFileSync(process.argv[2], "utf8");
const slice = (from, to) => source.slice(source.indexOf(from), source.indexOf(to));
const elements = {};
let focused, refreshes = 0;
function element(id, tagName = "BUTTON", options = []) {
  return elements[id] = {
    tagName, value: "", options, hidden: false, disabled: false, open: false,
    textContent: "", attributes: {}, handlers: {}, children: [],
    append(option) { this.options.push(option); },
    replaceChildren(...children) {
      this.children = children;
      if (this.tagName === "SELECT") this.options = children;
    },
    setAttribute(key, value) { this.attributes[key] = value; },
    addEventListener(type, fn) { this.handlers[type] = fn; },
    focus() { focused = id; context.document.activeElement = this; },
  };
}
const option = value => ({ value, textContent: value });
element("q", "INPUT");
element("max", "INPUT");
element("extension", "SELECT", [option("")]);
element("language", "SELECT", ["", "fr", "en"].map(option));
element("finish", "SELECT", ["", "holo", "reverse"].map(option));
element("condition", "SELECT", ["", "MT", "NM", "NM/EX", "EX", "GD", "LP", "PL", "PO", "unknown"].map(option));
element("sort", "SELECT", ["recent", "price", "price_desc", "name"].map(option));
element("filters", "FORM").reset = () => {
  for (const id of ["q", "max", "extension", "language", "finish", "condition"]) elements[id].value = "";
  elements.sort.value = "recent";
};
const classes = new Set();
const windowEvents = {};
const pending = [];
const media = {};
const location = { pathname: "/", search: "", hash: "#extension=Rare&finition=reverse&langue=fr&max=2.50&tri=price" };
const context = vm.createContext({
  watchPhoto: () => {}, refreshLanguageLink: () => {}, pageTitle: "Shop",
  t,
  URLSearchParams, setTimeout, clearTimeout,
  location, history: { replaceState(_, __, url) { location.hash = url.includes("#") ? url.slice(url.indexOf("#")) : ""; } },
  $: id => elements[id] || element(id),
  el: (tag, text) => ({ tagName: tag.toUpperCase(), textContent: text }),
  document: {
    body: { classList: { add: c => classes.add(c), remove: c => classes.delete(c), contains: c => classes.has(c), toggle: (c,on) => on ? classes.add(c) : classes.delete(c) } },
    querySelector: () => ({ refreshChips: () => refreshes++ }),
  },
  window: {
    addEventListener: (type, fn) => windowEvents[type] = fn,
    matchMedia: () => ({ addEventListener: (_, fn) => media.change = fn }),
  },
  state: { offset: 0, items: [], total: 0, request: 0 }, PAGE: 48,
  fetch: url => new Promise((resolve, reject) => pending.push({ url, resolve, reject })),
  tile: item => item.id,
  photo: (listing, item) => `/photo/${listing.id}/${item.index}`,
  openLink: () => false,
});
vm.runInContext(slice("const FILTERS =", "// A link sent by the seller:"), context);
vm.runInContext(slice("// The server's French detail", "\nconst euros"), context);
vm.runInContext(slice("function updateFilterUI(", '$("login-open").addEventListener('), context);
const result = (items, total = items.length) => ({ items, total, languages: ["fr"], extensions: ["Rare", "Commune"], finishes: ["holo", "reverse"] });
const card = id => ({ id, items: [{ index: 0, photos: ["front"] }] });
const respond = (request, body, ok = true, status = ok ? 200 : 500) =>
  request.resolve({ ok, status, json: async () => body });
(async () => {
  context.readFilters();
  assert.equal(elements.extension.value, "Rare"); // before facets arrive
  assert.equal(elements.finish.value, "reverse");
  assert.equal(elements.sort.value, "price");
  const first = context.load();
  let params = new URL(pending[0].url, "https://example.test").searchParams;
  for (const [key, value] of Object.entries({ extension: "Rare", finish: "reverse", language: "fr", max_eur: "2.50", limit: "48", offset: "0" }))
    assert.equal(params.get(key), value);
  assert.equal(elements["filter-apply"].disabled, true);
  assert.equal(elements["results-status"].textContent, t("results.loading"));
  assert.equal(elements["results-status"].hidden, false);
  assert.equal(elements.more.disabled, true);
  respond(pending[0], result(Array.from({ length: 48 }, (_, i) => card(i)), 55));
  await first;
  assert.equal(elements.count.textContent, "55 annonces");
  assert.equal(elements["filter-count"].textContent, "(4)");
  assert.equal(elements["filter-apply"].textContent, "Voir les 55 annonces");
  assert.equal(elements.more.hidden, false);
  assert.equal(elements.more.disabled, false);
  assert.equal(elements.extension.value, "Rare");
  assert.equal(elements.language.options.find(o => o.value === "en").disabled, true);
  elements.condition.value = "unknown";
  context.state.offset = context.state.items.length;
  const next = context.load(false);
  params = new URL(pending[1].url, "https://example.test").searchParams;
  assert.equal(params.get("offset"), "48");
  assert.equal(params.get("extension"), "Rare");
  assert.equal(params.get("condition"), "unknown");
  respond(pending[1], result(Array.from({ length: 7 }, (_, i) => card(i + 48)), 55));
  await next;
  assert.equal(context.state.items.length, 55);
  assert.equal(elements.more.hidden, true);
  // An older failed search must not overwrite a newer successful result.
  elements.extension.value = "Ancienne";
  const old = context.load();
  elements.extension.value = "Nouvelle";
  const current = context.load();
  respond(pending[3], result([card("new")], 1));
  await current;
  respond(pending[2], { detail: "Ancienne erreur" }, false);
  await old;
  assert.equal(context.state.items[0].id, "new");
  assert.equal(elements.error.hidden, true);
  assert.equal(elements.extension.value, "Nouvelle"); // withdrawn/unknown option stays removable
  assert.match(location.hash, /extension=Nouvelle/);
  // Mobile editing uses the same fields, preserves values and returns focus.
  elements["filter-open"].handlers.click();
  assert(classes.has("filters-open"));
  assert.equal(focused, "extension");
  assert.equal(elements["filter-open"].attributes["aria-expanded"], "true");
  windowEvents.keydown({ key: "Escape" });
  assert(!classes.has("filters-open"));
  assert.equal(focused, "filter-open");
  elements["filter-open"].handlers.click();
  media.change({ matches: false });
  assert(!classes.has("filters-open"));
  assert.equal(elements.finish.value, "reverse");
  // Invalid enum values from a shared URL return to the default.
  location.hash = "#finition=invented&tri=invented";
  context.readFilters();
  assert.equal(elements.finish.value, "");
  assert.equal(elements.sort.value, "recent");
  location.hash = "#condition=NM%2FEX";
  context.readFilters();
  assert.equal(elements.condition.value, "NM/EX");
  context.updateFacets({ languages: [], finishes: [], conditions: [] });
  assert.equal(elements.condition.options.find(o => o.value === "NM/EX").disabled, false);
  context.writeFilters();
  assert.match(location.hash, /condition=NM%2FEX/);
  location.hash = "#condition=invented";
  context.readFilters();
  assert.equal(elements.condition.value, "");
  const failed = context.load();
  respond(pending[4], { detail: "Service indisponible" }, false);
  await failed;
  assert.equal(elements["filter-error"].textContent, t("error.server"));
  assert.equal(elements["filter-error"].hidden, false);
  assert.equal(elements["filter-apply"].textContent, "Réessayer");
  assert.equal(elements["results-retry"].hidden, false);
  assert.equal(elements["results-retry"].disabled, false);
  assert.equal(elements.count.textContent, "");
  assert.equal(elements["results-status"].textContent, t("results.previous"));
  assert.equal(elements.more.hidden, true);
  const retry = elements["filter-apply"].handlers.click();
  respond(pending[5], result([]));
  await retry;
  assert.equal(elements["filter-error"].hidden, true);
  assert.equal(elements["filter-apply"].disabled, false);
  assert.equal(elements["filter-apply"].textContent, "Voir les 0 annonces");
  assert.equal(elements["results-retry"].hidden, true);
  assert.equal(elements["results-empty"].hidden, false);

  // Network and parsing failures never expose a browser's technical exception.
  elements.q.value = "eevee";
  const network = context.load();
  pending.at(-1).reject(new TypeError("Failed to fetch"));
  await network;
  assert.equal(elements.error.textContent, t("error.network"));
  assert.equal(elements.q.value, "eevee");
  assert.match(location.hash, /q=eevee/);
  assert.equal(elements["results-empty"].hidden, true);
  assert.equal(elements["results-status"].textContent, ""); // no older cards
  assert.equal(elements["results-status"].hidden, false); // live region stays present
  const invalidJson = context.load();
  pending.at(-1).resolve({ ok: true, status: 200, json: async () => { throw new SyntaxError("Unexpected token '<'"); } });
  await invalidJson;
  assert.equal(elements.error.textContent, t("error.response"));
  const invalidBody = context.load();
  respond(pending.at(-1), { detail: "not a listing response" });
  await invalidBody;
  assert.equal(elements.error.textContent, t("error.response"));

  // An unreadable listing must not replace the last usable state or DOM.
  const usable = context.load();
  respond(pending.at(-1), result([card("kept")], 1));
  await usable;
  const oldItems = context.state.items;
  const oldTiles = elements.grid.children;
  for (const items of [[null], [{ id: "missing-items" }], [{ items: [null] }]]) {
    const malformed = context.load();
    respond(pending.at(-1), result(items, 1));
    await malformed;
    assert.equal(elements.error.textContent, t("error.response"));
    assert.equal(context.state.items, oldItems);
    assert.equal(elements.grid.children, oldTiles);
  }
  const renderTile = context.tile;
  context.tile = () => { throw new TypeError("Broken rendering detail"); };
  const unreadable = context.load();
  respond(pending.at(-1), result([card("broken")], 1));
  await unreadable;
  assert.equal(elements.error.textContent, t("error.response"));
  assert.equal(context.state.items, oldItems);
  assert.equal(elements.grid.children, oldTiles);
  context.tile = renderTile;

  // Known errors are localised; unknown server detail stays out of the English UI.
  const en = JSON.parse(fs.readFileSync(require("node:path").join(__dirname, "../src/pokeprice/web/messages/en.json"), "utf8"));
  context.t = translator(en, "en-GB");
  const limited = context.load();
  respond(pending.at(-1), { code: "too_many_requests", detail: "Texte français" }, false, 429);
  await limited;
  assert.equal(elements.error.textContent, en["error.too_many_requests"]);
  const unknown = context.load();
  respond(pending.at(-1), { code: "unknown_error", detail: "Texte français" }, false, 503);
  await unknown;
  assert.equal(elements.error.textContent, en["error.server"]);
  context.t = t;

  // Retrying an append keeps the loaded cards and requests exactly the failed page.
  const base = context.load();
  respond(pending.at(-1), result(Array.from({ length: 48 }, (_, i) => card(i)), 55));
  await base;
  const append = context.load(false);
  const appendRequest = pending.at(-1);
  const beforeDuplicate = pending.length;
  await context.load(false);
  assert.equal(pending.length, beforeDuplicate);
  assert.equal(elements.more.disabled, true);
  assert.equal(new URL(appendRequest.url, "https://example.test").searchParams.get("offset"), "48");
  respond(appendRequest, { detail: "Pas maintenant" }, false, 503);
  await append;
  assert.equal(context.state.items.length, 48);
  assert.equal(elements.grid.children.length, 48);
  elements["results-retry"].focus();
  const appendRetry = elements["results-retry"].handlers.click();
  assert.equal(new URL(pending.at(-1).url, "https://example.test").searchParams.get("offset"), "48");
  respond(pending.at(-1), result(Array.from({ length: 7 }, (_, i) => card(i + 48)), 55));
  await appendRetry;
  assert.equal(context.state.items.length, 55);
  assert.equal(new Set(context.state.items.map(x => x.id)).size, 55);
  assert.equal(elements.more.hidden, true);
  assert.equal(focused, "results");

  // Disabling Retry may blur it to BODY in Chrome before the response arrives.
  const focusFailure = context.load();
  pending.at(-1).reject(new TypeError("Failed to fetch"));
  await focusFailure;
  elements["results-retry"].focus();
  const blurredRetry = elements["results-retry"].handlers.click();
  context.document.activeElement = context.document.body;
  focused = "BODY";
  respond(pending.at(-1), result([card("restored")], 1));
  await blurredRetry;
  assert.equal(focused, "results");

  // If the visitor chooses the search field while waiting, keep that focus.
  const anotherFailure = context.load();
  pending.at(-1).reject(new TypeError("Failed to fetch"));
  await anotherFailure;
  elements["results-retry"].focus();
  const fieldChosen = elements["results-retry"].handlers.click();
  context.document.activeElement = context.document.body;
  elements.q.focus();
  respond(pending.at(-1), result(Array.from({ length: 55 }, (_, i) => card(i)), 55));
  await fieldChosen;
  assert.equal(focused, "q");

  // A late success cannot erase the newest error or restore an obsolete count.
  const late = context.load();
  const lateRequest = pending.at(-1);
  const newest = context.load();
  respond(pending.at(-1), {}, false, 503);
  await newest;
  respond(lateRequest, result([card("obsolete")], 1));
  await late;
  assert.equal(elements.error.textContent, t("error.server"));
  assert.equal(context.state.items.length, 55);
  assert.equal(elements.count.textContent, "");

  // Editing invalidates an older fetch immediately, before the debounce expires.
  const inFlight = context.load();
  const inFlightRequest = pending.at(-1);
  elements.q.value = "new query";
  elements.filters.handlers.input();
  vm.runInContext("clearTimeout(typing)", context);
  respond(inFlightRequest, result([card("old-query")], 1));
  await inFlight;
  assert.equal(elements.count.textContent, "");
  assert.equal(elements["results-status"].textContent, t("results.loading"));
  assert.equal(context.state.items.length, 55);
  assert.equal(elements.more.disabled, true);
  const fresh = context.load();
  respond(pending.at(-1), result([]));
  await fresh;
  assert.equal(elements["results-empty"].hidden, false);

  // Empty results offer a complete reset and preserve a useful focus location.
  elements.finish.value = "reverse";
  elements.condition.value = "unknown";
  const cleared = elements["results-reset"].handlers.click();
  assert.equal(focused, "q");
  assert.equal(elements.q.value, "");
  assert.equal(elements.finish.value, "");
  assert.equal(elements.condition.value, "");
  assert.equal(location.hash, "");
  respond(pending.at(-1), result([card("available")], 1));
  await cleared;
  assert.equal(elements["results-empty"].hidden, true);
  assert.equal(elements.error.hidden, true);
  assert.equal(focused, "q");
  assert(refreshes > 0);
})().catch(error => { console.error(error); process.exit(1); });
