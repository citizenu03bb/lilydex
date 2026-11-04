const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[2], "utf8");
const fr = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));

function node(tag = "div", text = "", cls = "") {
  return {
    tag,
    className: cls,
    hidden: false,
    disabled: false,
    open: false,
    value: "",
    textContent: text,
    children: [],
    append(...items) {
      for (const item of items) {
        this.children.push(item);
      }
    },
    replaceChildren(...items) {
      this.children = [...items];
    },
    showModal() {
      this.open = true;
    },
    close() {
      this.open = false;
    },
    addEventListener(event, handler) {
      this[event] = handler;
    },
  };
}

function textOf(el) {
  if (!el) return "";
  if (typeof el === "string") return el;
  const self = el.textContent || "";
  const childText = (el.children || []).map(textOf).join("");
  return self + childText;
}

function translate(key, params = {}) {
  let template = fr[key] ?? key;
  if (template && typeof template === "object") {
    template = params.count === 1 ? template.one : template.other;
  }
  return String(template).replace(/\{(\w+)\}/g, (_, k) => params[k] ?? "");
}

(async () => {
  const controls = Object.fromEntries(
    [
      "move-selection",
      "move-dialog",
      "move-form",
      "move-album",
      "move-mode",
      "move-slot-fields",
      "move-start-page",
      "move-start-position",
      "move-slots",
      "move-reason",
      "move-preview-button",
      "move-results",
      "move-history",
      "move-apply",
      "move-undo",
      "move-error",
      "move-undo-bar",
      "move-undo-summary",
      "move-undo-last",
    ].map((id) => [id, node("div")]),
  );
  controls["move-mode"].value = "auto";
  controls["move-start-page"].value = "1";
  controls["move-start-position"].value = "1";
  controls["move-slots"].value = "9";
  controls["move-undo-bar"].hidden = true;

  const selectedCard = {
    id: "copy-1",
    name: "Pikachu",
    number: "58/102",
    album_id: "alb-1",
    version: 1,
    stock_state: "available",
  };
  const state = {
    user: { role: "admin" },
    summary: {
      albums: [
        { id: "alb-1", name: "Classeur Wizards" },
        { id: "alb-2", name: "Classeur Platine" },
      ],
    },
    selected: new Map([[selectedCard.id, selectedCard]]),
  };

  let previewJob = {
    id: "job-1",
    status: "preview",
    created_at: "2026-11-04T09:00:00Z",
    data: {
      album_id: "alb-2",
      album_name: "Classeur Platine",
      mode: "from_slot",
      has_collisions: true,
      collisions_count: 1,
      items: [
        {
          id: "copy-1",
          name: "Pikachu",
          number: "58/102",
          from_album: "Classeur Wizards",
          from_page: 1,
          from_position: 1,
          to_album: "Classeur Platine",
          to_page: 2,
          to_position: 1,
          collision: true,
          occupied_by: [{ id: "occ-1", name: "Évoli", number: "55/64" }],
          published: true,
        },
      ],
    },
  };

  const toasts = [];
  const calls = [];
  const context = vm.createContext({
    state,
    $: (id) => controls[id],
    el: (tag, text, cls) => node(tag, text, cls),
    document: {
      createTextNode: (t) => ({ textContent: t, children: [] }),
    },
    Option: function (label, value) {
      this.label = label;
      this.value = value;
    },
    options(select, albums, current = "") {
      select.replaceChildren(...albums.map((a) => ({ label: a.name, value: a.id })));
      select.value = current;
    },
    editAllowed: () => true,
    t: translate,
    toast: (msg) => toasts.push(msg),
    refreshSummary: async () => {},
    loadCards: async () => {},
    api: async (path, opts = {}) => {
      calls.push({ path, method: opts.method || "GET" });
      if (path === "/move-batches" && opts.method === "POST") return previewJob;
      if (path === "/move-batches") return [previewJob];
      if (path === "/move-batches/job-1/apply") {
        previewJob = { ...previewJob, status: "applied" };
        return previewJob;
      }
      if (path === "/move-batches/job-1/undo") {
        previewJob = { ...previewJob, status: "undone" };
        return previewJob;
      }
      return previewJob;
    },
  });

  vm.runInContext(
    source.slice(source.indexOf("let activeMoveBatch = null;")),
    context,
  );

  // 1. Open dialog: picks the other album by default and renders collision warning.
  await controls["move-selection"].click();
  assert.equal(controls["move-dialog"].open, true);
  assert.equal(controls["move-album"].value, "alb-2");
  assert.equal(controls["move-apply"].hidden, false);
  assert.equal(controls["move-apply"].disabled, true, "Collision disables apply");
  assert.match(textOf(controls["move-results"]), /Évoli \(55\/64\)/);
  assert.match(textOf(controls["move-results"]), /Classeur Wizards \(page 1, case 1\) → Classeur Platine \(page 2, case 1\)/);

  // 2. Switch to non-colliding preview and apply.
  previewJob = {
    ...previewJob,
    data: {
      ...previewJob.data,
      has_collisions: false,
      collisions_count: 0,
      items: [{ ...previewJob.data.items[0], collision: false, occupied_by: [] }],
    },
  };
  await controls["move-form"].submit({ preventDefault() {}, submitter: controls["move-preview-button"] });
  assert.equal(controls["move-apply"].disabled, false);

  await controls["move-apply"].click({ target: controls["move-apply"] });
  assert.equal(state.selected.size, 0, "Applying clears selection");
  assert.equal(controls["move-undo"].hidden, false);
  assert.equal(controls["move-undo-bar"].hidden, false, "Post-move undo bar is visible");
  assert.match(controls["move-undo-summary"].textContent, /1 carte déplacée vers « Classeur Platine »/);

  // 3. Undo from the main page undo bar.
  await controls["move-undo-last"].click({ target: controls["move-undo-last"] });
  assert.equal(controls["move-undo-bar"].hidden, true);
  assert.equal(controls["move-undo"].hidden, true);
  assert.equal(toasts.at(-1), fr["move.undone_toast"]);
})();
