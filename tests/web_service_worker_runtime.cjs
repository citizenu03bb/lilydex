// Runs the management app's service worker (as served, version filled in) against
// fake caches and network: only the shell is cached, /api and photos never are.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[2], "utf8");
const ORIGIN = "https://cards.test";

const stores = new Map([["lilydex-gestion-old", new Map()], ["other-site-cache", new Map()]]);
const writes = [];
const caches = {
  async open(name) {
    if (!stores.has(name)) stores.set(name, new Map());
    const store = stores.get(name);
    return {
      async addAll(requests) {
        for (const request of requests) {
          assert.equal(request.cache, "reload");
          const path = new URL(request.url, ORIGIN).pathname;
          writes.push(path);
          store.set(path, { body: "cached " + path });
        }
      },
      async put(request) {
        writes.push(String(request.url || request));
        throw new Error("the worker never puts a response in its cache");
      },
    };
  },
  async keys() { return [...stores.keys()]; },
  async delete(name) { return stores.delete(name); },
  async match(key, options) {
    const path = new URL(String(key), ORIGIN).pathname;
    return stores.get(options.cacheName)?.get(path);
  },
};

let online = true;
const network = [];
async function fetch(request) {
  network.push(request.url);
  if (!online) throw new TypeError("Failed to fetch");
  return { body: "network " + new URL(request.url).pathname };
}

const listeners = {};
const self = {
  location: new URL(ORIGIN + "/gestion/sw.js"),
  addEventListener(type, fn) { listeners[type] = fn; },
  skipWaiting: async () => {},
  clients: { claim: async () => {} },
};
class FakeRequest {
  constructor(url, init = {}) { this.url = new URL(url, ORIGIN).href; this.cache = init.cache; this.method = init.method || "GET"; this.mode = init.mode || "cors"; }
}
const context = vm.createContext({ self, caches, fetch, Request: FakeRequest, Response: { error: () => ({ error: true }) }, URL, Promise });
vm.runInContext(source, context);

const versionMatch = source.match(/const VERSION = "([0-9a-f]{16})";/);
assert(versionMatch, "the server fills in a content version");
const CACHE = "lilydex-gestion-" + versionMatch[1];

async function lifecycle(type) {
  let done;
  listeners[type]({ waitUntil(promise) { done = promise; } });
  await done;
}

function dispatch(url, init = {}) {
  let answer = null;
  listeners.fetch({ request: new FakeRequest(url, init), respondWith(promise) { answer = promise; } });
  return answer;
}

(async () => {
  await lifecycle("install");
  assert(stores.has(CACHE));
  assert(writes.includes("/gestion/hors-ligne"));
  assert(writes.includes("/assets/app.js"));
  assert(writes.every((path) => !path.startsWith("/api")), writes.join(","));

  await lifecycle("activate");
  assert(!stores.has("lilydex-gestion-old"), "the previous version is deleted");
  assert(stores.has("other-site-cache"), "a cache the app does not own stays");

  // /api, photos and writes are never answered by the worker: the browser fetches them.
  for (const url of ["/api/copies", "/api/copies/12/photo", "/api/public/listings/3/photo?format=webp",
                     "/api/todo", "/api/photo-batches/4/photo/7/front", "/api"]) {
    assert.equal(dispatch(url), null, url);
    assert.equal(dispatch(url, { mode: "navigate" }), null, url);
  }
  assert.equal(dispatch("/gestion", { method: "POST", mode: "navigate" }), null);
  assert.equal(dispatch("https://assets.tcgdex.net/fr/swsh/swsh1/1/high.webp"), null);
  assert.equal(dispatch("/assets/storefront.js"), null, "the storefront is not the app's business");

  // Online, pages and interface files come from the network.
  assert.equal((await dispatch("/gestion", { mode: "navigate" })).body, "network /gestion");
  assert.equal((await dispatch("/assets/app.js")).body, "network /assets/app.js");

  // Offline, a page becomes the offline page and the interface comes from the cache.
  online = false;
  assert.equal((await dispatch("/gestion?view=sales", { mode: "navigate" })).body, "cached /gestion/hors-ligne");
  assert.equal((await dispatch("/assets/style.css")).body, "cached /assets/style.css");

  const installed = writes.length;
  await dispatch("/gestion", { mode: "navigate" });
  assert.equal(writes.length, installed, "browsing writes nothing to the cache");
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
