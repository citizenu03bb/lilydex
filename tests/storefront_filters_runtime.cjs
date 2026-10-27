// Shared filter URLs, global results, request races and the mobile filter view.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
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
    focus() { focused = id; },
  };
}
const option = value => ({ value, textContent: value });
element("q", "INPUT");
element("max", "INPUT");
element("extension", "SELECT", [option("")]);
element("language", "SELECT", ["", "fr", "en"].map(option));
element("finish", "SELECT", ["", "holo", "reverse"].map(option));
element("sort", "SELECT", ["recent", "price", "price_desc", "name"].map(option));
element("filters", "FORM").reset = () => {
  for (const id of ["q", "max", "extension", "language", "finish"]) elements[id].value = "";
  elements.sort.value = "recent";
};
const classes = new Set();
const windowEvents = {};
const pending = [];
const media = {};
const location = { pathname: "/", search: "", hash: "#extension=Rare&finition=reverse&langue=fr&max=2.50&tri=price" };
const context = vm.createContext({
  URLSearchParams, setTimeout, clearTimeout,
  location, history: { replaceState(_, __, url) { location.hash = url.includes("#") ? url.slice(url.indexOf("#")) : ""; } },
  $: id => elements[id] || element(id),
  el: (tag, text) => ({ tagName: tag.toUpperCase(), textContent: text }),
  document: {
    body: { classList: { add: c => classes.add(c), remove: c => classes.delete(c), contains: c => classes.has(c) } },
    querySelector: () => ({ refreshChips: () => refreshes++ }),
  },
  window: {
    addEventListener: (type, fn) => windowEvents[type] = fn,
    matchMedia: () => ({ addEventListener: (_, fn) => media.change = fn }),
  },
  state: { offset: 0, items: [], total: 0, request: 0 }, PAGE: 48,
  fetch: url => new Promise(resolve => pending.push({ url, resolve })),
  tile: item => item.id,
  photo: (listing, item) => `/photo/${listing.id}/${item.index}`,
  openLink: () => false,
});
vm.runInContext(slice("const FILTERS =", "// A link sent by the seller:"), context);
vm.runInContext(slice("function updateFilterUI(", '$("login-open").addEventListener('), context);
const result = (items, total = items.length) => ({ items, total, languages: ["fr"], extensions: ["Rare", "Commune"], finishes: ["holo", "reverse"] });
const card = id => ({ id, items: [{ index: 0, photos: ["front"] }] });
const respond = (request, body, ok = true) => request.resolve({ ok, json: async () => body });
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
  respond(pending[0], result(Array.from({ length: 48 }, (_, i) => card(i)), 55));
  await first;
  assert.equal(elements.count.textContent, "55 annonces");
  assert.equal(elements["filter-count"].textContent, "(4)");
  assert.equal(elements["filter-apply"].textContent, "Voir les 55 annonces");
  assert.equal(elements.more.hidden, false);
  assert.equal(elements.extension.value, "Rare");
  assert.equal(elements.language.options.find(o => o.value === "en").disabled, true);
  context.state.offset = context.state.items.length;
  const next = context.load(false);
  params = new URL(pending[1].url, "https://example.test").searchParams;
  assert.equal(params.get("offset"), "48");
  assert.equal(params.get("extension"), "Rare");
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
  const failed = context.load();
  respond(pending[4], { detail: "Service indisponible" }, false);
  await failed;
  assert.equal(elements["filter-error"].textContent, "Service indisponible");
  assert.equal(elements["filter-error"].hidden, false);
  assert.equal(elements["filter-apply"].textContent, "Réessayer");
  const retry = elements["filter-apply"].handlers.click();
  respond(pending[5], result([]));
  await retry;
  assert.equal(elements["filter-error"].hidden, true);
  assert.equal(elements["filter-apply"].disabled, false);
  assert.equal(elements["filter-apply"].textContent, "Voir les 0 annonces");
  assert(refreshes > 0);
})().catch(error => { console.error(error); process.exit(1); });
