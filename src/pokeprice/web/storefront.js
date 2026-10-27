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
    throw Object.assign(new Error(detail), { status: response.status });
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
    // An unconfirmed condition is hidden by the server: say so instead.
    item.condition ? `État ${item.condition}` : "État non confirmé : voir la photo",
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

// The edition tells apart the many copies that share a name.
function label(listing) {
  if (listing.items.length > 1) return title(listing);
  const item = listing.items[0];
  return [item.name, item.set_name, item.number].filter(Boolean).join(" · ");
}

function tile(listing) {
  const li = el("li", undefined, "tile");
  const open = el("button", undefined, "tile-open");
  open.type = "button";
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

// A card's address: /carte/<publication id>, filters kept after the #.
const CARD = /^\/carte\/([^/]+)$/;
function cardPath(listing) {
  return `/carte/${encodeURIComponent(listing.id)}`;
}

function show(listing) {
  if (location.pathname !== cardPath(listing)) {
    history.pushState({ card: listing.id }, "", cardPath(listing) + location.hash);
  }
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
    if (!item.photos.includes("back"))
      list.append(el("li", "Verso non photographié : demandez-le dans votre message"));
    block.append(faces, list);
    body.append(block);
  }
  const action = el("p", undefined, "detail-action");
  if (state.me) {
    const inBasket = state.basket.some((x) => x.id === listing.id);
    const add = el("button", inBasket ? "Déjà dans ma demande" : "Ajouter à ma demande", "primary");
    add.type = "button";
    add.disabled = inBasket;
    const view = el("button", "Voir ma demande");
    view.type = "button";
    view.hidden = !inBasket;
    view.addEventListener("click", () => {
      $("detail").close();
      $("basket-open").click();
    });
    const added = el("span", "", "notice");
    added.setAttribute("role", "status");
    add.addEventListener("click", () => {
      state.basket.push({ id: listing.id, label: label(listing), price_cents: listing.price_cents });
      saveBasket();
      add.textContent = "Ajoutée à ma demande";
      add.disabled = true;
      view.hidden = false;
      const count = state.basket.length;
      added.textContent = `${count} carte${count > 1 ? "s" : ""} dans votre demande.`;
    });
    action.append(add, view, added);
  } else {
    const join = el("button", "Se connecter pour réserver");
    join.type = "button";
    join.addEventListener("click", () => {
      $("detail").close();
      $("login").showModal();
    });
    action.append(join);
  }
  const share = el("button", "Copier le lien");
  share.type = "button";
  const shared = el("span", "", "help");
  shared.setAttribute("role", "status");
  share.addEventListener("click", async () => {
    const url = location.origin + cardPath(listing);
    try {
      await navigator.clipboard.writeText(url);
      shared.textContent = "Lien copié.";
    } catch {
      // Without clipboard access the link is still there to copy by hand.
      shared.textContent = url;
    }
  });
  action.append(share, shared);
  body.append(action);
  if (!$("detail").open) $("detail").showModal();
}

// Closing the fiche goes back to the list, as the browser's Back button does.
// The open attribute is watched: some browsers skip the dialog's close event.
// Chrome ignores history.back() without a user gesture (Escape is not one):
// the address is then rewritten in place.
const leaveCard = () => {
  if (!$("detail").open && CARD.test(location.pathname))
    history.replaceState(null, "", "/" + location.hash);
};
new MutationObserver(() => {
  if ($("detail").open || !CARD.test(location.pathname)) return;
  if (history.state?.card) {
    history.back();
    setTimeout(leaveCard, 300);
  } else leaveCard();
}).observe($("detail"), { attributes: true, attributeFilter: ["open"] });

async function openFromAddress() {
  const match = CARD.exec(location.pathname);
  if (!match) {
    if ($("detail").open) $("detail").close();
    return;
  }
  try {
    show(await call(`/api/public/listings/${match[1]}`));
  } catch {
    history.replaceState(null, "", "/" + location.hash);
    $("notice").textContent = "Cette carte n’est plus en vente : voici les autres.";
    $("notice").hidden = false;
  }
}
window.addEventListener("popstate", openFromAddress);

// Filters live after the #: the server never sees them, and old management
// links on / keep their redirect.
const FILTERS = [["q", "q"], ["language", "langue"], ["max", "max"], ["sort", "tri"]];
function writeFilters() {
  const query = new URLSearchParams();
  for (const [id, key] of FILTERS) {
    const value = $(id).value.trim();
    if (value && !(id === "sort" && value === "recent")) query.set(key, value);
  }
  const hash = query.size ? "#" + query.toString() : "";
  if (location.hash !== hash)
    history.replaceState(history.state, "", location.pathname + location.search + hash);
}
function readFilters() {
  const query = new URLSearchParams(location.hash.slice(1));
  for (const [id, key] of FILTERS) {
    const value = query.get(key) || "";
    const field = $(id);
    if (field.tagName === "SELECT")
      field.value = Array.from(field.options).some((o) => o.value === value) ? value : field.options[0].value;
    else field.value = value.slice(0, 200);
  }
}
window.addEventListener("hashchange", () => {
  readFilters();
  load();
});

function renderAccount() {
  const signedIn = Boolean(state.me);
  for (const id of ["login-open", "signup-open"]) $(id).hidden = signedIn;
  for (const id of ["basket-open", "requests-open", "account-open", "logout"]) $(id).hidden = !signedIn;
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
  writeFilters();
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
    state.approximate = Boolean(result.approximate);
  } catch (error) {
    $("error").textContent =
      typeof error.message === "string" ? error.message : "La vitrine ne répond pas.";
    $("error").hidden = false;
    return;
  }
  $("grid").replaceChildren(...state.items.map(tile));
  $("count").textContent = state.total
    ? `${state.total} annonce${state.total > 1 ? "s" : ""}${state.approximate ? ` · résultats approchés pour « ${$("q").value.trim()} »` : ""}`
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
$("account-open").addEventListener("click", () => {
  const form = $("profile-form");
  form.reset();
  form.display_name.value = state.me.display_name;
  form.email.value = state.me.email;
  for (const box of [form, $("delete-form")]) formError(box, "");
  form.querySelector(".notice").hidden = true;
  $("delete-form").reset();
  $("account").showModal();
});
$("profile-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  formError(form, "");
  form.querySelector(".notice").hidden = true;
  try {
    state.me = await call("/api/me", {
      method: "PATCH",
      body: JSON.stringify({
        display_name: form.display_name.value.trim(),
        email: form.email.value.trim(),
        password: form.password.value,
      }),
    });
    form.password.value = "";
    const notice = form.querySelector(".notice");
    notice.textContent = "Modifications enregistrées.";
    notice.hidden = false;
  } catch (error) {
    formError(form, error.message);
  }
});
$("delete-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  formError(form, "");
  try {
    await call("/api/me/delete", {
      method: "POST",
      body: JSON.stringify({ password: form.password.value }),
    });
  } catch (error) {
    formError(form, error.message);
    return;
  }
  state.me = null;
  state.basket = [];
  saveBasket();
  $("account").close();
  $("notice").textContent = "Votre compte et vos données ont été supprimés.";
  $("notice").hidden = false;
});
$("logout").addEventListener("click", async () => {
  try {
    await call("/api/logout", { method: "POST" });
  } catch (error) {
    // Without the server's answer the session may still be valid: say so, keep it.
    if (error.status !== 401) {
      const reason = error.status ? error.message : "le serveur ne répond pas.";
      $("error").textContent = `Déconnexion impossible : ${reason} Réessayez.`;
      $("error").hidden = false;
      return;
    }
  }
  $("error").hidden = true;
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
      // A seller account: its place is the management application.
      location.href = "/gestion";
      return;
    }
    form.reset();
    $("notice").hidden = true;
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
readFilters();
load();
openFromAddress();
