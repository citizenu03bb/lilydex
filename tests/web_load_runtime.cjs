// Loads the management scripts in one context, in the order given on the
// command line (the order of the index.html script tags), against a stub DOM.
// Any load-time error (a top-level reference to a function defined in a later
// script, a syntax error, a strict-mode violation) fails the run. Network
// calls never resolve: only what runs while the scripts load is exercised.
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const scripts = process.argv.slice(2);
const web = path.dirname(scripts[0]);
const messages = fs.readFileSync(path.join(web, "messages", "fr.json"), "utf8");

// One object that answers every property, call and construction with itself:
// enough for code that wires listeners and reads attributes at load time.
function stub(name) {
  const target = function () {};
  const known = new Map();
  const proxy = new Proxy(target, {
    get(_, key) {
      if (key === Symbol.toPrimitive) return () => "";
      if (key === Symbol.iterator) return function* () {};
      if (key === "then") return undefined; // never a thenable
      if (key === "length" || key === "size" || key === "childElementCount") return 0;
      if (key === "toString" || key === "valueOf") return () => "";
      if (key === "textContent" || key === "value" || key === "innerHTML") return "";
      if (key === "dataset" || key === "style") {
        if (!known.has(key)) known.set(key, {});
        return known.get(key);
      }
      if (typeof key === "string" && /^(matches|contains|hasAttribute|checked|disabled|hidden|open)$/.test(key)) {
        return key === "matches" || key === "contains" || key === "hasAttribute" ? () => false : false;
      }
      if (typeof key === "string" && /^(querySelectorAll|getElementsBy\w+)$/.test(key)) return () => [];
      if (key === "getAttribute") return () => null;
      if (key === "closest" || key === "querySelector") return () => null;
      if (!known.has(key)) known.set(key, stub(`${name}.${String(key)}`));
      return known.get(key);
    },
    set(_, key, value) {
      known.set(key, value);
      return true;
    },
    apply() {
      return stub(`${name}()`);
    },
    construct() {
      return stub(`new ${name}`);
    },
  });
  return proxy;
}

const elements = new Map();
const document = stub("document");
document.documentElement = stub("documentElement");
document.documentElement.lang = "fr";
document.getElementById = (id) => {
  if (id === "messages") return { textContent: messages };
  if (!elements.has(id)) elements.set(id, stub(`#${id}`));
  return elements.get(id);
};
document.querySelector = (selector) => document.getElementById(`query:${selector}`);
document.querySelectorAll = () => [];
document.createElement = (tag) => stub(`<${tag}>`);
document.readyState = "loading";

const never = () => new Promise(() => {});
const storage = () => {
  const values = new Map();
  return {
    getItem: (key) => (values.has(key) ? values.get(key) : null),
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
    clear: () => values.clear(),
  };
};
const timers = [];
const context = {
  console,
  document,
  navigator: { userAgent: "stub", language: "fr", onLine: true, serviceWorker: undefined },
  location: {
    href: "http://testserver/gestion", origin: "http://testserver", protocol: "http:",
    host: "testserver", hostname: "testserver", pathname: "/gestion", search: "", hash: "",
    assign() {}, replace() {}, reload() {},
  },
  history: { state: null, pushState() {}, replaceState() {}, back() {} },
  localStorage: storage(),
  sessionStorage: storage(),
  fetch: never,
  setTimeout: (fn) => timers.push(fn),
  clearTimeout() {},
  setInterval: () => 0,
  clearInterval() {},
  requestAnimationFrame: () => 0,
  cancelAnimationFrame() {},
  queueMicrotask,
  matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
  getComputedStyle: () => stub("style"),
  addEventListener() {},
  removeEventListener() {},
  dispatchEvent() {},
  customElements: { define() {}, get() {}, whenDefined: never },
  HTMLElement: class {},
  Event: class { constructor(type) { this.type = type; } },
  CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init?.detail; } },
  MutationObserver: class { observe() {} disconnect() {} },
  IntersectionObserver: class { observe() {} unobserve() {} disconnect() {} },
  ResizeObserver: class { observe() {} unobserve() {} disconnect() {} },
  AbortController,
  URL,
  URLSearchParams,
  FormData: class { append() {} },
  Blob,
  TextEncoder,
  TextDecoder,
  structuredClone,
  crypto: { randomUUID: () => "00000000-0000-4000-8000-000000000000" },
  Image: class {},
};
context.window = context;
context.self = context;
context.globalThis = context;
vm.createContext(context);

for (const file of scripts) {
  const source = fs.readFileSync(file, "utf8");
  try {
    new vm.Script(source, { filename: path.basename(file) }).runInContext(context);
  } catch (error) {
    console.error(`${path.basename(file)} failed to load: ${error && error.stack || error}`);
    process.exit(1);
  }
}
console.log(`loaded ${scripts.length} scripts`);
