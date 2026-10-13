// Bulk price refresh: skips unconfirmed cards and survives individual failures.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[2], "utf8");
const context = vm.createContext({});
vm.runInContext(
  source.slice(
    source.indexOf("function canRefreshPrice("),
    source.indexOf("function cardLocation("),
  ),
  context,
);
const cards = [
  { id: "a", name: "A", identification_status: "confirmed", catalog_id: "x-1", deleted_at: "" },
  { id: "b", name: "B", identification_status: "review", catalog_id: null, deleted_at: "" },
  { id: "c", name: "C", identification_status: "confirmed", catalog_id: "x-2", deleted_at: "" },
  { id: "d", name: "D", identification_status: "confirmed", catalog_id: "x-3", deleted_at: "" },
];
(async () => {
  const calls = [],
    progress = [];
  const result = await context.runPriceRefresh(
    cards,
    async (card) => {
      calls.push(card.id);
      if (card.id === "c") throw new Error("La fiche a changé");
      return { ...card, version: 2, price_snapshot: { warnings: card.id === "d" ? ["!"] : [] } };
    },
    (done, total) => progress.push(`${done}/${total}`),
  );
  assert.deepEqual(calls, ["a", "c", "d"]); // b is never sent.
  assert.deepEqual(progress, ["1/3", "2/3", "3/3"]);
  assert.equal(result.skipped, 1);
  assert.equal(result.updated.map((c) => c.id).join(","), "a,d"); // Arrays from the vm realm.
  assert.equal(result.failed[0].card.id, "c");
  assert.equal(result.failed[0].message, "La fiche a changé");
  assert.equal(result.warned, 1);
  // Variant change: unchanged cards untouched, a pricing failure keeps the patch.
  const patched = [],
    priced = [];
  const change = await context.runVariantChange(
    [
      { ...cards[0], foil: 1 },
      { ...cards[1], foil: 1 },
      { ...cards[2], foil: 0 },
      { ...cards[3], foil: 1 },
    ],
    false,
    async (card) => {
      patched.push(card.id);
      if (card.id === "d") throw new Error("La fiche a changé");
      return { ...card, foil: 0, version: 3 };
    },
    async (card) => {
      priced.push(card.id);
      if (card.id === "a") throw new Error("TCGdex indisponible");
      return card;
    },
  );
  assert.equal(patched.join(","), "a,b,d"); // c is already Standard.
  assert.equal(priced.join(","), "a"); // b is not confirmed: no relevé.
  assert.equal(change.unchanged, 1);
  assert.equal(change.updated.map((c) => c.id).join(","), "a,b");
  assert.equal(change.unpriced[0].card.id, "a");
  assert.equal(change.failed[0].card.id, "d");
})().catch((error) => {
  console.error(error);
  process.exit(1);
});

// Detail price refresh must update the collection totals as well as the card.
(async () => {
  const makeElement = (tag, text) => ({
    tag, text, children: [], handlers: {},
    append(...children) { this.children.push(...children); },
    setAttribute() {},
    addEventListener(event, handler) { this.handlers[event] = handler; },
  });
  let storedPrice = null, total = null, detailPrice = null, listPrice = null;
  const panelContext = vm.createContext({
    el: makeElement,
    money: (n) => n == null ? "Prix indisponible" : String(n),
    editAllowed: () => true,
    renderSaleEstimate: () => {},
    api: async () => { storedPrice = 4200; },
    refreshSummary: async () => { total = storedPrice; },
    openDetail: async () => { detailPrice = storedPrice; },
    loadCards: async () => { listPrice = storedPrice; },
    toast: () => {},
  });
  vm.runInContext(source.slice(source.indexOf("function renderPriceSnapshot("), source.indexOf("function renderSaleEstimate(")), panelContext);
  const parent = makeElement("div");
  panelContext.renderPriceSnapshot(parent, {
    id: "checked-prime", version: 3, identification_status: "confirmed", catalog_id: "hgss3-85", variant_confirmed: true,
    price_snapshot: { metrics: {}, warnings: [
      "TCGdex ne connaît pas de version Foil (reverse) de cette carte",
      "L’autre variante cote 11,00 € : une erreur de variante changerait fortement la valeur.",
    ] },
  });
  const descendants = (node) => [node, ...node.children.flatMap(descendants)];
  const manual = makeElement("div");
  panelContext.renderPriceSnapshot(manual, {
    reference_cents: 5210, price_source: "Cardmarket · tendance", price_date: "2026-10-07",
    valuation: { trend_cents: null, prudent_cents: null },
  });
  assert(descendants(manual).some((n) => n.text?.includes("Référence enregistrée : 5210 · Cardmarket · tendance · 2026-10-07")));
  const nodes = descendants(parent);
  assert(!nodes.some((n) => n.text?.startsWith("TCGdex ne connaît pas de version Foil")));
  assert(nodes.some((n) => n.text?.includes("autre catégorie écartée après vérification physique")));
  await nodes.find((n) => n.tag === "button" && n.text === "Relever le prix (TCGdex)").handlers.click();
  assert.equal(total, 4200);
  assert.equal(detailPrice, total);
  assert.equal(listPrice, total);
  storedPrice = null;
  const unsaved = makeElement("form");
  unsaved.elements = { finish: { value: "non_holo" } };
  panelContext.renderPriceSnapshot(unsaved, {
    id: "pending-finish", version: 4, finish: "holo", identification_status: "confirmed", catalog_id: "ex5-71",
  });
  await descendants(unsaved).find((n) => n.tag === "button" && n.text === "Relever le prix (TCGdex)").handlers.click();
  assert.equal(storedPrice, null); // Do not price the saved print while showing unsaved observations.
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
