// A close-up series link (/gestion?prises=id,id,…) opens the series on those
// copies for an administrator, even though loading the workspace rewrites the
// address; an editor, or a malformed id, opens nothing.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[2], "utf8");
const slice = (start, end) =>
  source.slice(source.indexOf(start), source.indexOf(end));
const A = "0cac5d86-807d-65f6-a2e2-e46273f7c793";
const B = "e85c8200-9142-5762-992d-f0bf64dcdc3d";

async function run(search, role) {
  const opened = [];
  const location = { search };
  const context = vm.createContext({
    URLSearchParams,
    location,
    $: () => ({}),
    editAllowed: () => true,
    refreshSummary: async () => {},
    refreshPhotoRequests: async () => {},
    refreshFloorRequests: async () => {},
    toast: () => {},
    restoreLocation: () => {},
    changeView: () => {},
    Closeups: { attach: () => {}, open: async (scope) => opened.push(scope) },
    loadCards: async () => {
      location.search = "";
    },
    loadSales: async () => {},
    loadUsers: async () => {},
    loadAudience: async () => {},
  });
  vm.runInContext(
    "var state = {};" + slice("// An alert's link", "function collectionQuery("),
    context,
  );
  await context.showWorkspace({ username: "lily", role });
  return JSON.parse(JSON.stringify(opened));
}

(async () => {
  assert.deepEqual(await run(`?prises=${A},${B}`, "admin"), [{ copy_ids: [A, B] }]);
  assert.deepEqual(await run(`?prises=${A},not-an-id`, "admin"), [{ copy_ids: [A] }]);
  assert.deepEqual(await run(`?prises=${A}`, "editor"), []);
  assert.deepEqual(await run("?prises=", "admin"), []);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
