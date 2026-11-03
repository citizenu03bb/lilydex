// An alert's link (/gestion?demande=…) opens that request, even though loading
// the workspace rewrites the address before the requests are listed.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[2], "utf8");
const slice = (start, end) =>
  source.slice(source.indexOf(start), source.indexOf(end));
const views = [];
let focusedWhenListed;
const location = { search: "?demande=r-42" };
const context = vm.createContext({
  URLSearchParams,
  location,
  $: () => ({}),
  editAllowed: () => true,
  refreshSummary: async () => {},
  restoreLocation: () => {},
  changeView: (view) => {
    views.push(view);
    context.state.view = view;
  },
  // Like syncLocation: the address is rebuilt without the request.
  loadCards: async () => {
    location.search = "?view=sales";
  },
  loadSales: async () => {
    focusedWhenListed = context.focusedRequest();
  },
  loadUsers: async () => {},
  loadAudience: async () => {},
});
vm.runInContext(
  "var state = {};" +
    slice("// An alert's link", "function collectionQuery("),
  context,
);
(async () => {
  await context.showWorkspace({ username: "lily", role: "editor" });
  assert.deepEqual(views, ["sales"]);
  assert.equal(focusedWhenListed, "r-42");
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
