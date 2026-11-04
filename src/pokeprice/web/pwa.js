/* The management app as an installed app (docs/APP.md, « Application installable »):
 * registers the service worker of /gestion, runs the install help of the settings
 * and the « Notifications sur ce téléphone » switch (Web Push, decision 0033). */
"use strict";

// The browser's own install prompt (Chrome, Edge, Android), kept until asked for.
let installPrompt = null;

function standaloneDisplay(win) {
  return Boolean(win.matchMedia?.("(display-mode: standalone)").matches || win.navigator.standalone);
}

function appleDevice(nav) {
  return /iPhone|iPad|iPod/.test(nav.userAgent) || (nav.platform === "MacIntel" && nav.maxTouchPoints > 1);
}

function showInstallHelp(doc, win) {
  const installed = standaloneDisplay(win);
  const apple = appleDevice(win.navigator);
  doc.getElementById("install-installed").hidden = !installed;
  doc.getElementById("install-native").hidden = installed || !installPrompt;
  // The steps of the other platform stay, smaller, for a phone lent to a helper.
  doc.getElementById("install-iphone").hidden = installed;
  doc.getElementById("install-android").hidden = installed || Boolean(installPrompt);
  const first = apple ? "install-iphone" : "install-android";
  const box = doc.getElementById(first);
  box.parentNode.insertBefore(box, doc.getElementById(apple ? "install-android" : "install-iphone"));
  doc.getElementById("install-message").textContent = "";
  doc.getElementById("install-dialog").showModal();
}

async function runNativeInstall(doc) {
  const prompt = installPrompt;
  if (!prompt) return;
  installPrompt = null;
  doc.getElementById("install-native").hidden = true;
  prompt.prompt();
  const choice = await prompt.userChoice.catch(() => null);
  if (choice?.outcome === "accepted") doc.getElementById("install-message").textContent = t("install.done");
  else doc.getElementById("install-android").hidden = false;
}

// Web Push. The permission is only asked from the switch, a gesture of the user:
// iOS refuses it otherwise, and only grants it to the installed app.
const push = { key: null, enabled: false };

function pushSupported(win) {
  return Boolean(win.isSecureContext && "serviceWorker" in win.navigator && "PushManager" in win && "Notification" in win);
}

function keyBytes(base64url) {
  const text = (base64url + "=".repeat((4 - (base64url.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  return Uint8Array.from(atob(text), (c) => c.charCodeAt(0));
}

function sameKey(subscription, key) {
  const current = subscription.options?.applicationServerKey;
  if (!current) return false;
  const a = new Uint8Array(current);
  const b = keyBytes(key);
  return a.length === b.length && a.every((value, i) => value === b[i]);
}

async function pushRequest(win, path, method, body) {
  const response = await win.fetch("/api/push" + path, {
    method,
    credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw new Error("HTTP " + response.status);
  return response.json();
}

function pushView(doc, { checked = false, disabled = true, message = "" } = {}) {
  const toggle = doc.getElementById("push-toggle");
  toggle.checked = checked;
  toggle.disabled = disabled;
  doc.getElementById("push-status").textContent = message;
}

// The « À toi » queue offers notifications to a device that does not get them:
// "install" on an iPhone outside the installed app, "enable" when the server
// pushes and this device is not subscribed, null otherwise or while paused.
const OFFER_PAUSE = "lilydex-push-offer-paused";
const OFFER_PAUSE_DAYS = 14;

function offerPaused(win) {
  try {
    return Number(win.localStorage.getItem(OFFER_PAUSE) || 0) > Date.now();
  } catch {
    return false;
  }
}

function pauseOffer(win) {
  try {
    win.localStorage.setItem(OFFER_PAUSE, String(Date.now() + OFFER_PAUSE_DAYS * 86400000));
  } catch {
    // Without storage the card comes back at the next load: harmless.
  }
}

async function subscribedHere(win) {
  const registration = await win.navigator.serviceWorker.ready;
  const subscription = await registration.pushManager.getSubscription();
  if (!subscription || win.Notification.permission !== "granted" || !sameKey(subscription, push.key)) return false;
  const state = await pushRequest(win, "/subscriptions/check", "POST", { endpoint: subscription.endpoint }).catch(() => null);
  return Boolean(state?.subscribed);
}

async function pushOffer(win) {
  if (offerPaused(win)) return null;
  const settings = await pushRequest(win, "", "GET").catch(() => null);
  push.enabled = Boolean(settings?.enabled && settings.public_key);
  push.key = settings?.public_key || null;
  if (!push.enabled) return null;
  if (appleDevice(win.navigator) && !standaloneDisplay(win)) return "install";
  if (!pushSupported(win) || win.Notification.permission === "denied") return null;
  return (await subscribedHere(win)) ? null : "enable";
}

async function refreshPush(doc, win) {
  if (!doc.getElementById("push-toggle")) return;
  if (appleDevice(win.navigator) && !standaloneDisplay(win)) return pushView(doc, { message: t("push.install_first") });
  if (!pushSupported(win)) return pushView(doc, { message: t("push.unsupported") });
  const settings = await pushRequest(win, "", "GET").catch(() => null);
  push.enabled = Boolean(settings?.enabled && settings.public_key);
  push.key = settings?.public_key || null;
  if (!push.enabled) return pushView(doc, { message: t("push.server_off") });
  if (win.Notification.permission === "denied") return pushView(doc, { message: t("push.denied") });
  pushView(doc, { checked: await subscribedHere(win), disabled: false });
}

async function turnPushOn(doc, win) {
  // First thing in the gesture, before any other await: iOS needs it so.
  const permission = await win.Notification.requestPermission();
  if (permission !== "granted")
    return pushView(doc, { disabled: permission === "denied", message: t(permission === "denied" ? "push.denied" : "push.off") });
  const registration = await win.navigator.serviceWorker.ready;
  let subscription = await registration.pushManager.getSubscription();
  if (subscription && !sameKey(subscription, push.key)) {
    await subscription.unsubscribe();
    subscription = null;
  }
  subscription ||= await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(push.key) });
  const { endpoint, keys } = subscription.toJSON();
  await pushRequest(win, "/subscriptions", "POST", { endpoint, keys: { p256dh: keys.p256dh, auth: keys.auth } });
  pushView(doc, { checked: true, disabled: false, message: t("push.on") });
}

async function turnPushOff(doc, win) {
  const registration = await win.navigator.serviceWorker.ready;
  const subscription = await registration.pushManager.getSubscription();
  if (subscription) {
    await pushRequest(win, "/subscriptions", "DELETE", { endpoint: subscription.endpoint });
    await subscription.unsubscribe();
  }
  pushView(doc, { checked: false, disabled: false, message: t("push.off") });
}

async function changePush(doc, win) {
  const toggle = doc.getElementById("push-toggle");
  const wanted = toggle.checked;
  toggle.disabled = true;
  try {
    await (wanted ? turnPushOn(doc, win) : turnPushOff(doc, win));
  } catch {
    pushView(doc, { checked: !wanted, disabled: false, message: t("push.error") });
  }
}

if (typeof window !== "undefined" && typeof document !== "undefined") {
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    installPrompt = event;
  });
  window.addEventListener("appinstalled", () => {
    installPrompt = null;
  });
  document.getElementById("install-open")?.addEventListener("click", () => showInstallHelp(document, window));
  document.getElementById("install-native")?.addEventListener("click", () => runNativeInstall(document));
  document.getElementById("push-toggle")?.addEventListener("change", () => changePush(document, window));
  // app.js calls refresh each time the settings open, and the others from the queue.
  window.lilydexPush = {
    refresh: () => refreshPush(document, window).catch(() => pushView(document, { message: t("push.error") })),
    offer: () => pushOffer(window),
    // From the card's click, with no await before: iOS asks permission only so.
    enable: () => turnPushOn(document, window),
    install: () => showInstallHelp(document, window),
    pause: () => pauseOffer(window),
  };
  if ("serviceWorker" in navigator && window.isSecureContext) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/gestion/sw.js", { scope: "/gestion" }).catch(() => {});
    });
  }
}
