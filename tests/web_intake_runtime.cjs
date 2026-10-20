// Exercise the Gemini-assisted identification of the add dialog without a browser.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[2], "utf8");
const intakeSource = source.slice(
  source.indexOf("const intakeNumberKey ="),
  source.indexOf("// Editing the entry keeps the chosen edition"),
);

function element(tag = "div") {
  const node = {
    tag,
    value: "",
    checked: false,
    hidden: false,
    textContent: "",
    children: [],
    listeners: {},
    selected: false,
    classList: {
      add() {
        node.selected = true;
      },
      remove() {
        node.selected = false;
      },
    },
    append(...children) {
      this.children.push(...children);
    },
    replaceChildren() {
      this.children = [];
    },
    setAttribute() {},
    addEventListener(event, handler) {
      (this.listeners[event] ||= []).push(handler);
    },
    click() {
      for (const handler of this.listeners.click || []) handler();
    },
    querySelectorAll() {
      return [];
    },
  };
  return node;
}
const controls = new Map();
const $ = (id) => {
  if (!controls.has(id)) controls.set(id, element());
  return controls.get(id);
};
const keys = ["name", "number", "set_name", "language", "hp"];
const form = $("add-form");
form.elements = Object.fromEntries(keys.map((key) => [key, element()]));
const intakeState = { chosen: null, hasPhoto: false };
let zooms = 0;
const context = vm.createContext({
  $,
  intakeState,
  el: (tag, text) => Object.assign(element(tag), { textContent: text ?? "" }),
  clearIntakeChoice() {
    intakeState.chosen = null;
    $("intake-confirm").checked = false;
    $("intake-confirm-label").hidden = true;
  },
  CardMedia: {
    zoomButton(image) {
      const button = element("button");
      button.append(image);
      button.addEventListener("click", () => zooms++);
      return button;
    },
  },
});
vm.runInContext(intakeSource, context);
const run = (code, values) => vm.runInContext(code, Object.assign(context, values));

// 1. A blank or unknown reading keeps what the copy already records.
const elektek = {
  name: "Elektek NIV.32",
  number: "87/132",
  language: "fr",
  hp: "70",
  set_name: "Merveilles Secrètes",
  stamp: "",
  stamp_state: "absent",
  notes: "Classeur bleu",
};
let reading = run("intakeReading(current, observation)", {
  current: elektek,
  observation: {
    name: "Elektek NIV.32",
    number: "",
    language: "unknown",
    hp: null,
    flaws: "",
    notes: "",
    stamp_text: "",
  },
});
assert.equal(reading.number, "87/132");
assert.equal(reading.language, "fr");
assert.equal(reading.hp, "70");
assert.equal(reading.set_name, "Merveilles Secrètes");
assert.equal(reading.stamp_state, "absent");
assert.equal(reading.notes, "Classeur bleu");
// A new reference invalidates the extension; a read stamp reopens "absent".
reading = run("intakeReading(current, observation)", {
  current: elektek,
  observation: {
    name: "Elektek",
    number: "087/132",
    language: "fr",
    hp: 70,
    flaws: "",
    notes: "",
    stamp_text: "",
  },
});
assert.equal(reading.set_name, "Merveilles Secrètes"); // Same reference, other zeros.
reading = run("intakeReading(current, observation)", {
  current: elektek,
  observation: {
    name: "Elektek",
    number: "88/132",
    language: "fr",
    hp: 70,
    flaws: "",
    notes: "",
    stamp_text: "Prerelease",
  },
});
assert.equal(reading.number, "88/132");
assert.equal(reading.set_name, "");
assert.equal(reading.stamp, "Prerelease");
assert.equal(reading.stamp_state, "unobserved");

// 3. Notes and flaws join the notes, without erasing or repeating them.
const observation = {
  name: "Elektek",
  number: "87/132",
  language: "fr",
  hp: 70,
  flaws: "Pliure au coin supérieur",
  notes: "Code d’énergie inhabituel",
  stamp_text: "",
};
reading = run("intakeReading(current, observation)", {
  current: elektek,
  observation,
});
assert.equal(
  reading.notes,
  "Classeur bleu\nLecture Gemini : Code d’énergie inhabituel\nDéfauts visibles (lecture Gemini) : Pliure au coin supérieur",
);
assert.equal(
  run("intakeNotes(notes, observation)", { notes: reading.notes, observation }),
  reading.notes,
);
assert.equal(
  run("intakeNotes('', observation)", {
    observation: { ...observation, notes: "  " },
  }),
  "Défauts visibles (lecture Gemini) : Pliure au coin supérieur",
);

// 2. A single exact edition is preselected, without confirming it.
const candidate = {
  id: "pl2-72",
  name: "Nidoran♂",
  printed_name: "Nidoran♂ NIV.9",
  printed_number: "72/111",
  set_name: "Rivaux Émergeants",
  number: "72/111",
  language: "fr",
  hp: null,
  image: "https://assets.tcgdex.net/fr/pl/pl2/72/low.webp",
};
Object.assign(form.elements.name, { value: "Nidoran♂ NIV.9" });
Object.assign(form.elements.number, { value: "72/111" });
Object.assign(form.elements.language, { value: "fr" });
Object.assign(form.elements.hp, { value: "50" });
run("showIntakeCandidates(result)", {
  result: { candidates: [candidate], exact: true, message: "Comparez." },
});
assert.equal(intakeState.chosen, "pl2-72");
assert.equal(form.elements.set_name.value, "Rivaux Émergeants");
assert.equal(form.elements.hp.value, "50"); // The catalogue lacks it: kept.
assert.equal($("intake-confirm").checked, false);
assert.equal($("intake-confirm-label").hidden, false);
assert.equal(zooms, 0);

// Without an exact match nothing is chosen; enlarging an illustration chooses it.
form.elements.set_name.value = "";
const other = { ...candidate, id: "pl2-73", set_name: "Autre", number: "73/111" };
run("showIntakeCandidates(result)", {
  result: { candidates: [candidate, other], exact: false, message: "Comparez." },
});
assert.equal(intakeState.chosen, null);
assert.equal(form.elements.set_name.value, "");
const [, second] = $("intake-candidates").children;
const [zoom, button] = second.children;
zoom.click();
assert.equal(zooms, 1);
assert.equal(intakeState.chosen, "pl2-73");
assert.equal(form.elements.set_name.value, "Autre");
assert.ok(button.selected);
console.log("Intake identification checks passed");
