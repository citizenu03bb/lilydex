// Exercise the shared controller itself and the private viewer using that controller.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(tag = "div") {
    this.tagName = tag.toUpperCase(); this.children = []; this.listeners = new Map();
    this.style = { width: "" }; this.attributes = {}; this.dataset = {};
    this.className = ""; this.clientWidth = 200; this.clientHeight = 200;
    this.maxHeight = "200px"; this._left = this._top = 0;
    this.value = ""; this.min = this.max = this.step = "";
    this.naturalWidth = this.naturalHeight = 1000; this.captures = new Set();
    this.classList = {
      contains: (name) => this.className.split(/\s+/).includes(name),
      add: (...names) => { this.className = [...new Set([...this.className.split(/\s+/).filter(Boolean), ...names])].join(" "); },
      remove: (...names) => { this.className = this.className.split(/\s+/).filter(x => !names.includes(x)).join(" "); },
      toggle: (name, on) => { if (on ?? !this.classList.contains(name)) this.classList.add(name); else this.classList.remove(name); },
    };
  }
  addEventListener(name, listener) { if (!this.listeners.has(name)) this.listeners.set(name, new Set()); this.listeners.get(name).add(listener); }
  removeEventListener(name, listener) { this.listeners.get(name)?.delete(listener); }
  dispatch(name, properties = {}) {
    const event = { target: this, prevented: false, stopped: false,
      preventDefault() { this.prevented = true; }, stopPropagation() { this.stopped = true; }, ...properties };
    for (const listener of [...(this.listeners.get(name) || [])]) listener(event);
    return event;
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  append(...nodes) { this.children.push(...nodes); nodes.forEach(node => { node.parentNode = this; }); }
  replaceChildren(...nodes) { this.children.forEach(node => { node.parentNode = null; }); this.children = []; this.append(...nodes); }
  closest() { return null; }
  get isConnected() { return true; }
  focus() { this.focused = true; }
  showModal() { this.open = true; }
  close() { this.open = false; this.dispatch("close"); }
  setPointerCapture(id) { this.captures.add(id); }
  hasPointerCapture(id) { return this.captures.has(id); }
  releasePointerCapture(id) { this.captures.delete(id); }
  get scrollWidth() { return Math.max(this.clientWidth, ...this.children.map(c => Number.parseFloat(c.style.width) || 0)); }
  get scrollHeight() { return Math.max(this.clientHeight, ...this.children.map(c => (Number.parseFloat(c.style.width) || 0) * c.naturalHeight / c.naturalWidth)); }
  get scrollLeft() { return this._left; }
  set scrollLeft(value) { this._left = Math.min(Math.max(0, this.scrollWidth - this.clientWidth), Math.max(0, value)); }
  get scrollTop() { return this._top; }
  set scrollTop(value) { this._top = Math.min(Math.max(0, this.scrollHeight - this.clientHeight), Math.max(0, value)); }
  scrollTo(left, top) { this.scrollLeft = left; this.scrollTop = top; }
  scrollBy(left, top) { this.scrollTo(this.scrollLeft + left, this.scrollTop + top); }
}
const observers = [];
class ResizeObserver {
  constructor(callback) { this.callback = callback; observers.push(this); }
  observe(target) { this.target = target; }
  disconnect() { this.disconnected = true; }
  fire() { if (!this.disconnected) this.callback(); }
}
const context = vm.createContext({ window: {}, ResizeObserver,
  getComputedStyle: (element) => ({ maxHeight: element.maxHeight }),
  document: { createElement: (tag) => new Element(tag), querySelectorAll: () => [], body: new Element("body") },
  navigator: { userAgent: "Synthetic desktop", maxTouchPoints: 0 },
  MutationObserver: class { observe() {} },
});
context.window.addEventListener = () => {};
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), context);
context.PhotoZoom = context.window.PhotoZoom;
const mount = (options = {}) => {
  const frame = new Element(), image = new Element("img"), range = new Element("input"),
    output = new Element("output"), reset = new Element("button"), minus = new Element("button"), plus = new Element("button");
  frame.append(image);
  const changes = [];
  const controller = context.PhotoZoom.mount({ frame, image, range, output, reset, minus, plus,
    onChange: x => changes.push({ ...x }), formatPercent: n => `${n}% synthetic`, ...options });
  return { frame, image, range, output, reset, minus, plus, controller, changes, observer: observers.at(-1) };
};

const a = mount();
assert.equal(a.controller.zoom, 1);
assert.equal(a.image.style.width, "200px");
assert.equal(a.output.textContent, "100% synthetic");
assert.equal(a.range.getAttribute("aria-valuetext"), "100% synthetic");
assert.equal(a.output.getAttribute("aria-live"), "polite");
assert.equal(a.minus.disabled, true);
assert.equal(a.plus.disabled, false);
a.plus.dispatch("click");
assert.equal(a.controller.zoom, 1.25);
a.range.value = "2"; a.range.dispatch("input");
assert.equal(a.image.style.width, "400px");
assert.equal(a.frame.classList.contains("is-zoomed"), true);

// A focused zoom area owns panning keys; controls and browser shortcuts retain theirs.
for (const [key, left, top] of [["ArrowRight", 64, 0], ["ArrowDown", 64, 64]]) {
  const event = a.frame.dispatch("keydown", { key });
  assert.equal(event.prevented, true); assert.equal(event.stopped, true);
  assert.deepEqual([a.frame.scrollLeft, a.frame.scrollTop], [left, top]);
}
assert.equal(a.frame.dispatch("keydown", { key: "ArrowLeft", ctrlKey: true }).prevented, false);
assert.equal(a.frame.dispatch("keydown", { key: "ArrowLeft", target: a.range }).prevented, false);
a.frame.dispatch("keydown", { key: "End" });
assert.deepEqual([a.frame.scrollLeft, a.frame.scrollTop], [200, 200]);
a.frame.dispatch("keydown", { key: "Home" });
assert.deepEqual([a.frame.scrollLeft, a.frame.scrollTop], [0, 0]);

// The actual source proportion, the frame and its maximum height determine fitting.
a.image.naturalHeight = 2000; a.image.dispatch("load");
assert.equal(a.image.style.width, "200px");
a.controller.setZoom(4);
assert.equal(a.image.style.width, "400px");
assert.equal(a.plus.disabled, true);
a.frame.maxHeight = "100px"; a.observer.fire();
assert.equal(a.image.style.width, "200px");
a.frame.maxHeight = "none"; a.observer.fire();
assert.equal(a.image.style.width, "800px");
a.controller.setZoom(99); assert.equal(a.controller.zoom, 4);
a.controller.setZoom(-8); assert.equal(a.controller.zoom, 1);
a.controller.setZoom(NaN); assert.equal(a.controller.zoom, 1);
assert.equal(a.frame.dispatch("keydown", { key: "ArrowRight" }).stopped, false);

// Mouse capture pans and ends on cancellation; touch scrolling remains native.
a.controller.setZoom(3);
const touch = a.frame.dispatch("pointerdown", { pointerType: "touch", button: 0, pointerId: 2 });
assert.equal(touch.prevented, false); assert.equal(a.frame.captures.size, 0);
const down = a.frame.dispatch("pointerdown", { pointerType: "mouse", button: 0, pointerId: 7, clientX: 80, clientY: 80 });
assert.equal(down.prevented, true); assert.equal(a.frame.focused, true);
assert.equal(a.frame.hasPointerCapture(7), true);
a.frame.dispatch("pointermove", { pointerId: 7, clientX: 20, clientY: 10 });
assert.deepEqual([a.frame.scrollLeft, a.frame.scrollTop], [60, 70]);
a.frame.dispatch("pointercancel", { pointerId: 7 });
assert.equal(a.frame.captures.size, 0); assert.equal(a.frame.classList.contains("is-panning"), false);
a.frame.dispatch("pointermove", { pointerId: 7, clientX: 0, clientY: 0 });
assert.deepEqual([a.frame.scrollLeft, a.frame.scrollTop], [60, 70]);
a.reset.dispatch("click");
assert.deepEqual([a.controller.zoom, a.frame.scrollLeft, a.frame.scrollTop], [1, 0, 0]);

// Separate photo mounts have independent factors and lifetime.
const b = mount(); b.controller.setZoom(2);
assert.equal(a.controller.zoom, 1);
a.controller.setZoom(2);
a.frame.dispatch("pointerdown", { pointerType: "mouse", button: 0, pointerId: 9, clientX: 0, clientY: 0 });
const beforeDestroy = a.changes.length;
a.controller.destroy(); a.controller.destroy();
assert.equal(a.observer.disconnected, true); assert.equal(a.frame.captures.size, 0);
assert.equal(a.image.style.width, "");
assert.equal(a.frame.classList.contains("photo-zoom-frame"), false);
a.range.value = "4"; a.range.dispatch("input"); a.plus.dispatch("click"); a.observer.fire(); a.image.dispatch("load");
a.controller.setZoom(4);
assert.equal(a.changes.length, beforeDestroy);
for (const element of [a.frame, a.range, a.image, a.plus, a.minus, a.reset])
  assert.equal([...element.listeners.values()].reduce((n, listeners) => n + listeners.size, 0), 0);
b.controller.destroy();

// The private wrapper mounts the real common controller and disposes it on close.
vm.runInContext(fs.readFileSync(process.argv[3], "utf8") + "\nwindow.CardMediaForTest = CardMedia;", context);
const source = new Element("img"); source.src = "/synthetic-public.jpg"; source.alt = "Synthetic card";
const trigger = context.window.CardMediaForTest.zoomButton(source);
trigger.dispatch("click");
const dialog = context.document.body.children.at(-1);
assert.equal(dialog.open, true);
const gallery = dialog.children[1], figure = gallery.children[0], controls = figure.children[1],
  privateRange = controls.children[0].children[0], privateReset = controls.children[2],
  privateFrame = figure.children[3], privateImage = privateFrame.children[0];
privateRange.value = "2"; privateRange.dispatch("input");
assert.equal(privateImage.style.width, "400px");
privateReset.dispatch("click"); assert.equal(privateRange.value, "1");
dialog.close();
assert.equal(trigger.focused, true);
assert.equal(observers.at(-1).disconnected, true);
assert.equal(dialog.children.length, 0);
assert.equal([...privateFrame.listeners.values()].every(listeners => listeners.size === 0), true);
