// Public storefront: read-only, no account, no management code loaded.
"use strict";

const $ = (id) => document.getElementById(id);
const language = (code) => t(`language.${code}`, {}, code);
const PAGE = 48;
const state = { offset: 0, items: [], total: 0, request: 0, me: null, basket: [] };
const BASKET = "lilydex-basket";
const pageTitle = document.title;
// Capture before submit handlers: a second click or Enter never starts another request.
const pendingForms = new WeakSet();
document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!form.id?.endsWith("-form") || form.method === "dialog") return;
  if (pendingForms.has(form)) { event.preventDefault(); event.stopImmediatePropagation(); return; }
  pendingForms.add(form);
  form.setAttribute("aria-busy", "true");
  let status = form.querySelector(".submit-status");
  if (!status) { status = el("p", "", "submit-status"); status.setAttribute("role", "status"); form.append(status); }
  status.textContent = t("common.sending");
}, true);
function releaseForm(form) {
  pendingForms.delete(form);
  form.removeAttribute("aria-busy");
  const status = form.querySelector(".submit-status");
  if (status) status.textContent = "";
}

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
  }).catch(() => { throw new Error(t("error.network")); });
  const text = await response.text();
  let body = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {}
  if (text && body === null) throw new Error(t("error.response"));
  if (!response.ok) {
    let detail = failure(body, t("error.http", { status: response.status }));
    if (Array.isArray(detail)) detail = t("error.fields");
    throw Object.assign(new Error(detail), { status: response.status });
  }
  return body;
}

// The server's French detail, in the page's language when its code is known.
const failure = (body, fallback) =>
  body?.code ? t(`error.${body.code}`, {}, fallback) : fallback;

const euros = (cents) =>
  (cents / 100).toLocaleString(t.locale, { style: "currency", currency: "EUR" });
const day = (iso) =>
  iso ? new Date(iso + "T12:00:00").toLocaleDateString(t.locale) : "";

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function watchPhoto(image, interactive = true) {
  image.addEventListener("error", () => {
    image.hidden = true;
    if (!interactive) { image.parentNode?.append(el("span", t("photo.unavailable"), "photo-retry")); return; }
    const retry = el(interactive ? "button" : "span", t("photo.retry"), "photo-retry");
    retry.type = "button";
    image.hidden = true;
    retry.addEventListener("click", event => {
      event.preventDefault(); event.stopPropagation();
      retry.remove(); image.hidden = false;
      image.src = image.src;
    });
    image.parentNode?.append(retry);
  });
}
function photo(listing, item, side, size) {
  return `/api/public/listings/${encodeURIComponent(listing.id)}/photo?item=${item.index}&side=${side}&size=${size}`;
}

function facts(item) {
  return [
    [item.set_name, item.number].filter(Boolean).join(" · "),
    language(item.language),
    // An unconfirmed condition is hidden by the server: say so instead.
    item.condition ? t("item.condition", { condition: item.condition }) : t("item.condition_unconfirmed"),
    item.finish && t(`finish.${item.finish}`, {}, item.finish),
    item.stamp && t("item.stamp", { stamp: item.stamp }),
    item.distribution,
  ].filter(Boolean);
}

function title(listing) {
  return listing.items.length > 1
    ? listing.title || t("listing.lot", { count: listing.items.length })
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
  // A real link: middle click or "open in a new tab" reach the card's address.
  const open = el("a", undefined, "tile-open");
  open.href = cardPath(listing);
  const first = listing.items[0];
  const figure = el("div", undefined, "tile-photo");
  if (first.photos.includes("front")) {
    const image = el("img");
    image.src = photo(listing, first, "front", "thumb");
    image.alt = "";
    image.loading = "lazy";
    watchPhoto(image, false);
    figure.append(image);
  }
  if (listing.items.length > 1)
    figure.append(el("span", t("tile.cards", { count: listing.items.length }), "badge"));
  const text = el("div", undefined, "tile-text");
  const head = el("div", undefined, "tile-head");
  head.append(el("p", title(listing), "tile-name"), el("p", euros(listing.price_cents), "price"));
  text.append(head);
  if (listing.items.length === 1) {
    text.append(el("p", [first.set_name, first.number].filter(Boolean).join(" · "), "tile-facts"));
    text.append(el("p", [language(first.language), first.finish && t(`finish.${first.finish}`, {}, first.finish)].filter(Boolean).join(" · "), "tile-spec"));
    text.append(el("p", first.condition ? t("item.condition", { condition: first.condition }) : t("tile.condition_pending"), "tile-state"));
  } else {
    text.append(el("p", t("tile.lot_facts"), "tile-facts"));
    text.append(el("p", t("tile.lot_spec"), "tile-spec"));
  }
  open.append(figure, text);
  open.addEventListener("click", (event) => {
    if (event.button || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    show(listing);
  });
  li.append(open);
  return li;
}

// A card's address: /carte/<publication id> under the language's home (/ or /en/),
// filters kept after the #. The server writes the home on <html>.
const HOME = document.documentElement.dataset.home || "/";
const CARD = /^(?:\/[a-z]{2})?\/carte\/([^/]+)$/;
function cardPath(listing) {
  return `${HOME}carte/${encodeURIComponent(listing.id)}`;
}

// The fiche is also a viewer: one photo at a time, the neighbouring cards of
// the list a swipe or an arrow key away.
function faces(listing) {
  return listing.items.flatMap((item) => item.photos.map((side) => ({ item, side })));
}

const side = (name) => (name === "front" ? t("viewer.front") : t("viewer.back"));

function drawFace() {
  const listing = state.current;
  const all = faces(listing);
  const face = all[state.face];
  const stage = $("detail-stage");
  if (face) {
    const image = el("img");
    image.src = photo(listing, face.item, face.side, "full");
    image.alt = t("viewer.alt", { side: side(face.side), name: face.item.name });
    watchPhoto(image);
    stage.replaceChildren(image);
  } else stage.replaceChildren(el("p", t("viewer.no_photo"), "help"));
  const flip = $("detail-flip");
  flip.hidden = all.length < 2;
  // One card: recto and verso. A lot: every photo in turn.
  flip.textContent =
    listing.items.length > 1
      ? t("viewer.photo_count", { index: state.face + 1, total: all.length })
      : side(face?.side === "front" ? "back" : "front");
  $("detail-caption").textContent = face
    ? [side(face.side), listing.items.length > 1 && face.item.name]
        .filter(Boolean)
        .join(" · ")
    : "";
}

function flip() {
  const count = faces(state.current).length;
  if (count < 2) return;
  state.face = (state.face + 1) % count;
  drawFace();
}

const position = () => state.items.findIndex((x) => x.id === state.current?.id);

function drawNav() {
  const index = position();
  // A card opened from its address may not be in the list loaded behind it.
  for (const id of ["detail-previous", "detail-next", "detail-position"]) $(id).hidden = index < 0;
  if (index < 0) return;
  $("detail-previous").disabled = index === 0;
  $("detail-next").disabled = index === state.items.length - 1 && state.items.length >= state.total;
  $("detail-position").textContent = `${(index + 1).toLocaleString(t.locale)} / ${state.total.toLocaleString(t.locale)}`;

}

async function step(delta) {
  if (state.stepping || position() < 0) return;
  state.stepping = true;
  try {
    if (position() + delta >= state.items.length && state.items.length < state.total) {
      state.offset = state.items.length;
      await load(false);
    }
    const next = state.items[position() + delta];
    if (next && $("detail").open) show(next, true);
  } finally {
    state.stepping = false;
  }
}

function show(listing, replace = false) {
  if (location.pathname !== cardPath(listing)) {
    const address = cardPath(listing) + location.hash;
    // Going from card to card keeps one history entry: Back returns to the list.
    if (replace) history.replaceState(history.state, "", address);
    else history.pushState({ card: listing.id }, "", address);
  }
  state.current = listing;
  document.title = `${title(listing)} · ${pageTitle}`;
  refreshLanguageLink();
  state.face = 0;
  drawFace();
  drawNav();
  const body = $("detail-body");
  body.replaceChildren();
  body.append(el("h2", title(listing), undefined));
  body.lastChild.id = "detail-title";
  body.append(
    el("p", t("detail.price", { price: euros(listing.price_cents), date: day(listing.price_date) }), "price"),
  );
  for (const item of listing.items) {
    const block = el("section", undefined, "detail-item");
    if (listing.items.length > 1) block.append(el("h3", item.name));
    const list = el("ul", undefined, "facts");
    for (const fact of facts(item)) list.append(el("li", fact));
    if (!item.photos.includes("back"))
      list.append(el("li", t("detail.no_back")));
    block.append(list);
    body.append(block);
  }
  const action = el("p", undefined, "detail-action");
  // No account needed: the request itself carries the address.
  const inBasket = state.basket.some((x) => x.id === listing.id);
  const add = el("button", inBasket ? t("detail.in_basket") : t("detail.add"), "primary");
  add.type = "button";
  add.disabled = inBasket;
  const view = el("button", t("detail.view_basket"));
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
    add.textContent = t("detail.added");
    add.disabled = true;
    view.hidden = false;
    added.textContent = t("detail.basket_count", { count: state.basket.length });
  });
  action.append(add, view, added);
  const share = el("button", t("detail.share"));
  share.type = "button";
  const shared = el("span", "", "help");
  shared.setAttribute("role", "status");
  share.addEventListener("click", async () => {
    const url = location.origin + cardPath(listing);
    try {
      await navigator.clipboard.writeText(url);
      shared.textContent = t("detail.shared");
    } catch {
      // Without clipboard access the link is still there to copy by hand.
      shared.textContent = url;
    }
  });
  action.append(share, shared);
  body.append(action);
  if (!$("detail").open) $("detail").showModal();
  $("detail").scrollTop = $("detail-body").scrollTop = 0;
}

$("detail-previous").addEventListener("click", () => step(-1));
$("detail-next").addEventListener("click", () => step(1));
$("detail-flip").addEventListener("click", flip);
$("detail").addEventListener("keydown", (event) => {
  if (event.altKey || event.ctrlKey || event.metaKey) return;
  if (event.target.closest("input, select, textarea")) return;
  if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
    event.preventDefault();
    step(event.key === "ArrowLeft" ? -1 : 1);
  } else if (event.key === "r" || event.key === "R") flip();
  else if (event.key === "f" || event.key === "F") fullView(!$("detail").classList.contains("full"));
});

// A horizontal swipe on the photo changes card; vertical scroll and pinch zoom stay native.
let swipe = null;
$("detail-stage").addEventListener("pointerdown", (event) => {
  swipe = event.isPrimary && event.pointerType !== "mouse" ? { x: event.clientX, y: event.clientY } : null;
});
$("detail-stage").addEventListener("pointercancel", () => (swipe = null));
$("detail-stage").addEventListener("pointerup", (event) => {
  if (!swipe) return;
  const dx = event.clientX - swipe.x;
  const dy = event.clientY - swipe.y;
  swipe = null;
  if (Math.abs(dx) > 50 && Math.abs(dx) > 1.5 * Math.abs(dy)) step(dx < 0 ? 1 : -1);
});

// On a computer the fiche can take the whole screen; a phone always shows it so.
// The choice is a per-visitor convenience, kept on the device.
const FULL = "lilydex-viewer-full";
function fullView(on) {
  $("detail").classList.toggle("full", on);
  $("detail-full").setAttribute("aria-pressed", String(on));
  $("detail-full").textContent = on ? t("viewer.reduce") : t("viewer.full");
  try {
    if (on) localStorage.setItem(FULL, "1");
    else localStorage.removeItem(FULL);
  } catch {}
}
$("detail-full").addEventListener("click", () => fullView(!$("detail").classList.contains("full")));
try {
  fullView(localStorage.getItem(FULL) === "1");
} catch {}

// Closing the fiche goes back to the list, as the browser's Back button does.
// The open attribute is watched: some browsers skip the dialog's close event.
// Chrome ignores history.back() without a user gesture (Escape is not one):
// the address is then rewritten in place.
const leaveCard = () => {
  if (!$("detail").open) { document.title = pageTitle; refreshLanguageLink(); }
  if (!$("detail").open && CARD.test(location.pathname))
    history.replaceState(null, "", HOME + location.hash);
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
    history.replaceState(null, "", HOME + location.hash);
    $("notice").textContent = t("results.card_gone");
    $("notice").hidden = false;
  }
}
window.addEventListener("popstate", openFromAddress);

// The other language opens on the same card, with the same filters.
function refreshLanguageLink() {
  const link = $("language-switch");
  link.href = link.dataset.home + location.pathname.replace(/^(?:\/[a-z]{2})?\//, "") + location.hash;
}
$("language-switch").addEventListener("click", refreshLanguageLink);
window.addEventListener("popstate", refreshLanguageLink);
window.addEventListener("hashchange", refreshLanguageLink);
refreshLanguageLink();

// Filters live after the #: the server never sees them, and old management
// links on / keep their redirect.
const FILTERS = [
  ["q", "q"], ["extension", "extension"], ["language", "langue"],
  ["max", "max"], ["finish", "finition"], ["sort", "tri"],
];
function writeFilters() {
  const query = new URLSearchParams();
  for (const [id, key] of FILTERS) {
    const value = $(id).value.trim();
    if (value && !(id === "sort" && value === "recent")) query.set(key, value);
  }
  const hash = query.size ? "#" + query.toString() : "";
  if (location.hash !== hash)
    history.replaceState(history.state, "", location.pathname + location.search + hash);
  refreshLanguageLink();
}
function readFilters() {
  const query = new URLSearchParams(location.hash.slice(1));
  for (const [id, key] of FILTERS) {
    const value = (query.get(key) || "").slice(0, 200);
    const field = $(id);
    // Extension choices arrive with the first response. Keep a shared URL's
    // selection until then, even if the last matching publication was withdrawn.
    if (id === "extension" && value && !Array.from(field.options).some((o) => o.value === value)) {
      const option = el("option", value);
      option.value = value;
      field.append(option);
    }
    if (field.tagName === "SELECT")
      field.value = Array.from(field.options).some((o) => o.value === value) ? value : field.options[0].value;
    else field.value = value.slice(0, 200);
  }
}
window.addEventListener("hashchange", () => {
  if (openLink()) return;
  readFilters();
  load();
});

// A link sent by the seller: the token leaves the address bar and the history at once.
const LINK = /^#mot-de-passe=([\w-]{20,100})$/;
function openLink() {
  const link = LINK.exec(location.hash);
  if (!link) return false;
  state.link = link[1];
  history.replaceState(null, "", location.pathname + location.search);
  for (const dialog of document.querySelectorAll("dialog[open]")) dialog.close();
  $("password").showModal();
  return true;
}

function renderAccount() {
  const signedIn = Boolean(state.me);
  for (const id of ["login-open", "signup-open"]) $(id).hidden = signedIn;
  for (const id of ["requests-open", "account-open", "logout"]) $(id).hidden = !signedIn;
  $("basket-count").textContent = state.basket.length;
  $("basket-open").setAttribute("aria-label", t("basket.label", { count: state.basket.length }));
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
  $("basket-title").textContent = t("basket.title");
  const list = $("basket-items");
  list.replaceChildren();
  for (const entry of state.basket) {
    const line = el("li");
    // Derived from the id, so baskets saved before the photo was shown get one too.
    const image = el("img", undefined, "basket-thumb");
    image.src = photo(entry, { index: 0 }, "front", "thumb");
    image.alt = "";
    image.addEventListener("error", () => image.remove());
    line.append(image, el("span", entry.label, "basket-name"), el("span", euros(entry.price_cents), "price"));
    const remove = el("button", t("basket.remove"));
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
    ? t("basket.total", { total: euros(total) })
    : t("basket.empty");
  $("basket-form").hidden = !state.basket.length;
  $("basket-browse").hidden = Boolean(state.basket.length);
  // A disabled fieldset is left out of the form's checks.
  const guest = $("basket-guest");
  guest.hidden = guest.disabled = Boolean(state.me);
}

// Shown only while the lot is reserved and unpaid: the server sends nothing otherwise.
function paymentBox(payment) {
  const box = el("div", undefined, "payment");
  const total = payment.shipping_cents
    ? t("payment.total_shipping", { total: euros(payment.total_cents), shipping: euros(payment.shipping_cents) })
    : euros(payment.total_cents);
  box.append(
    el("h4", t("payment.title")),
    el("p", t("payment.amount", { total, reference: payment.reference })),
  );
  const methods = [
    ["Wero", payment.wero, t("payment.wero.hint")],
    [t("payment.transfer"), payment.iban && `${payment.iban.replace(/(.{4})/g, "$1 ").trim()} · ${payment.holder}`, t("payment.transfer.hint")],
    ["PayPal", payment.paypal, t("payment.paypal.hint")],
  ].filter(([, value]) => value);
  if (!methods.length) {
    box.append(el("p", t("payment.by_email"), "help"));
    return box;
  }
  const list = el("dl");
  for (const [name, value, hint] of methods) {
    const detail = el("dd");
    detail.append(el("span", value, "payment-value"), el("span", ` (${hint})`, "help"));
    list.append(el("dt", name), detail);
  }
  box.append(list, el("p", t("payment.after"), "help"));
  return box;
}

// A sale's status, once there is one, says more than the request's.
const status = (request) =>
  request.sale_status
    ? t(`requests.sale.${request.sale_status}`, {}, request.status_label)
    : t(`requests.status.${request.status}`, {}, request.status_label);

async function renderRequests() {
  const box = $("requests-body");
  box.replaceChildren(el("p", t("common.loading"), "help"));
  try {
    const requests = await call("/api/me/requests");
    box.replaceChildren();
    if (!requests.length) box.append(el("p", t("requests.none"), "help"));
    for (const request of requests) {
      const section = el("section", undefined, "request");
      section.append(
        el("h3", `${status(request)} · ${euros(request.total_cents)}`),
        el("p", t("requests.sent_on", { date: new Date(request.created_at).toLocaleDateString(t.locale) }), "help"),
      );
      const lines = el("ul", undefined, "lines");
      for (const item of request.items) {
        const outcome = item.outcome && t(`requests.outcome.${item.outcome}`, {}, "");
        lines.append(el("li", `${item.label} · ${euros(item.price_cents)}${outcome ? " · " + outcome : ""}`));
      }
      section.append(lines);
      if (request.decision) section.append(el("p", t("requests.decision", { decision: request.decision })));
      if (request.payment) section.append(paymentBox(request.payment));
      if (request.status === "sent") {
        const cancel = el("button", t("requests.cancel"));
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

function updateFilterUI() {
  const active = FILTERS.filter(([id]) => id !== "sort" && $(id).value.trim()).length;
  $("filter-count").textContent = active ? `(${active})` : "";
  $("filters-clear").hidden = !active && $("sort").value === "recent";
  document.querySelector("lilydex-filter-bar").refreshChips();
}

function updateFacets(result) {
  const extension = $("extension");
  const selected = extension.value;
  const values = new Set(result.extensions || []);
  if (selected) values.add(selected);
  extension.replaceChildren(...["", ...values].map((value) => {
    const option = el("option", value || t("filters.all"));
    option.value = value;
    return option;
  }));
  extension.value = selected;
  for (const [id, values] of [["language", result.languages], ["finish", result.finishes]]) {
    // Safari ignores hidden options in a select: disable them as well.
    for (const option of $(id).options)
      option.hidden = option.disabled = Boolean(option.value) &&
        option.value !== $(id).value && !values?.includes(option.value);
  }
}

function drawHero() {
  const photos = state.items.filter((listing) => listing.items[0].photos.includes("front")).slice(0, 2);
  $("hero-art").hidden = photos.length < 2;
  $("hero-art").replaceChildren(...photos.map((listing) => {
    const image = el("img");
    image.src = photo(listing, listing.items[0], "front", "thumb");
    image.alt = "";
    return image;
  }));
}

function filterLoading() {
  state.loading = true;
  $("filter-apply").disabled = true;
  $("filter-apply").textContent = t("filters.searching");
  $("count").textContent = "";
  $("results-status").textContent = t("results.loading");
  $("results-empty").hidden = true;
  $("results-retry").disabled = true;
  $("more").disabled = true;
}

async function load(reset = true) {
  // Repeated activations must not append the same page twice. A new search can
  // still supersede an in-flight request, including one waiting for its debounce.
  if (!reset && state.loading) return;
  const retryInitiated = document.activeElement === $("results-retry");
  state.offset = reset ? 0 : state.items.length;
  writeFilters();
  const request = ++state.request;
  updateFilterUI();
  filterLoading();
  $("grid").setAttribute("aria-busy", "true");
  const query = new URLSearchParams({
    sort: $("sort").value,
    limit: PAGE,
    offset: state.offset,
  });
  if ($("q").value.trim()) query.set("q", $("q").value.trim());
  if ($("language").value) query.set("language", $("language").value);
  if ($("extension").value) query.set("extension", $("extension").value);
  if ($("finish").value) query.set("finish", $("finish").value);
  if ($("max").value) query.set("max_eur", $("max").value);
  $("error").hidden = true;
  $("filter-error").hidden = true;
  let message = t("error.network");
  let tiles;
  try {
    const response = await fetch("/api/public/listings?" + query);
    message = response.ok ? t("error.response")
      : response.status === 429 ? t("error.too_many_requests")
      : response.status >= 500 ? t("error.server") : t("error.storefront");
    const result = await response.json();
    if (!response.ok) {
      // Known codes are translated, while unknown French details and technical
      // exceptions never become the visitor's error message.
      if (typeof result?.code === "string") message = t(`error.${result.code}`, {}, message);
      else if (Array.isArray(result?.detail)) message = t("error.fields");
      throw new Error(message);
    }
    if (!Array.isArray(result?.items) || !Number.isFinite(result.total) || result.total < 0 ||
        !result.items.every(listing => Array.isArray(listing?.items) && listing.items.length &&
          listing.items.every(item => item && Array.isArray(item.photos))))
      throw new Error(message);
    if (request !== state.request) return; // A newer search already answered.
    const items = reset ? result.items : state.items.concat(result.items);
    // Prepare the replacement before publishing any state. A malformed item or
    // a rendering failure must leave the previous cards available for retry.
    tiles = items.map(tile);
    updateFacets(result);
    state.items = items;
    state.total = result.total;
    state.approximate = Boolean(result.approximate);
  } catch (error) {
    if (request !== state.request) return;
    state.retryReset = reset;
    $("error").textContent = message;
    $("error").hidden = false;
    $("filter-error").textContent = message;
    $("filter-error").hidden = false;
    $("results-retry").hidden = false;
    $("results-status").textContent = state.items.length ? t("results.previous") : "";
    // Previous cards remain useful, but their count and next page cannot be
    // presented as results of the new criteria until the search succeeds.
    $("count").textContent = "";
    document.body.classList.toggle("catalogue-empty", !state.items.length);
    $("more").hidden = true;
    $("filter-apply").textContent = t("filters.retry");
    $("filter-apply").disabled = false;
    return;
  } finally {
    if (request === state.request) {
      state.loading = false;
      $("grid").setAttribute("aria-busy", "false");
      $("more").disabled = false;
      $("results-retry").disabled = false;
    }
  }
  // Chrome may move focus to body when the retry button is disabled. Remember
  // its initiating focus, but leave a field chosen during the request alone.
  const retryFocused = retryInitiated &&
    (document.activeElement === $("results-retry") || document.activeElement === document.body);
  $("results-retry").hidden = true;
  $("results-status").textContent = "";
  $("results-empty").hidden = state.total !== 0;
  document.body.classList.toggle("catalogue-empty", state.total === 0);
  $("grid").replaceChildren(...tiles);
  $("count").textContent = state.total
    ? t("results.count", { count: state.total }) +
      (state.approximate ? t("results.approximate", { q: $("q").value.trim() }) : "")
    : t("results.none");
  $("more").hidden = state.items.length >= state.total;
  $("more").textContent = t("results.more.count", {
    shown: state.items.length.toLocaleString(t.locale),
    total: state.total.toLocaleString(t.locale),
  });
  $("filter-apply").disabled = false;
  $("filter-apply").textContent = t("filters.apply.count", { count: state.total });
  updateFilterUI();
  if (reset) drawHero();
  if ($("detail").open) drawNav();
  if (!reset) $("results-status").textContent = t("results.more.count", {
    shown: state.items.length.toLocaleString(t.locale), total: state.total.toLocaleString(t.locale),
  });
  if (retryFocused) $("results").focus();
}

function closeFilters() {
  document.body.classList.remove("filters-open");
  $("filter-open").setAttribute("aria-expanded", "false");
}
$("filter-open").addEventListener("click", () => {
  document.body.classList.add("filters-open");
  $("filter-open").setAttribute("aria-expanded", "true");
  $("extension").focus();
});
$("filter-close").addEventListener("click", () => {
  closeFilters();
  $("filter-open").focus();
});
$("filter-apply").addEventListener("click", () => {
  if (!$("filter-error").hidden) return load(state.retryReset);
  closeFilters();
  $("filter-open").focus();
});
window.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && document.body.classList.contains("filters-open")) {
    closeFilters();
    $("filter-open").focus();
  }
});
window.matchMedia("(max-width: 700px)").addEventListener("change", (event) => {
  if (!event.matches) closeFilters();
});
function clearFilters() {
  clearTimeout(typing);
  $("filters").reset();
  return load();
}
$("filters-clear").addEventListener("click", clearFilters);
$("filter-reset").addEventListener("click", clearFilters);
$("results-retry").addEventListener("click", () => load(state.retryReset));
$("results-reset").addEventListener("click", () => {
  $("q").focus();
  return clearFilters();
});
$("how-open").addEventListener("click", () => $("how").showModal());
$("account-menu").addEventListener("click", (event) => {
  if (event.target.closest("button[id]")) $("account-menu").open = false;
});

let typing;
$("filters").addEventListener("input", () => {
  clearTimeout(typing);
  // Invalidate the previous response immediately, not only 250 ms later.
  state.request++;
  updateFilterUI();
  filterLoading();
  typing = setTimeout(() => load(), 250);
});
$("filters").addEventListener("submit", (event) => {
  event.preventDefault();
  clearTimeout(typing);
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
  try {
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
    notice.textContent = t("profile.saved");
    notice.hidden = false;
  } catch (error) {
    formError(form, error.message);
  }
  } finally { releaseForm(form); }
});
$("delete-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  try {
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
  $("notice").textContent = t("profile.deleted");
  $("notice").hidden = false;
  } finally { releaseForm(form); }
});
$("logout").addEventListener("click", async () => {
  try {
    await call("/api/logout", { method: "POST" });
  } catch (error) {
    // Without the server's answer the session may still be valid: say so, keep it.
    if (error.status !== 401) {
      const reason = error.status ? error.message : t("logout.no_answer");
      $("error").textContent = t("logout.failed", { reason });
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
  try {
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
  } finally { releaseForm(form); }
});
$("signup-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  try {
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
    notice.textContent = t("signup.sent");
    notice.hidden = false;
  } catch (error) {
    formError(form, error.message);
  }
  } finally { releaseForm(form); }
});
$("basket-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  try {
  formError(form, "");
  const body = {
    listing_ids: state.basket.map((x) => x.id),
    message: form.message.value,
  };
  // A guest's address is read before the form is reset: the answer names it.
  const guest = state.me ? "" : form.email.value.trim();
  try {
    if (state.me) {
      await call("/api/me/requests", { method: "POST", body: JSON.stringify(body) });
    } else {
      await call("/api/public/requests", {
        method: "POST",
        body: JSON.stringify({
          ...body,
          display_name: form.display_name.value.trim(),
          email: guest,
          consent: form.consent.checked,
        }),
      });
    }
    state.basket = [];
    saveBasket();
    form.reset();
    load();
    if (guest) {
      renderBasket();
      $("basket-total").textContent = t("basket.sent", { email: guest });
      $("basket-title").textContent = t("basket.success");
      return;
    }
    $("basket").close();
    renderRequests();
    $("requests").showModal();
  } catch (error) {
    formError(form, error.message);
  }
  } finally { releaseForm(form); }
});
$("password-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  try {
  formError(form, "");
  try {
    await call("/api/public/password", {
      method: "POST",
      body: JSON.stringify({ token: state.link, password: form.password.value }),
    });
  } catch (error) {
    formError(form, error.message);
    return;
  }
  state.link = "";
  form.reset();
  $("password").close();
  await whoAmI();
  $("notice").textContent = t("password.saved");
  $("notice").hidden = false;
  } finally { releaseForm(form); }
});
openLink();
state.basket = readBasket();
renderAccount();
whoAmI();
readFilters();
load();
openFromAddress();

const accountMenu = $("account-menu");
const accountTrigger = accountMenu.querySelector("summary");
document.addEventListener("pointerdown", event => {
  if (!accountMenu.contains(event.target)) accountMenu.open = false;
});
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && accountMenu.open) {
    accountMenu.open = false; accountTrigger.focus();
  }
});
for (const id of ["login", "signup", "account", "requests"]) {
  const dialog = $(id);
  dialog.addEventListener("close", () => accountTrigger.focus());
}
for (const id of ["login-open", "signup-open"]) {
  $(id).addEventListener("click", () => {
    const dialog = $(id.replace("-open", ""));
    dialog.querySelector("input:not([type=hidden])")?.focus();
  });
}

$("basket-browse").addEventListener("click", () => { $("basket").close(); $("q").focus(); });
