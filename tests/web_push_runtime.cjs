// Runs the management app's service worker (as served) against a fake push event
// and fake windows: the notification has the app's icon, a tap opens /gestion.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[2], "utf8");
const ORIGIN = "https://cards.test";

const shown = [];
const opened = [];
let windows = [];
const listeners = {};
const self = {
  location: new URL(ORIGIN + "/gestion/sw.js"),
  addEventListener(type, fn) { listeners[type] = fn; },
  skipWaiting: async () => {},
  registration: { async showNotification(title, options) { shown.push({ title, options }); } },
  clients: {
    claim: async () => {},
    async matchAll(options) {
      assert.equal(options.type, "window");
      return windows;
    },
    async openWindow(url) { opened.push(url); return null; },
  },
};
const context = vm.createContext({ self, caches: {}, fetch: async () => ({}), Request: class {}, Response: {}, URL, Promise });
vm.runInContext(source, context);
assert.equal(typeof listeners.push, "function");
assert.equal(typeof listeners.notificationclick, "function");

async function push(data) {
  let done;
  listeners.push({
    data: data === undefined ? null : { json() { return JSON.parse(data); } },
    waitUntil(promise) { done = promise; },
  });
  await done;
  return shown.at(-1);
}

async function tap(notification) {
  let done;
  let closed = false;
  listeners.notificationclick({
    notification: { ...notification, close() { closed = true; } },
    waitUntil(promise) { done = promise; },
  });
  await done;
  assert(closed, "the notification closes on tap");
}

function windowAt(path, { navigable = true } = {}) {
  const win = {
    url: ORIGIN + path,
    focused: false,
    visited: [],
    async focus() { win.focused = true; return win; },
    async navigate(url) {
      if (!navigable) throw new TypeError("not controlled");
      win.visited.push(url);
      return win;
    },
  };
  return win;
}

(async () => {
  // The brief: title, short text, the app's icon, /gestion to open.
  const brief = await push(JSON.stringify({ title: "À toi : 2 choses, environ 5 min", body: "Fait : 3 annonce(s) publiée(s).", url: "/gestion" }));
  assert.equal(brief.title, "À toi : 2 choses, environ 5 min");
  assert.equal(brief.options.body, "Fait : 3 annonce(s) publiée(s).");
  assert.equal(brief.options.icon, "/assets/icon-192.png");
  assert.equal(brief.options.data.url, ORIGIN + "/gestion");

  // An alert keeps the view concerned.
  const alert = await push(JSON.stringify({ title: "Nouvelle demande : 1 carte, 1,20 €", body: "Accepter ou refuser", url: "/gestion?demande=abc" }));
  assert.equal(alert.options.data.url, ORIGIN + "/gestion?demande=abc");

  // A URL outside the management, or none, or an unreadable payload, opens /gestion.
  for (const url of ["https://evil.test/gestion", "/", "/vitrine", "javascript:alert(1)", undefined]) {
    const other = await push(JSON.stringify({ title: "T", body: "B", url }));
    assert.equal(other.options.data.url, ORIGIN + "/gestion", String(url));
  }
  const empty = await push(undefined);
  assert(empty.title.length > 0);
  assert.equal(empty.options.data.url, ORIGIN + "/gestion");
  listeners.push({ data: { json() { throw new SyntaxError("bad"); } }, waitUntil(p) { p.catch(() => {}); } });

  // No window: one opens at the URL.
  await tap(alert.options);
  assert.deepEqual(opened, [ORIGIN + "/gestion?demande=abc"]);

  // The app already open comes to the front and moves to the URL; the storefront tab is left alone.
  const storefront = windowAt("/");
  const app = windowAt("/gestion?view=sales");
  windows = [storefront, app];
  await tap(alert.options);
  assert(app.focused && !storefront.focused);
  assert.deepEqual(app.visited, [ORIGIN + "/gestion?demande=abc"]);
  assert.equal(opened.length, 1);

  // A window that cannot be navigated: a new one opens instead.
  windows = [windowAt("/gestion", { navigable: false })];
  await tap(brief.options);
  assert.deepEqual(opened, [ORIGIN + "/gestion?demande=abc", ORIGIN + "/gestion"]);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
