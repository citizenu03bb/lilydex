// Runs pwa.js against a fake page, browser and server: the « Notifications sur ce
// téléphone » switch asks permission only on the user's gesture, explains the
// iPhone install, and keeps the server's subscription in step with the browser's.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[2], "utf8");
const messages = JSON.parse(fs.readFileSync(0, "utf8"));
const t = (key) => messages[key] ?? key;

const KEY_BYTES = Uint8Array.from([4, ...Array.from({ length: 64 }, (_, i) => (i * 7 + 3) % 256)]);
const KEY = Buffer.from(KEY_BYTES).toString("base64url");

function boot({ apple = false, standalone = false, permission = "default", answer = "granted", enabled = true } = {}) {
  const elements = {};
  const element = (id) =>
    (elements[id] ||= {
      id, checked: false, disabled: true, textContent: "", hidden: false, listeners: {},
      addEventListener(type, fn) { this.listeners[type] = fn; },
    });
  for (const id of ["push-toggle", "push-status"]) element(id);
  const document = { getElementById: (id) => elements[id] || null };
  const calls = { permission: 0, subscribe: [], requests: [], unsubscribed: 0 };
  const server = new Set();
  let subscription = null;
  const pushManager = {
    async getSubscription() { return subscription; },
    async subscribe(options) {
      calls.subscribe.push(options);
      subscription = {
        endpoint: "https://fcm.googleapis.com/fcm/send/phone-" + calls.subscribe.length,
        options: { applicationServerKey: options.applicationServerKey.buffer },
        toJSON() { return { endpoint: this.endpoint, expirationTime: null, keys: { p256dh: "p", auth: "a" } }; },
        async unsubscribe() { calls.unsubscribed++; subscription = null; return true; },
      };
      return subscription;
    },
  };
  const Notification = {
    permission,
    async requestPermission() { calls.permission++; Notification.permission = answer; return answer; },
  };
  const navigator = {
    userAgent: apple ? "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)" : "Mozilla/5.0 (Linux; Android 15)",
    platform: apple ? "iPhone" : "Linux armv8l",
    maxTouchPoints: 5,
    standalone: apple ? standalone : undefined,
    serviceWorker: { ready: Promise.resolve({ pushManager }), register: async () => ({}) },
  };
  async function fetch(url, init = {}) {
    const body = init.body ? JSON.parse(init.body) : null;
    calls.requests.push({ url, method: init.method, body });
    let result;
    if (url === "/api/push") result = { enabled, public_key: enabled ? KEY : null };
    else if (url === "/api/push/subscriptions" && init.method === "POST") { server.add(body.endpoint); result = { subscribed: true }; }
    else if (url === "/api/push/subscriptions" && init.method === "DELETE") result = { removed: server.delete(body.endpoint) };
    else if (url === "/api/push/subscriptions/check") result = { subscribed: server.has(body.endpoint) };
    else throw new Error("unexpected " + url);
    return { ok: true, status: 200, json: async () => result };
  }
  const window = {
    isSecureContext: true,
    navigator,
    Notification,
    PushManager: function PushManager() {},
    fetch,
    matchMedia: (query) => ({ matches: !apple && standalone && query.includes("standalone") }),
    addEventListener() {},
  };
  const context = vm.createContext({ window, document, navigator, t, atob, Uint8Array, URL, Promise, JSON });
  vm.runInContext(source, context);
  const toggle = elements["push-toggle"];
  return {
    toggle, status: elements["push-status"], calls, server,
    refresh: () => window.lilydexPush.refresh(),
    async flip(checked) {
      toggle.checked = checked;
      await toggle.listeners.change();
      for (let i = 0; i < 20; i++) await new Promise((resolve) => setImmediate(resolve));
    },
  };
}

(async () => {
  // iPhone in Safari: install first; nothing is asked of the browser or the server.
  const safari = boot({ apple: true });
  await safari.refresh();
  assert.equal(safari.toggle.disabled, true);
  assert.equal(safari.status.textContent, messages["push.install_first"]);
  assert.equal(safari.calls.permission, 0);
  assert.equal(safari.calls.requests.length, 0);

  // Android, or the installed iPhone app: the switch is offered, no permission asked yet.
  for (const options of [{}, { apple: true, standalone: true }]) {
    const phone = boot(options);
    await phone.refresh();
    assert.equal(phone.toggle.disabled, false);
    assert.equal(phone.toggle.checked, false);
    assert.equal(phone.calls.permission, 0, "opening the settings never asks for permission");

    // The gesture: permission, subscription with the server's key, then the server.
    await phone.flip(true);
    assert.equal(phone.calls.permission, 1);
    assert.equal(phone.calls.subscribe.length, 1);
    assert.equal(phone.calls.subscribe[0].userVisibleOnly, true);
    assert.deepEqual([...phone.calls.subscribe[0].applicationServerKey], [...KEY_BYTES]);
    const posted = phone.calls.requests.find((r) => r.url === "/api/push/subscriptions" && r.method === "POST");
    assert.deepEqual(posted.body, { endpoint: "https://fcm.googleapis.com/fcm/send/phone-1", keys: { p256dh: "p", auth: "a" } });
    assert.equal(phone.toggle.checked, true);
    assert.equal(phone.status.textContent, messages["push.on"]);

    // Reopening the settings shows it on, from the server's answer.
    await phone.refresh();
    assert.equal(phone.toggle.checked, true);

    // Off: the server forgets the phone, then the browser.
    await phone.flip(false);
    assert.equal(phone.server.size, 0);
    assert.equal(phone.calls.unsubscribed, 1);
    assert.equal(phone.toggle.checked, false);
    assert.equal(phone.status.textContent, messages["push.off"]);
    assert.equal(phone.calls.permission, 1);
  }

  // A refusal leaves the switch off and says where to change it.
  const refused = boot({ answer: "denied" });
  await refused.refresh();
  await refused.flip(true);
  assert.equal(refused.toggle.checked, false);
  assert.equal(refused.calls.subscribe.length, 0);
  assert.equal(refused.status.textContent, messages["push.denied"]);

  // Already blocked, or the server without keys: the switch stays disabled.
  const blocked = boot({ permission: "denied" });
  await blocked.refresh();
  assert.equal(blocked.toggle.disabled, true);
  assert.equal(blocked.status.textContent, messages["push.denied"]);
  const off = boot({ enabled: false });
  await off.refresh();
  assert.equal(off.toggle.disabled, true);
  assert.equal(off.status.textContent, messages["push.server_off"]);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
