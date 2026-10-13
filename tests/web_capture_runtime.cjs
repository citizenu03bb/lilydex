const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const controls = new Map();
function element() {
  return {
    value: "",
    checked: false,
    hidden: false,
    disabled: false,
    children: [],
    addEventListener() {},
    replaceChildren() {
      this.children = [];
    },
    append(...children) {
      this.children.push(...children);
    },
    querySelectorAll() {
      return [];
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
const fields = Object.fromEntries(
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
    "album_id",
    "page",
    "position",
  ].map((k) => [k, element()]),
);
Object.assign($("add-form"), { elements: fields });
fields.name.value = "Carte à conserver";
fields.language.value = "fr";
fields.reason.value = "Essai";
fields.page.value = "1";
fields.position.value = "9";
fields.name.disabled = true; // Saving/uploading disables controls but must keep their values.
const intakeState = { token: "front-token", existing: null, chosen: null };
const session = {
  id: "session",
  album_id: "album",
  version: 4,
  slots: 9,
  data: { completed: 0, page: 1, position: 9, fields: {}, back_token: null },
};
const calls = [];
let latest = session;
const context = vm.createContext({
  $,
  intakeState,
  setTimeout,
  clearTimeout,
  Date,
  FormData,
  api: async (path, options) => {
    calls.push({ path, options });
    if (options?.method === "PATCH") return { ...session, version: 5 };
    return latest;
  },
  el: () => element(),
  CardMedia: {
    zoomButton: (x) => x,
    photoHeaders: (file) => ({ "Content-Type": file.type }),
  },
  editAllowed: () => true,
  state: { selected: new Map(), summary: { albums: [] } },
});
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), context);
const workflows = vm.runInContext("Workflows", context);
(async () => {
  workflows.attach(session);
  await workflows.persist();
  const patch = JSON.parse(calls[0].options.body);
  assert.equal(patch.fields.name, "Carte à conserver");
  assert.equal(patch.expected_version, 4);
  assert.equal(patch.front_token, "front-token");
  // The server committed a card, but the phone lost the response. The retry must
  // reach the idempotent save endpoint without trying to reuse a consumed draft.
  latest = {
    ...session,
    version: 6,
    data: {
      ...session.data,
      last_token: "front-token",
      last_copy: "saved-card",
      completed: 1,
      page: 2,
      position: 1,
    },
  };
  calls.length = 0;
  const retry = await workflows.prepareSave({
    name: "Carte à conserver",
    album_id: "album",
    page: 1,
    position: 9,
    reason: "Essai",
  });
  assert.equal(retry.url, "/capture-sessions/session/save");
  assert.equal(retry.data.token, "front-token");
  assert.equal(retry.data.expected_version, 6);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, "/capture-sessions/session");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
