// A summary refresh must not clear the album of an ongoing capture series.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[2], "utf8");
const slice = (start, end) =>
  source.slice(source.indexOf(start), source.indexOf(end));
function select() {
  return {
    options: [],
    selected: "",
    replaceChildren() {
      this.options = [];
      this.selected = "";
    },
    append(option) {
      this.options.push(option);
      if (this.options.length === 1) this.selected = option.value;
    },
    get value() {
      return this.selected;
    },
    // Like a browser: an unknown value leaves nothing selected.
    set value(v) {
      this.selected = this.options.some((o) => o.value === v) ? v : "";
    },
  };
}
const controls = {
  stats: { replaceChildren() {}, append() {} },
  "album-filter": select(),
  "add-form": { elements: { album_id: select() } },
};
const albums = [
  { id: "diamond-pearl", name: "Diamond & Pearl" },
  { id: "series-album", name: "Gotta catch 'em all!" },
];
const context = vm.createContext({
  $: (id) => controls[id],
  el: () => ({ append() {} }),
  Option: function (text, value) {
    return { text, value };
  },
  api: async () => ({ copies: 1, editions: 1, available: 1, albums }),
  renderValuationTotals: () => {},
});
vm.runInContext(
  "var state = {};" +
    slice("function options(", "function showAccess(") +
    slice("async function refreshSummary(", "async function showWorkspace("),
  context,
);
(async () => {
  const album = controls["add-form"].elements.album_id;
  await context.refreshSummary();
  album.value = "series-album"; // Set by Workflows.attach for the series.
  await context.refreshSummary(); // After saving a card of the series.
  assert.equal(album.value, "series-album");
  albums.pop(); // A removed album is not kept as a stale selection.
  await context.refreshSummary();
  assert.equal(album.value, "");
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
