// Exercise the W3C theme/filter helpers, viewer quick-exam payload, and CSP invariants.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const componentsPath = process.argv[2];
const galleryPath = process.argv[3];
const webDir = path.dirname(componentsPath);

const componentsSource = fs.readFileSync(componentsPath, "utf8");
const context = vm.createContext({
  localStorage: {
    store: new Map(),
    getItem(k) {
      return this.store.has(k) ? this.store.get(k) : null;
    },
    setItem(k, v) {
      this.store.set(k, String(v));
    },
    removeItem(k) {
      this.store.delete(k);
    },
  },
});
vm.runInContext(
  componentsSource.slice(
    componentsSource.indexOf("function resolveLilydexTheme("),
    componentsSource.indexOf("// W3C Custom Elements registration"),
  ),
  context,
);

// 1. Theme resolution respects prefers-color-scheme by default and explicit choices when set.
assert.equal(context.resolveLilydexTheme(null, false), "herbier");
assert.equal(context.resolveLilydexTheme(null, true), "vault");
assert.equal(context.resolveLilydexTheme("auto", true), "vault");
assert.equal(context.resolveLilydexTheme("auto", false), "herbier");
assert.equal(context.resolveLilydexTheme("atelier", true), "atelier");
assert.equal(context.resolveLilydexTheme("herbier", true), "herbier");
assert.equal(context.resolveLilydexTheme("vault", false), "vault");
assert.equal(context.resolveLilydexTheme("invalid-theme", true), "vault");

const fakeMeta = { content: "light" };
const fakeDoc = {
  documentElement: { dataset: {} },
  querySelector(sel) {
    return sel === 'meta[name="color-scheme"]' ? fakeMeta : null;
  },
};
context.applyLilydexTheme(fakeDoc, "auto", true);
assert.equal(fakeDoc.documentElement.dataset.theme, "vault");
assert.equal(fakeDoc.documentElement.dataset.themeMode, "auto");
assert.equal(fakeMeta.content, "dark");

context.applyLilydexTheme(fakeDoc, "atelier", true);
assert.equal(fakeDoc.documentElement.dataset.theme, "atelier");
assert.equal(fakeDoc.documentElement.dataset.themeMode, "atelier");
assert.equal(fakeMeta.content, "light");

// The shared picker exposes a radio group, one checked choice and one tab stop.
// Exercise the actual element: a radio never receives the button-only pressed state.
let focusedChoice;
class PickerNode {
  constructor(tag = "lilydex-theme-picker") {
    this.tagName = tag;
    this.children = [];
    this.dataset = {};
    this.attributes = {};
    this.events = {};
  }
  setAttribute(name, value) { this.attributes[name] = value; }
  getAttribute(name) { return this.attributes[name] ?? null; }
  addEventListener(name, handler) { this.events[name] = handler; }
  append(child) { this.children.push(child); }
  replaceChildren(...children) { this.children = children; }
  querySelector(selector) {
    return selector === ".theme-picker"
      ? this.children.find(child => child.className === "theme-picker") || null
      : null;
  }
  querySelectorAll(selector) {
    return this.children.flatMap(child => [
      ...(selector === "button[data-theme-choice]" && child.dataset.themeChoice ? [child] : []),
      ...child.querySelectorAll(selector),
    ]);
  }
  focus() { focusedChoice = this.dataset.themeChoice; }
}
let picker;
const pickerContext = vm.createContext({
  HTMLElement: PickerNode,
  document: { createElement: tag => new PickerNode(tag) },
  LILYDEX_THEMES: ["auto", "herbier", "vault", "atelier"],
  t: key => key,
  readStoredTheme: () => "auto",
  setLilydexTheme: mode => picker.sync(mode),
});
vm.runInContext(
  componentsSource.slice(
    componentsSource.indexOf("      class LilydexThemePicker"),
    componentsSource.indexOf('      customElements.define("lilydex-theme-picker"'),
  ) + "\nglobalThis.Picker = LilydexThemePicker;",
  pickerContext,
);
picker = new pickerContext.Picker();
picker.connectedCallback();
const radioChoices = picker.querySelectorAll("button[data-theme-choice]");
assert.equal(radioChoices.length, 4);
function checkPickerState(expected) {
  assert.equal(picker.children[0].getAttribute("role"), "radiogroup");
  for (const button of radioChoices) {
    const selected = button.dataset.themeChoice === expected;
    assert.equal(button.getAttribute("role"), "radio");
    assert.equal(button.getAttribute("aria-checked"), String(selected));
    assert.equal(button.getAttribute("aria-pressed"), null);
    assert.equal(button.tabIndex, selected ? 0 : -1);
  }
}
checkPickerState("auto");
for (const mode of ["herbier", "vault", "atelier", "auto"]) {
  picker.sync(mode);
  checkPickerState(mode);
}
radioChoices[2].events.click();
checkPickerState("vault");
let keyPrevented = false;
picker.children[0].events.keydown({ key: "ArrowRight", preventDefault() { keyPrevented = true; } });
assert.equal(keyPrevented, true);
checkPickerState("atelier");
assert.equal(focusedChoice, "atelier");
picker.children[0].events.keydown({ key: "ArrowRight", preventDefault() {} });
checkPickerState("auto");
assert.equal(focusedChoice, "auto");
picker.children[0].events.keydown({ key: "ArrowLeft", preventDefault() {} });
checkPickerState("atelier");
assert.equal(focusedChoice, "atelier");
picker.connectedCallback();
assert.equal(picker.children.length, 1, "reconnecting reuses the existing radio group");
checkPickerState("auto");

// 2. Active filter chips only list non-default filters.
const chips = context.activeFilterChips({
  album: { value: "a1", label: "Classeur Pikachu" },
  stock: { value: "available", label: "Disponibles" },
  status: { value: "", label: "Toutes les identités" },
  variant: { value: "check", label: "Foil à vérifier" },
  review: { value: "needed", label: "À examiner" },
  threshold: { value: "10", defaultValue: "10" },
});
assert.deepEqual(
  Array.from(chips.map((c) => c.key)),
  ["album", "stock", "variant", "review"],
);

// 3. Viewer quick-exam payload sends only modified fields + expected_version, never inventing confirmations.
const gallerySource = fs.readFileSync(galleryPath, "utf8");
const galleryContext = vm.createContext({});
vm.runInContext(
  gallerySource.slice(
    gallerySource.indexOf("  function viewerExamPayload("),
    gallerySource.indexOf("  const panels ="),
  ),
  galleryContext,
);

const baseCard = {
  id: "copy-1",
  version: 7,
  finish: "",
  stamp_state: "unobserved",
  stamp: "",
  condition: "",
  variant_confirmed: false,
  condition_confirmed: false,
};

const unchanged = galleryContext.viewerExamPayload(baseCard, {
  finish: "",
  stamp_state: "unobserved",
  stamp: "",
  condition: "",
  variant_confirmed: false,
  condition_confirmed: false,
  reason: "Examen rapide en visionneuse",
});
assert.equal(unchanged, null, "nothing changed -> no PATCH sent");

const partialPatch = galleryContext.viewerExamPayload(baseCard, {
  finish: "reverse",
  stamp_state: "absent",
  stamp: "",
  condition: "NM",
  variant_confirmed: true,
  condition_confirmed: false,
  reason: "Examen en classeur",
});
assert.deepEqual(
  JSON.parse(JSON.stringify(partialPatch)),
  {
    expected_version: 7,
    reason: "Examen en classeur",
    finish: "reverse",
    stamp_state: "absent",
    condition: "NM",
    variant_confirmed: true,
  },
);

// 3b. Viewer index after save advances when card stays in filter, or stays at previousIndex when filtered out.
assert.equal(
  galleryContext.nextViewerIndexAfterSave(["c1", "c2", "c3"], "c1", 0),
  1,
  "when saved card remains in list, advance to next card",
);
assert.equal(
  galleryContext.nextViewerIndexAfterSave(["c2", "c3"], "c1", 0),
  0,
  "when saved card is removed by active filter (e.g. review=needed), stay at previous index",
);
assert.equal(
  galleryContext.nextViewerIndexAfterSave(["c2"], "c3", 1),
  0,
  "when saved last card is removed by filter, clamp to last remaining index",
);

// 3c. Viewer draftFor preserves unsaved edits per id:version and resets on version bump.
vm.runInContext(
  gallerySource.slice(
    gallerySource.indexOf("  const drafts = new Map();"),
    gallerySource.indexOf("  function renderExamForm("),
  ),
  galleryContext,
);
const draftV7 = galleryContext.draftFor(baseCard);
draftV7.condition = "EX";
assert.equal(
  galleryContext.draftFor(baseCard).condition,
  "EX",
  "unsaved draft persists across re-renders (e.g. R flip) at same version",
);
assert.equal(
  galleryContext.draftFor({ ...baseCard, version: 8 }).condition,
  "",
  "version bump creates a fresh draft from updated card state",
);

// 4. Static HTML CSP & W3C invariants across index.html, storefront.html, about.html.
for (const file of ["index.html", "storefront.html", "about.html"]) {
  const html = fs.readFileSync(path.join(webDir, file), "utf8");
  assert.ok(!/\sstyle\s*=/i.test(html), `${file} must not contain inline style attributes`);
  assert.ok(!/<script(?![^>]*\bsrc=)[^>]*>/i.test(html), `${file} must not contain inline scripts`);
  assert.ok(html.includes("/assets/themes.css"), `${file} must load /assets/themes.css`);
  assert.ok(html.includes("/assets/components.js"), `${file} must load /assets/components.js`);
  assert.ok(html.includes("<lilydex-theme-picker"), `${file} must include <lilydex-theme-picker>`);
}
