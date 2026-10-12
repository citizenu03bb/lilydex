const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[2], "utf8");
function element(tag, text) {
  return { tag, text, children: [], append(...nodes) { this.children.push(...nodes); }, replaceChildren() { this.children = []; } };
}
const context = vm.createContext({ el: element, money: (n) => n == null ? "Prix indisponible" : `${n / 100} €` });
vm.runInContext(source.slice(source.indexOf("function renderValuationTotals("), source.indexOf("function syncLocation(")), context);
const target = element("section");
context.renderValuationTotals(target, { copies: 2, trend_cents: 50000, trend_known: 1, trend_missing: 1, prudent_cents: 10000, prudent_known: 1, prudent_missing: 1, sale_estimate_cents: null, sale_estimate_known: 0, sale_estimate_missing: 2 });
assert.equal(target.children.length, 3);
assert.equal(target.children[1].children[1].text, "100 €");
assert.equal(target.children[1].children[2].text, "1/2 exemplaires · 1 sans prix");
assert.equal(target.children[2].children[1].text, "Prix indisponible");
// A refreshed empty result removes the previous amounts, without inventing zero.
context.renderValuationTotals(target, { copies: 0, trend_cents: null, trend_known: 0, trend_missing: 0, prudent_cents: null, prudent_known: 0, prudent_missing: 0, sale_estimate_cents: null, sale_estimate_known: 0, sale_estimate_missing: 0 });
assert.equal(target.children.length, 3);
assert(target.children.every((box) => box.children[1].text === "Prix indisponible"));
