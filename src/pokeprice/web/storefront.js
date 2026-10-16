// Public storefront: read-only, no account, no management code loaded.
"use strict";

const $ = (id) => document.getElementById(id);
const LANGUAGES = {
  fr: "Français",
  en: "Anglais",
  es: "Espagnol",
  it: "Italien",
  de: "Allemand",
  ja: "Japonais",
  pt: "Portugais",
  ko: "Coréen",
  zh: "Chinois",
};
const PAGE = 48;
const state = { offset: 0, items: [], total: 0, request: 0, me: null, basket: [] };
const BASKET = "lilydex-basket";

// The basket is a per-visitor convenience: it may vanish, the server decides.
function saveBasket() {
  try {
    localStorage.setItem(BASKET, JSON.stringify(state.basket));
  } catch {}
  renderAccount();
}
function readBasket() {
  try {
    const value = JSON.parse(localStorage.getItem(BASKET) || "[]");
    return Array.isArray(value) ? value.filter((x) => x && x.id) : [];
  } catch {
    return [];
  }
}

async function call(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers: options.body ? { "Content-Type": "application/json" } : {},
  });
  const text = await response.text();
  let body = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {}
  if (!response.ok) {
    let detail = body?.detail || `La demande n’a pas abouti (HTTP ${response.status}).`;
    if (Array.isArray(detail)) detail = "Vérifiez les champs du formulaire.";
    throw new Error(detail);
  }
  return body;
}

const euros = (cents) =>
  (cents / 100).toLocaleString("fr-FR", { style: "currency", currency: "EUR" });
const day = (iso) =>
  iso ? new Date(iso + "T12:00:00").toLocaleDateString("fr-FR") : "";

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function photo(listing, item, side, size) {
  return `/api/public/listings/${encodeURIComponent(listing.id)}/photo?item=${item.index}&side=${side}&size=${size}`;
}

function facts(item) {
  return [
    [item.set_name, item.number].filter(Boolean).join(" · "),
    LANGUAGES[item.language] || item.language,
    item.condition && `État ${item.condition}`,
    item.finish,
    item.stamp && `Tampon : ${item.stamp}`,
    item.distribution,
  ].filter(Boolean);
}

function title(listing) {
  return listing.items.length > 1
    ? listing.title || `Lot de ${listing.items.length} cartes`
    : listing.items[0].name;
}

function tile(listing) {
  const li = el("li", undefined, "tile");
  const open = el("button", undefined, "tile-open");
  open.type = "button";
  open.setAttribute("aria-label", `${title(listing)}, ${euros(listing.price_cents)}`);
  const first = listing.items[0];
  const figure = el("div", undefined, "tile-photo");
  if (first.photos.includes("front")) {
    const image = el("img");
    image.src = photo(listing, first, "front", "thumb");
    image.alt = "";
    image.loading = "lazy";
    figure.append(image);
  }
  if (listing.items.length > 1)
    figure.append(el("span", `${listing.items.length} cartes`, "badge"));
  const text = el("div", undefined, "tile-text");
  text.append(el("p", title(listing), "tile-name"));
  if (listing.items.length === 1)
    text.append(el("p", facts(first).slice(0, 3).join(" · "), "tile-facts"));
  text.append(el("p", euros(listing.price_cents), "price"));
  open.append(figure, text);
  open.addEventListener("click", () => show(listing));
  li.append(open);
  return li;
}

function show(listing) {
  const body = $("detail-body");
  body.replaceChildren();
  body.append(el("h2", title(listing), undefined));
  body.lastChild.id = "detail-title";
  body.append(
    el("p", `${euros(listing.price_cents)} · prix du ${day(listing.price_date)}`, "price"),
  );
  for (const item of listing.items) {
    const block = el("section", undefined, "detail-item");
    if (listing.items.length > 1) block.append(el("h3", item.name));
    const faces = el("div", undefined, "faces");
    for (const side of item.photos) {
      const image = el("img");
      image.src = photo(listing, item, side, "full");
      image.alt = `${side === "front" ? "Recto" : "Verso"} de ${item.name}`;
      image.loading = "lazy";
      faces.append(image);
    }
    const list = el("ul", undefined, "facts");
    for (const fact of facts(item)) list.append(el("li", fact));
    if (!item.condition) list.append(el("li", "État visible sur les photos"));
    block.append(faces, list);
    body.append(block);
  }
  const action = el("p", undefined, "detail-action");
  if (state.me) {
    const inBasket = state.basket.some((x) => x.id === listing.id);
    const add = el("button", inBasket ? "Déjà dans ma demande" : "Ajouter à ma demande", "primary");
    add.type = "button";
    add.disabled = inBasket;
    add.addEventListener("click", () => {
      state.basket.push({ id: listing.id, label: title(listing), price_cents: listing.price_cents });
      saveBasket();
      add.textContent = "Ajoutée à ma demande";
      add.disabled = true;
    });
    action.append(add);
  } else {
    const join = el("button", "Se connecter pour réserver");
    join.type = "button";
    join.addEventListener("click", () => {
      $("detail").close();
      $("login").showModal();
    });
    action.append(join);
  }
  body.append(action);
  $("detail").showModal();
}

function renderAccount() {
  const signedIn = Boolean(state.me);
  for (const id of ["login-open", "signup-open"]) $(id).hidden = signedIn;
  for (const id of ["basket-open", "requests-open", "logout"]) $(id).hidden = !signedIn;
  $("basket-open").textContent = `Ma demande (${state.basket.length})`;
}

async function whoAmI() {
  try {
    state.me = await call("/api/me");
  } catch {
    state.me = null;
  }
  renderAccount();
}

function formError(form, message) {
  const error = form.querySelector(".error");
  error.textContent = message || "";
  error.hidden = !message;
}

function renderBasket() {
  const list = $("basket-items");
  list.replaceChildren();
  for (const entry of state.basket) {
    const line = el("li");
    line.append(el("span", entry.label), el("span", euros(entry.price_cents), "price"));
    const remove = el("button", "Retirer");
    remove.type = "button";
    remove.addEventListener("click", () => {
      state.basket = state.basket.filter((x) => x.id !== entry.id);
      saveBasket();
      renderBasket();
    });
    line.append(remove);
    list.append(line);
  }
  const total = state.basket.reduce((sum, x) => sum + x.price_cents, 0);
  $("basket-total").textContent = state.basket.length
    ? `Total indicatif : ${euros(total)} (hors frais d’envoi)`
    : "Votre demande est vide : ouvrez une carte pour l’ajouter.";
  $("basket-form").hidden = !state.basket.length;
}

async function renderRequests() {
  const box = $("requests-body");
  box.replaceChildren(el("p", "Chargement…", "help"));
  try {
    const requests = await call("/api/me/requests");
    box.replaceChildren();
    if (!requests.length) box.append(el("p", "Aucune demande pour l’instant.", "help"));
    for (const request of requests) {
      const section = el("section", undefined, "request");
      section.append(
        el("h3", `${request.status_label} · ${euros(request.total_cents)}`),
        el("p", `Envoyée le ${new Date(request.created_at).toLocaleDateString("fr-FR")}`, "help"),
      );
      const lines = el("ul", undefined, "lines");
      for (const item of request.items) {
        const outcome = { accepted: "acceptée", refused: "non retenue", unavailable: "plus disponible" }[item.outcome];
        lines.append(el("li", `${item.label} · ${euros(item.price_cents)}${outcome ? " · " + outcome : ""}`));
      }
      section.append(lines);
      if (request.decision) section.append(el("p", `Réponse du vendeur : ${request.decision}`));
      if (request.status === "sent") {
        const cancel = el("button", "Annuler la demande");
        cancel.type = "button";
        cancel.addEventListener("click", async () => {
          try {
            await call(`/api/me/requests/${encodeURIComponent(request.id)}/cancel`, {
              method: "POST",
              body: JSON.stringify({ expected_version: request.version }),
            });
            renderRequests();
          } catch (error) {
            section.append(el("p", error.message, "error"));
          }
        });
        section.append(cancel);
      }
      box.append(section);
    }
  } catch (error) {
    box.replaceChildren(el("p", error.message, "error"));
  }
}

async function load(reset = true) {
  if (reset) state.offset = 0;
  const request = ++state.request;
  const query = new URLSearchParams({
    sort: $("sort").value,
    limit: PAGE,
    offset: state.offset,
  });
  if ($("q").value.trim()) query.set("q", $("q").value.trim());
  if ($("language").value) query.set("language", $("language").value);
  if ($("max").value) query.set("max_eur", $("max").value);
  $("error").hidden = true;
  try {
    const response = await fetch("/api/public/listings?" + query);
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "La vitrine ne répond pas.");
    if (request !== state.request) return; // A newer search already answered.
    state.items = reset ? result.items : state.items.concat(result.items);
    state.total = result.total;
  } catch (error) {
    $("error").textContent =
      typeof error.message === "string" ? error.message : "La vitrine ne répond pas.";
    $("error").hidden = false;
    return;
  }
  $("grid").replaceChildren(...state.items.map(tile));
  $("count").textContent = state.total
    ? `${state.total} annonce${state.total > 1 ? "s" : ""}`
    : "Aucune carte ne correspond pour l’instant.";
  $("more").hidden = state.items.length >= state.total;
}

let typing;
$("filters").addEventListener("input", () => {
  clearTimeout(typing);
  typing = setTimeout(() => load(), 250);
});
$("filters").addEventListener("submit", (event) => {
  event.preventDefault();
  load();
});
$("more").addEventListener("click", () => {
  state.offset = state.items.length;
  load(false);
});
$("login-open").addEventListener("click", () => $("login").showModal());
$("signup-open").addEventListener("click", () => $("signup").showModal());
$("basket-open").addEventListener("click", () => {
  renderBasket();
  $("basket").showModal();
});
$("requests-open").addEventListener("click", () => {
  renderRequests();
  $("requests").showModal();
});
$("logout").addEventListener("click", async () => {
  try {
    await call("/api/logout", { method: "POST" });
  } catch {}
  state.me = null;
  renderAccount();
});
$("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  formError(form, "");
  try {
    await call("/api/login", {
      method: "POST",
      body: JSON.stringify({ username: form.email.value.trim(), password: form.password.value }),
    });
    await whoAmI();
    if (!state.me) {
      formError(form, "Ce compte sert à la gestion : ouvrez la page d’accueil du site.");
      return;
    }
    form.reset();
    $("login").close();
  } catch (error) {
    formError(form, error.message);
  }
});
$("signup-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  formError(form, "");
  try {
    const result = await call("/api/public/signup", {
      method: "POST",
      body: JSON.stringify({
        email: form.email.value.trim(),
        display_name: form.display_name.value.trim(),
        password: form.password.value,
        consent: form.consent.checked,
      }),
    });
    form.reset();
    const notice = form.querySelector(".notice");
    notice.textContent = result.detail;
    notice.hidden = false;
  } catch (error) {
    formError(form, error.message);
  }
});
$("basket-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  formError(form, "");
  try {
    await call("/api/me/requests", {
      method: "POST",
      body: JSON.stringify({
        listing_ids: state.basket.map((x) => x.id),
        message: form.message.value,
      }),
    });
    state.basket = [];
    saveBasket();
    form.reset();
    $("basket").close();
    renderRequests();
    $("requests").showModal();
    load();
  } catch (error) {
    formError(form, error.message);
  }
});
state.basket = readBasket();
renderAccount();
whoAmI();
load();
