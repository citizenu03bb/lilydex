/* Shared W3C Custom Elements (Light DOM) and theme/filter helpers for the site. */
"use strict";

function resolveLilydexTheme(stored, prefersDark) {
  if (stored === "herbier" || stored === "vault" || stored === "atelier") {
    return stored;
  }
  return prefersDark ? "vault" : "herbier";
}

const LILYDEX_THEME_KEY = "lilydex-theme";
const LILYDEX_THEMES = ["auto", "herbier", "vault", "atelier"];

function applyLilydexTheme(doc, choice, prefersDark) {
  if (!doc || !doc.documentElement) return "herbier";
  const mode = LILYDEX_THEMES.includes(choice) ? choice : "auto";
  const resolved = resolveLilydexTheme(mode, Boolean(prefersDark));
  doc.documentElement.dataset.theme = resolved;
  doc.documentElement.dataset.themeMode = mode;
  const meta = doc.querySelector?.('meta[name="color-scheme"]');
  if (meta) {
    meta.content = resolved === "vault" ? "dark" : "light";
  }
  return resolved;
}

function activeFilterChips(entries) {
  const result = [];
  for (const [key, item] of Object.entries(entries || {})) {
    if (!item) continue;
    const val = String(item.value ?? "").trim();
    const def = String(item.defaultValue ?? "").trim();
    if (!val || val === def) continue;
    result.push({
      key,
      value: val,
      label: item.label || val,
    });
  }
  return result;
}

// W3C Custom Elements registration (guarded for Node.js runtime test harness)
if (typeof window !== "undefined" && typeof document !== "undefined") {
  const mediaQuery = window.matchMedia
    ? window.matchMedia("(prefers-color-scheme: dark)")
    : { matches: false, addEventListener() {} };

  function readStoredTheme() {
    try {
      const raw = localStorage.getItem(LILYDEX_THEME_KEY);
      return LILYDEX_THEMES.includes(raw) ? raw : "auto";
    } catch {
      return "auto";
    }
  }

  function setLilydexTheme(choice) {
    const mode = LILYDEX_THEMES.includes(choice) ? choice : "auto";
    try {
      if (mode === "auto") localStorage.removeItem(LILYDEX_THEME_KEY);
      else localStorage.setItem(LILYDEX_THEME_KEY, mode);
    } catch {}
    applyLilydexTheme(document, mode, mediaQuery.matches);
    for (const picker of document.querySelectorAll("lilydex-theme-picker")) {
      picker.sync?.(mode);
    }
  }

  // Apply immediately on script load to avoid FOUC under strict CSP
  applyLilydexTheme(document, readStoredTheme(), mediaQuery.matches);
  mediaQuery.addEventListener?.("change", () => {
    const current = readStoredTheme();
    if (current === "auto") {
      applyLilydexTheme(document, "auto", mediaQuery.matches);
      for (const picker of document.querySelectorAll("lilydex-theme-picker")) {
        picker.sync?.("auto");
      }
    }
  });
  window.addEventListener?.("storage", (event) => {
    if (event.key === LILYDEX_THEME_KEY || event.key === null) {
      const mode = readStoredTheme();
      applyLilydexTheme(document, mode, mediaQuery.matches);
      for (const picker of document.querySelectorAll("lilydex-theme-picker")) {
        picker.sync?.(mode);
      }
    }
  });

  if (typeof customElements !== "undefined") {
    if (!customElements.get("lilydex-theme-picker")) {
      class LilydexThemePicker extends HTMLElement {
        connectedCallback() {
          if (this.querySelector(".theme-picker")) {
            this.sync(readStoredTheme());
            return;
          }
          const group = document.createElement("div");
          group.className = "theme-picker";
          group.setAttribute("role", "radiogroup");
          group.setAttribute("aria-label", "Thème d’affichage");
          // Plain words on the buttons: the design names mean nothing to a visitor.
          const options = [
            ["auto", "Auto", "Suivre le thème clair ou sombre de votre appareil"],
            ["herbier", "Clair", "Thème clair éditorial (Herbier)"],
            ["vault", "Sombre", "Thème sombre à contraste élevé (Vault)"],
            ["atelier", "Dense", "Thème clair technique, plus dense (Atelier)"],
          ];
          for (const [mode, label, title] of options) {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.setAttribute("role", "radio");
            btn.dataset.themeChoice = mode;
            btn.textContent = label;
            btn.title = title;
            btn.setAttribute("aria-checked", "false");
            btn.setAttribute("aria-pressed", "false");
            btn.addEventListener("click", () => setLilydexTheme(mode));
            group.append(btn);
          }
          group.addEventListener("keydown", (event) => {
            if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
            event.preventDefault();
            const buttons = Array.from(group.querySelectorAll("button[data-theme-choice]"));
            const currentIdx = Math.max(
              0,
              buttons.findIndex((b) => b.getAttribute("aria-checked") === "true"),
            );
            const delta = event.key === "ArrowRight" ? 1 : -1;
            const nextBtn = buttons[(currentIdx + delta + buttons.length) % buttons.length];
            if (nextBtn) {
              setLilydexTheme(nextBtn.dataset.themeChoice);
              nextBtn.focus();
            }
          });
          this.replaceChildren(group);
          this.sync(readStoredTheme());
        }
        sync(mode = readStoredTheme()) {
          for (const btn of this.querySelectorAll("button[data-theme-choice]")) {
            const active = btn.dataset.themeChoice === mode;
            btn.setAttribute("aria-checked", String(active));
            btn.setAttribute("aria-pressed", String(active));
            btn.tabIndex = active ? 0 : -1;
          }
        }
      }
      customElements.define("lilydex-theme-picker", LilydexThemePicker);
    }

    if (!customElements.get("lilydex-filter-bar")) {
      class LilydexFilterBar extends HTMLElement {
        connectedCallback() {
          if (this._initialized) return;
          this._initialized = true;
          this.addEventListener("change", () => this.refreshChips());
          this.addEventListener("input", () => this.refreshChips());
          setTimeout(() => this.refreshChips(), 0);
        }
        refreshChips() {
          const chipsBox = this.querySelector(".active-filter-chips");
          const badge = this.querySelector(".secondary-filter-count");
          if (!chipsBox) return;
          const find = (id) => this.querySelector(`#${id}`);
          const selectText = (id) => {
            const el = find(id);
            if (!el || !el.value) return "";
            const opt = el.selectedOptions?.[0];
            return opt ? opt.textContent.trim() : el.value;
          };
          const thresholdEl = find("review-threshold");
          const entries = {
            q: {
              value: find("q")?.value || "",
              label: `Recherche : ${find("q")?.value || ""}`,
              reset: () => {
                const el = find("q");
                if (el) {
                  el.value = "";
                  el.dispatchEvent(new Event("input", { bubbles: true }));
                }
              },
            },
            language: {
              value: find("language")?.value || "",
              label: `Langue : ${selectText("language")}`,
              reset: () => {
                const el = find("language");
                if (el) {
                  el.value = "";
                  el.dispatchEvent(new Event("input", { bubbles: true }));
                }
              },
            },
            extension: {
              value: find("extension")?.value || "",
              label: `Extension : ${selectText("extension")}`,
              reset: () => {
                const el = find("extension");
                if (el) {
                  el.value = "";
                  el.dispatchEvent(new Event("input", { bubbles: true }));
                }
              },
            },
            finish: {
              value: find("finish")?.value || "",
              label: `Finition : ${selectText("finish")}`,
              reset: () => {
                const el = find("finish");
                if (el) {
                  el.value = "";
                  el.dispatchEvent(new Event("input", { bubbles: true }));
                }
              },
            },
            max: {
              value: find("max")?.value || "",
              label: `Max : ${find("max")?.value || ""} €`,
              reset: () => {
                const el = find("max");
                if (el) {
                  el.value = "";
                  el.dispatchEvent(new Event("input", { bubbles: true }));
                }
              },
            },
            search: {
              value: find("search")?.value || "",
              label: `Recherche : ${find("search")?.value || ""}`,
              reset: () => {
                const el = find("search");
                if (el) {
                  el.value = "";
                  el.dispatchEvent(new Event("input", { bubbles: true }));
                }
              },
            },
            album: {
              value: find("album-filter")?.value || "",
              label: `Album : ${selectText("album-filter")}`,
              reset: () => {
                const el = find("album-filter");
                if (el) {
                  el.value = "";
                  el.dispatchEvent(new Event("change", { bubbles: true }));
                }
              },
            },
            review: {
              value: find("review-filter")?.value || "",
              label: `Examen : ${selectText("review-filter")}`,
              reset: () => {
                const el = find("review-filter");
                if (el) {
                  el.value = "";
                  el.dispatchEvent(new Event("change", { bubbles: true }));
                }
              },
            },
            stock: {
              value: find("stock-filter")?.value || "",
              label: `Stock : ${selectText("stock-filter")}`,
              secondary: true,
              reset: () => {
                const el = find("stock-filter");
                if (el) {
                  el.value = "";
                  el.dispatchEvent(new Event("change", { bubbles: true }));
                }
              },
            },
            status: {
              value: find("status-filter")?.value || "",
              label: `Identité : ${selectText("status-filter")}`,
              secondary: true,
              reset: () => {
                const el = find("status-filter");
                if (el) {
                  el.value = "";
                  el.dispatchEvent(new Event("change", { bubbles: true }));
                }
              },
            },
            variant: {
              value: find("variant-filter")?.value || "",
              label: `Variante : ${selectText("variant-filter")}`,
              secondary: true,
              reset: () => {
                const el = find("variant-filter");
                if (el) {
                  el.value = "";
                  el.dispatchEvent(new Event("change", { bubbles: true }));
                }
              },
            },
            threshold: {
              value: thresholdEl?.value || "10",
              defaultValue: "10",
              label: `Seuil : ${thresholdEl?.value || "10"} €`,
              secondary: true,
              reset: () => {
                if (thresholdEl) {
                  thresholdEl.value = "10";
                  thresholdEl.dispatchEvent(new Event("change", { bubbles: true }));
                }
              },
            },
          };
          const active = activeFilterChips(entries);
          const secondaryCount = active.filter((c) => entries[c.key]?.secondary).length;
          if (badge) {
            badge.textContent = secondaryCount ? String(secondaryCount) : "";
            badge.hidden = secondaryCount === 0;
          }
          chipsBox.replaceChildren();
          if (!active.length) {
            chipsBox.hidden = true;
            return;
          }
          chipsBox.hidden = false;
          for (const item of active) {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "filter-chip";
            btn.textContent = `${item.label} ×`;
            btn.setAttribute("aria-label", `Retirer le filtre ${item.label}`);
            btn.addEventListener("click", () => entries[item.key]?.reset?.());
            chipsBox.append(btn);
          }
        }
      }
      customElements.define("lilydex-filter-bar", LilydexFilterBar);
    }
  }
}
