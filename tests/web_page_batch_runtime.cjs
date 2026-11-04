const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const controls = new Map();
function element(tag = "div") {
  return {
    tag,
    value: "",
    type: "",
    textContent: "",
    checked: false,
    hidden: false,
    disabled: false,
    children: [],
    addEventListener() {},
    showModal() {
      this.open = true;
    },
    close() {
      this.open = false;
    },
    replaceChildren(...items) {
      this.children = [...items];
    },
    append(...children) {
      this.children.push(...children);
    },
    querySelectorAll(selector) {
      if (selector !== "input:checked") return [];
      const found = [];
      const visit = (node) => {
        if (!node || typeof node !== "object") return;
        if (node.type === "checkbox" && node.checked) found.push(node);
        for (const child of node.children || []) visit(child);
      };
      visit(this);
      return found;
    },
    classList: { add() {}, remove() {} },
    contains() {
      return false;
    },
  };
}
function $(id) {
  if (!controls.has(id)) controls.set(id, element());
  return controls.get(id);
}

const addFields = Object.fromEntries(
  [
    "name",
    "number",
    "set_name",
    "language",
    "hp",
    "finish",
    "stamp",
    "stamp_state",
    "distribution",
    "distribution_state",
    "reason",
    "notes",
    "album_id",
    "page",
    "position",
  ].map((k) => [k, element("input")]),
);
Object.assign($("add-form"), { elements: addFields });

const pageFields = {
  album_id: element("select"),
  page: Object.assign(element("input"), { value: "3" }),
  rotation: Object.assign(element("select"), { value: "auto" }),
};
Object.assign($("page-form"), { elements: pageFields });

const calls = [];
const previewJob = {
  id: "page-job-1",
  status: "preview",
  created_at: "2026-11-03T12:00:00Z",
  data: {
    kind: "page",
    album_id: "album-1",
    album: "Classeur Rubis",
    page: 3,
    rotation: "auto",
    items: [
      {
        key: "pos-1",
        position: 1,
        action: "update",
        id: "card-1",
        name: "Gourgeist",
        location: "Classeur Rubis · P.3 #1",
        version: 1,
        before: "old.jpg",
        result: "new-1.jpg",
      },
      {
        key: "pos-2",
        position: 2,
        action: "create",
        id: null,
        name: "À identifier",
        location: "Classeur Rubis · P.3 #2",
        version: null,
        before: null,
        result: "new-2.jpg",
      },
      {
        key: "pos-3",
        position: 3,
        action: "conflict",
        id: null,
        name: "Carte A / Carte B",
        location: "Classeur Rubis · P.3 #3",
        version: null,
        before: "old-a.jpg",
        result: "new-3.jpg",
      },
    ],
  },
};

const context = vm.createContext({
  $,
  Intl,
  URLSearchParams,
  setTimeout,
  clearTimeout,
  Date,
  FormData,
  document: {
    createTextNode: (text) => ({ textContent: String(text) }),
  },
  intakeState: { token: null, existing: null, chosen: null },
  options: (select, items, selected) => {
    select.value = selected || items[0]?.id || "";
  },
  api: async (path, opts) => {
    calls.push({ path, opts });
    if (path === "/photo-batches") return [previewJob];
    if (path.startsWith("/photo-batches/page?")) return previewJob;
    if (path === "/photo-batches/page-job-1/apply")
      return { ...previewJob, status: "applied" };
    if (path === "/photo-batches/page-job-1/undo")
      return { ...previewJob, status: "undone" };
    return {};
  },
  el: (tag, text, cls) => {
    const node = element(tag);
    if (text !== undefined) node.textContent = String(text);
    if (cls) node.className = cls;
    return node;
  },
  CardMedia: {
    zoomButton: (x) => x,
    photoHeaders: (file) => ({ "Content-Type": file.type }),
    capture: () => {},
  },
  editAllowed: () => true,
  refreshSummary: async () => {},
  loadCards: async () => {},
  toast: () => {},
  state: {
    selected: new Map(),
    summary: { albums: [{ id: "album-1", name: "Classeur Rubis" }] },
  },
  t: require("./i18n_runtime.cjs").t,
});

vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), context);
const workflows = vm.runInContext("Workflows", context);

(async () => {
  await $("capture-page").onclick();
  assert.equal($("page-dialog").open, true);
  assert.equal(pageFields.album_id.value, "album-1");

  await workflows.uploadPage({ type: "image/jpeg", name: "page.jpg" });
  const uploadCall = calls.find((c) =>
    c.path.startsWith("/photo-batches/page?"),
  );
  assert.ok(uploadCall);
  assert.equal(
    uploadCall.path,
    "/photo-batches/page?album_id=album-1&page=3&rotation=auto",
  );
  assert.equal($("page-apply").hidden, false);
  assert.equal($("page-undo").hidden, true);

  // Only pockets 1 (update) and 2 (create) are checked; pocket 3 (conflict) is disabled and unchecked.
  const checked = $("page-results")
    .querySelectorAll("input:checked")
    .map((c) => Number(c.value));
  assert.deepEqual(checked, [1, 2]);

  calls.length = 0;
  await $("page-apply").onclick({ target: $("page-apply") });
  const applyCall = calls.find(
    (c) => c.path === "/photo-batches/page-job-1/apply",
  );
  assert.ok(applyCall);
  assert.deepEqual(JSON.parse(applyCall.opts.body), { positions: [1, 2] });
  assert.equal($("page-apply").hidden, true);
  assert.equal($("page-undo").hidden, false);

  await $("page-undo").onclick({ target: $("page-undo") });
  assert.equal($("page-undo").hidden, true);
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
