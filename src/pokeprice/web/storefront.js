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
const state = { offset: 0, items: [], total: 0, request: 0 };

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
  $("detail").showModal();
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
load();
