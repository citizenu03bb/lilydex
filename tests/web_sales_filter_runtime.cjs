const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[2], "utf8");

function node(tag = "div", text, className) {
  return {
    tag,
    textContent: text ?? "",
    className: className ?? "",
    dataset: {},
    children: [],
    append(...items) {
      this.children.push(...items);
    },
    replaceChildren(...items) {
      this.children = [...items];
    },
    setAttribute() {},
    addEventListener(event, handler) {
      this[event] = handler;
    },
  };
}

let salesResponse = [];
const controls = {
  "sales-filter": { value: "active", addEventListener(e, h) { this[e] = h; } },
  "sales-count": node("p"),
  "sales-list": node("div"),
};

const context = vm.createContext({
  $: (id) => controls[id],
  el: node,
  field: (parent, name, label, value) => {
    const input = node("input", label);
    input.name = name;
    input.value = value;
    parent.append(input);
    return input;
  },
  document: { createTextNode: (text) => ({ tag: "#text", textContent: text }) },
  editAllowed: () => true,
  money: (cents) => `${(cents / 100).toFixed(2)} €`,
  saleLabels: {
    draft: "Brouillon",
    reserved: "Réservée",
    sold: "Vendue",
    shipped: "Expédiée",
    completed: "Terminée",
    cancelled: "Annulée",
    returned: "Retour",
  },
  loadRequests: async () => {},
  api: async (path) => {
    assert.equal(path, "/sales");
    return salesResponse;
  },
  toast: () => {},
});

vm.runInContext(
  source.slice(
    source.indexOf("function matchesSalesFilter("),
    source.indexOf("async function loadUsers("),
  ),
  context,
);

(async () => {
  // 1. Two cancelled test lots only: default "active" filter hides them cleanly.
  salesResponse = [
    {
      id: "lot-1",
      title: "Test constitution lot",
      status: "cancelled",
      amount_cents: 5000,
      net_cents: 5000,
      items: [{ id: "c1", name: "Pikachu", number: "1/102" }],
    },
    {
      id: "lot-2",
      title: "Test lot kiky",
      status: "cancelled",
      amount_cents: 5000,
      net_cents: 5000,
      items: [{ id: "c2", name: "Évoli", number: "2/102" }],
    },
  ];
  await context.loadSales();
  assert.equal(controls["sales-count"].textContent, "0 lot affiché · 2 annulés masqués");
  assert.equal(controls["sales-list"].children.length, 1);
  assert.equal(controls["sales-list"].children[0].className, "empty");
  assert(
    controls["sales-list"].children[0].textContent.includes(
      "Aucun lot actif pour le moment.",
    ),
  );

  // 2. Selecting "cancelled" displays the 2 cancelled lots with their form collapsed in <details>.
  controls["sales-filter"].value = "cancelled";
  await context.loadSales();
  assert.equal(controls["sales-count"].textContent, "2 lots affichés");
  assert.equal(controls["sales-list"].children.length, 2);
  assert(
    controls["sales-list"].children[0].children.some((c) => c.tag === "details"),
    "Cancelled lot edit form should be collapsed inside <details>",
  );

  // 3. Mixed statuses filter accurately across draft, reserved, sold, and active.
  salesResponse.push(
    {
      id: "lot-draft",
      title: "Lot brouillon",
      status: "draft",
      amount_cents: 1200,
      net_cents: 1200,
      items: [],
    },
    {
      id: "lot-shipped",
      title: "Lot expédié",
      status: "shipped",
      amount_cents: 2500,
      net_cents: 2200,
      items: [],
    },
  );
  controls["sales-filter"].value = "active";
  await context.loadSales();
  assert.equal(controls["sales-count"].textContent, "2 lots affichés · 2 annulés masqués");
  assert.equal(controls["sales-list"].children.length, 2);

  controls["sales-filter"].value = "draft";
  await context.loadSales();
  assert.equal(controls["sales-list"].children.length, 1);

  controls["sales-filter"].value = "sold";
  await context.loadSales();
  assert.equal(controls["sales-list"].children.length, 1);

  controls["sales-filter"].value = "reserved";
  await context.loadSales();
  assert.equal(controls["sales-list"].children.length, 1);
  assert.equal(controls["sales-list"].children[0].textContent, "Aucun lot dans ce statut.");

  controls["sales-filter"].value = "all";
  await context.loadSales();
  assert.equal(controls["sales-list"].children.length, 4);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
