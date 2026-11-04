/* Service worker of the management app (/gestion), see docs/APP.md.
 *
 * The server fills in VERSION (a digest of the interface files) and PRECACHE,
 * so each deployment that changes the interface installs a new cache and
 * deletes the old one. Only the PRECACHE list is ever written to the cache:
 * /api, photos and every other request go to the network untouched, so no
 * price or customer data is kept on the phone.
 */
"use strict";

const VERSION = "{{version}}";
const PRECACHE = {{precache}};
const OFFLINE = "/gestion/hors-ligne";
const CACHE = "lilydex-gestion-" + VERSION;

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(PRECACHE.map((url) => new Request(url, { cache: "reload" }))))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) =>
        Promise.all(
          names.filter((name) => name.startsWith("lilydex-gestion-") && name !== CACHE).map((name) => caches.delete(name)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

// What the worker answers; null leaves the request to the browser and the network.
function strategy(request) {
  if (request.method !== "GET") return null;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return null;
  if (url.pathname.startsWith("/api/") || url.pathname === "/api") return null;
  if (request.mode === "navigate") return "page";
  if (PRECACHE.includes(url.pathname)) return "interface";
  return null;
}

self.addEventListener("fetch", (event) => {
  const kind = strategy(event.request);
  if (kind === "page") {
    // Network first: a page without the network has no data to show anyway.
    event.respondWith(fetch(event.request).catch(() => caches.match(OFFLINE, { cacheName: CACHE })));
  } else if (kind === "interface") {
    // Network first too, so a fresh page never runs with an older script;
    // the cached copy only serves when the network is down.
    event.respondWith(
      fetch(event.request).catch(() =>
        caches.match(new URL(event.request.url).pathname, { cacheName: CACHE }).then((hit) => hit || Response.error()),
      ),
    );
  }
});

// Web Push (V1 and later) adds its "push" and "notificationclick" listeners here.
