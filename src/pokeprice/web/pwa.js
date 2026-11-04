/* The management app as an installed app (docs/APP.md, « Application installable »):
 * registers the service worker of /gestion and runs the install help of the settings. */
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
  if ("serviceWorker" in navigator && window.isSecureContext) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/gestion/sw.js", { scope: "/gestion" }).catch(() => {});
    });
  }
}
