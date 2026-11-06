const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[2], "utf8");
function element(tag, text) {
  return { tag, text, children: [], append(...nodes) { this.children.push(...nodes); }, replaceChildren() { this.children = []; } };
}
const path = require("node:path");
const web = path.dirname(process.argv[2]);
const components = fs.readFileSync(path.join(web, "components.js"), "utf8");
const dictionary = (language) => JSON.parse(fs.readFileSync(path.join(web, "messages", `${language}.json`), "utf8"));
const translators = vm.createContext({ Intl });
vm.runInContext(components.slice(components.indexOf("function translator("), components.indexOf("\nconst t = (() =>")), translators);
const tiles = source.slice(source.indexOf("function renderValuationTotals("), source.indexOf("function syncLocation("));
function contextFor(language) {
  const context = vm.createContext({ el: element, money: (n) => n == null ? "Prix indisponible" : `${n / 100} €`, t: translators.translator(dictionary(language), language) });
  vm.runInContext(tiles, context);
  return context;
}
const context = contextFor("fr");
const target = element("section");
context.renderValuationTotals(target, { copies: 2, trend_cents: 50000, trend_known: 1, trend_missing: 1, prudent_cents: 10000, prudent_known: 1, prudent_missing: 1, sale_estimate_cents: null, sale_estimate_known: 0, sale_estimate_missing: 2 });
assert.equal(target.children.length, 3);
assert.equal(target.children[1].children[1].text, "100 €");
assert.equal(target.children[0].children[2].text, "1/2 exemplaires · 1 sans prix");
assert.equal(target.children[1].children[2].text, "1/2 exemplaires · 1 sans valeur prudente");
// The sale estimate needs pasted offers: a copy with a trend still counts as lacking them.
assert.equal(target.children[2].children[2].text, "0/2 exemplaires · 2 sans offre collée");
assert.equal(target.children[2].children[1].text, "Prix indisponible");
// A refreshed empty result removes the previous amounts, without inventing zero.
context.renderValuationTotals(target, { copies: 0, trend_cents: null, trend_known: 0, trend_missing: 0, prudent_cents: null, prudent_known: 0, prudent_missing: 0, sale_estimate_cents: null, sale_estimate_known: 0, sale_estimate_missing: 0 });
assert.equal(target.children.length, 3);
assert(target.children.every((box) => box.children[1].text === "Prix indisponible"));
// The tooltip comes from the dictionary too.
context.renderValuationTotals(target, { copies: 1, bulk_copies: 1, trend_cents: null, trend_known: 0, trend_missing: 0, prudent_cents: null, prudent_known: 0, prudent_missing: 0, sale_estimate_cents: null, sale_estimate_known: 0, sale_estimate_missing: 0 });
assert.equal(target.children[0].children[0].text, "Tendance");
assert.equal(target.children[0].children[2].text, "0/1 exemplaire · 0 sans prix · 1 en vrac");
assert.match(target.children[2].title, /sans offre collée/);
// An English page gets English tiles.
const english = contextFor("en");
english.renderValuationTotals(target, { copies: 1721, bulk_copies: 131, trend_cents: 333561, trend_known: 1575, trend_missing: 15, prudent_cents: null, prudent_known: 0, prudent_missing: 1590, sale_estimate_cents: 14162, sale_estimate_known: 24, sale_estimate_missing: 1566 });
assert.equal(target.children[2].children[0].text, "Sale estimate");
assert.equal(target.children[0].children[2].text, "1,575/1,721 copies · 15 unpriced · 131 in bulk");
assert.equal(target.children[2].children[2].text, "24/1,721 copies · 1,566 without pasted offers · 131 in bulk");
