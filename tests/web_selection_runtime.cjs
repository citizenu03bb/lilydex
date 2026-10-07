const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[2], "utf8");

function node() {
  return {
    hidden: false,
    disabled: false,
    textContent: "",
    children: [],
    append(child) {
      this.children.push(child);
    },
    replaceChildren() {
      this.children = [];
    },
    setAttribute() {},
    addEventListener(event, handler) {
      this[event] = handler;
    },
  };
}

for (const lotMode of [false, true]) {
  const controls = Object.fromEntries(
    [
      "clear-selection",
      "selection-bar",
      "lot-builder",
      "prepare-sale",
      "refresh-prices",
      "change-variant",
      "finish-lot",
      "select-visible",
      "selection-count",
      "lot-summary",
      "lot-selected",
    ].map((id) => [id, node()]),
  );
  const visible = { id: "visible", stock_state: "available" };
  const offPage = { id: "another-page", stock_state: "available" };
  const state = {
    user: { role: "admin" },
    selected: new Map([visible, offPage].map((card) => [card.id, card])),
    visibleCards: [visible],
    lotMode,
  };
  const checkbox = { checked: false };
  const card = {
    dataset: { copyId: visible.id },
    selected: false,
    classList: { toggle: (_, selected) => (card.selected = selected) },
    querySelector: () => checkbox,
  };
  let requests = 0;
  const context = vm.createContext({
    state,
    $: (id) => controls[id],
    document: { querySelectorAll: () => [card] },
    editAllowed: () => true,
    el: node,
    cardLocation: (card) => card.id,
    selectCopy() {},
    toast() {},
    // A slow or unavailable server must not delay clearing client selection.
    loadCards: () => {
      requests++;
      return new Promise(() => {});
    },
  });
  vm.runInContext(
    source.slice(
      source.indexOf("function selectionBar("),
      source.indexOf("function cardLocation("),
    ) +
      source.slice(
        source.indexOf('$("clear-selection").addEventListener('),
        source.indexOf('for (const id of ["create-lot", "sales-create-lot"])'),
      ),
    context,
  );
  context.selectionBar();
  assert.equal(checkbox.checked, true);
  assert.equal(controls["lot-selected"].children.length, 2);
  controls["clear-selection"].click();
  assert.equal(state.selected.size, 0, "Also clear copies on another page");
  assert.equal(checkbox.checked, false);
  assert.equal(card.selected, false);
  assert.equal(
    controls["selection-count"].textContent,
    "0 exemplaire sélectionné",
  );
  assert.equal(controls["lot-selected"].children.length, 0);
  assert.equal(controls["prepare-sale"].disabled, true);
  assert.equal(controls["finish-lot"].disabled, true);
  assert.equal(controls["select-visible"].disabled, false);
  assert.equal(controls["selection-bar"].hidden, !lotMode);
  assert.equal(controls["lot-builder"].hidden, !lotMode);
  assert.equal(requests, 0, "Clearing selection must work without a request");
}
