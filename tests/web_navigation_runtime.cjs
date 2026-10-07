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
    "?q=Zarbi+%3F&album=album-1&stock=available&status=confirmed&variant=check&limit=40&offset=80",
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
assert.equal(state.offset, 80);
context.syncLocation();
assert(location.search.includes("variant=check"));
assert(!location.search.includes("limit="));
// A refresh reconstructs the same filters/page from the canonical URL.
controls.search.value = "";
controls["stock-filter"].value = "";
state.offset = 0;
context.restoreLocation();
assert.equal(controls.search.value, "Zarbi ?");
assert.equal(controls["stock-filter"].value, "available");
assert.equal(state.offset, 80);
controls.search.value = "Évoli & Pikachu";
context.syncLocation("push");
context.restoreLocation();
assert.equal(controls.search.value, "Évoli & Pikachu");
location.search =
  "?album=missing&stock=invalid&variant=holo&view=settings&limit=999&offset=-1";
context.restoreLocation();
assert.equal(controls["variant-filter"].value, "");
assert.equal(controls["album-filter"].value, "");
assert.equal(controls["stock-filter"].value, "");
assert.equal(state.view, "collection");
assert.equal(state.limit, 200);
assert.equal(state.offset, 0);
