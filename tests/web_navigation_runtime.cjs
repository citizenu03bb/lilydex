const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[2], "utf8");
const controls = {
  search: { value: "" },
  "album-filter": { value: "", options: [{ value: "" }, { value: "album-1" }] },
  "stock-filter": {
    value: "",
    options: ["", "available", "reserved", "sold"].map((value) => ({ value })),
  },
  "status-filter": {
    value: "",
    options: ["", "confirmed", "review"].map((value) => ({ value })),
  },
  "variant-filter": {
    value: "",
    options: ["", "standard", "foil", "check"].map((value) => ({ value })),
  },
  "sort-order": {
    value: "name",
    options: ["name", "binder"].map((value) => ({ value })),
  },
  "display-mode": { value: "copies" },
  "review-filter": { value: "", options: ["", "needed", "coverage"].map((value) => ({ value })) },
  "review-threshold": { value: "10" },
};
const state = {
  user: { role: "editor" },
  view: "collection",
  limit: 40,
  offset: 0,
};
const location = {
  pathname: "/",
  search:
    "?q=Zarbi+%3F&album=album-1&stock=available&status=confirmed&variant=check&sort=binder&limit=40&offset=80",
};
const history = {};
for (const method of ["pushState", "replaceState"])
  history[method] = (_, __, url) => {
    const parsed = new URL(url, "https://example.com");
    location.pathname = parsed.pathname;
    location.search = parsed.search;
  };
const context = vm.createContext({
  state,
  location,
  history,
  URLSearchParams,
  $: (id) => controls[id],
  changeView: (view) => (state.view = view),
});
vm.runInContext(
  source.slice(
    source.indexOf("function collectionQuery("),
    source.indexOf("async function loadCards("),
  ),
  context,
);
context.restoreLocation();
assert.equal(controls.search.value, "Zarbi ?");
assert.equal(controls["stock-filter"].value, "available");
assert.equal(controls["variant-filter"].value, "check");
assert.equal(controls["sort-order"].value, "binder");
assert.equal(state.offset, 80);
context.syncLocation();
assert(location.search.includes("variant=check"));
assert(location.search.includes("sort=binder"));
assert(!location.search.includes("limit="));
// A refresh reconstructs the same filters/page from the canonical URL.
controls.search.value = "";
controls["stock-filter"].value = "";
controls["sort-order"].value = "name";
state.offset = 0;
context.restoreLocation();
assert.equal(controls.search.value, "Zarbi ?");
assert.equal(controls["stock-filter"].value, "available");
assert.equal(controls["sort-order"].value, "binder");
assert.equal(state.offset, 80);
controls.search.value = "Évoli & Pikachu";
context.syncLocation("push");
context.restoreLocation();
assert.equal(controls.search.value, "Évoli & Pikachu");
location.search =
  "?album=missing&stock=invalid&variant=holo&sort=invalid&view=settings&limit=999&offset=-1";
context.restoreLocation();
assert.equal(controls["variant-filter"].value, "");
assert.equal(controls["album-filter"].value, "");
assert.equal(controls["stock-filter"].value, "");
assert.equal(state.view, "collection");
assert.equal(state.limit, 200);
assert.equal(state.offset, 0);
assert.equal(controls["sort-order"].value, "name");
context.syncLocation();
assert(!location.search.includes("sort="));
assert.equal(context.collectionQuery().get("sort"), "name");
// Existing links, with no sort, keep the default name order.
controls["sort-order"].value = "binder";
location.search = "?q=Pikachu";
context.restoreLocation();
assert.equal(controls["sort-order"].value, "name");
// The same order survives display and tab changes without the Foil filter.
for (const view of ["collection", "sales", "settings"]) {
  state.user.role = "admin";
  location.search = `?sort=binder&display=editions&view=${view}`;
  context.restoreLocation();
  assert.equal(controls["sort-order"].value, "binder");
  assert.equal(controls["variant-filter"].value, "");
  assert.equal(controls["display-mode"].value, "editions");
  assert.equal(state.view, view);
  context.syncLocation("push");
  assert.equal(new URLSearchParams(location.search).get("sort"), "binder");
}
location.search = "?review=needed&threshold=12.50&sort=binder&offset=40";
context.restoreLocation();
assert.equal(controls["review-filter"].value, "needed");
assert.equal(context.collectionQuery().get("threshold"), "12.5");
context.syncLocation();
assert.equal(new URLSearchParams(location.search).get("review"), "needed");
controls["review-threshold"].value = "10";
context.restoreLocation();
assert.equal(controls["review-threshold"].value, "12.5");
location.search = "?review=coverage&sort=binder&limit=200";
context.restoreLocation();
assert.equal(controls["review-filter"].value, "coverage");
context.syncLocation();
assert.equal(new URLSearchParams(location.search).get("review"), "coverage");
assert.equal(new URLSearchParams(location.search).get("sort"), "binder");
for (const value of ["", "-1", "NaN", "Infinity", "0", "10001", "1.001", "1e2"]) {
  location.search = `?review=invalid&threshold=${value}`;
  context.restoreLocation();
  assert.equal(controls["review-filter"].value, "");
  assert.equal(context.collectionQuery().get("threshold"), "10");
  context.syncLocation();
  assert(!location.search.includes("threshold="));
}
