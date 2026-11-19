"use strict";

// The management assistant, V0 (todo.py): what the agents did since yesterday,
// then « À toi », the few decisions left to a person, each with the button
// that opens the screen where it is made. Phone first: three items, then more.
const todoState = { open: false, brief: null };
const assistantShown = () =>
  editAllowed() && ["collection", "sales"].includes(state.view || "collection") && !!todoState.brief;
function todoMoney(cents) {
  return (cents / 100).toLocaleString(t.locale, { style: "currency", currency: "EUR" });
}
function todoDone(done) {
  const sold = done.sales.transitions.sold || 0,
    shipped = done.sales.transitions.shipped || 0;
  return [
    done.agent.confirmed && t("todo.done.confirmed", { count: done.agent.confirmed }),
    done.listings.published && t("todo.done.published", { count: done.listings.published }),
    done.listings.unpublished && t("todo.done.unpublished", { count: done.listings.unpublished }),
    done.requests.received && t("todo.done.received", { count: done.requests.received }),
    sold && t("todo.done.sold", { count: sold, amount: todoMoney(done.sales.sold_cents) }),
    shipped && t("todo.done.shipped", { count: shipped }),
  ].filter(Boolean);
}
function todoText(item) {
  const d = item.data || {};
  if (item.kind === "photo")
    return {
      title: `${d.name} ${d.number}`,
      detail: t("photo_requests.place", { album: d.album, page: d.page, position: d.position }) +
        " · " + t(`photo_requests.view.${photoRequestViews.includes(d.view) ? d.view : "front"}`),
      reason: item.reason,
    };
  if (item.kind === "request")
    return {
      title: t("todo.item.request", { count: d.cards, total: todoMoney(d.total_cents) }),
      reason: t("todo.reason.request", {
        date: new Date(d.expires_at).toLocaleDateString(t.locale, { weekday: "long", day: "numeric", month: "long" }),
      }),
    };
  if (item.kind === "ship")
    return { title: t("todo.item.ship", { title: d.title }), reason: t("todo.reason.ship") };
  if (item.kind === "payment")
    return {
      title: t("todo.item.payment", { title: d.title, total: todoMoney(d.total_cents) }),
      reason: d.paid ? t("todo.reason.paid") : t("todo.reason.payment"),
    };
  return { title: item.title, reason: item.reason };
}
async function followTodo(action) {
  if (action.view && action.view !== state.view) {
    changeView(action.view);
    if (action.view === "sales") await loadSales();
  }
  if (action.view === "collection" && action.copy_id && !document.getElementById(action.target))
    await refreshPhotoRequests();
  const target = action.target && document.getElementById(action.target);
  if (target) {
    for (const old of document.querySelectorAll(".todo-focus")) old.classList.remove("todo-focus");
    target.classList.add("todo-focus");
    target.scrollIntoView({ behavior: "smooth", block: "center" });
  } else if (action.copy_id) await openDetail(action.copy_id);
  else toast(t("todo.gone"));
}
// Not a decision of the server's queue: this device does not get the notifications.
async function pushOfferCard() {
  const offer = await window.lilydexPush?.offer?.().catch(() => null);
  if (!offer) return null;
  const card = el("div", undefined, "todo-item todo-notify");
  const body = el("div", undefined, "todo-body");
  body.append(
    el("span", t("todo.kind.notify"), "badge"),
    el("strong", t(`todo.notify.${offer}.title`)),
    el("span", t(`todo.notify.${offer}.reason`), "todo-reason"),
  );
  const go = el("button", t(`todo.notify.${offer}.action`), "primary");
  go.type = "button";
  go.onclick = () => {
    const done = offer === "install" ? window.lilydexPush.install() : window.lilydexPush.enable();
    Promise.resolve(done)
      .then(() => refreshTodo())
      .catch((e) => toast(e.message));
  };
  const later = el("button", t("todo.notify.later"), "quiet");
  later.type = "button";
  later.onclick = () => {
    window.lilydexPush.pause();
    card.remove();
  };
  const actions = el("div", undefined, "todo-notify-actions");
  actions.append(go, later);
  card.append(body, actions);
  return card;
}
async function refreshTodo() {
  const box = $("assistant");
  if (!box) return;
  if (!editAllowed()) {
    box.hidden = true;
    return;
  }
  const brief = (todoState.brief = await api("/todo"));
  box.hidden = !assistantShown();
  const done = todoDone(brief.done_since);
  const banner = el("div", undefined, "brief-banner");
  const heading = el("h2", t("todo.brief.title"));
  heading.id = "assistant-title";
  const summary = el(
    "p",
    brief.waiting.length
      ? t("todo.brief.waiting", { count: brief.waiting.length, minutes: brief.minutes })
      : t("todo.brief.nothing"),
    "brief-waiting",
  );
  banner.append(heading, summary, el("p", done.length ? done.join(" · ") : t("todo.done.none"), "help"));
  box.replaceChildren(banner);
  // Never awaited: a service worker not ready yet must not hold the queue back.
  pushOfferCard()
    .then((card) => card && banner.isConnected && banner.after(card))
    .catch(() => {});
  if (!brief.waiting.length) return;
  const queueTitle = el("h3", t("todo.queue.title"));
  const list = el("ol", undefined, "todo-queue");
  const shown = todoState.open ? brief.waiting : brief.waiting.slice(0, 3);
  for (const item of shown) {
    const text = todoText(item);
    const card = el("li", undefined, `todo-item todo-${item.kind}`);
    const body = el("div", undefined, "todo-body");
    body.append(
      el("span", t(`todo.kind.${item.kind}`, {}, item.kind), "badge"),
      el("strong", text.title),
    );
    if (text.detail) body.append(el("span", text.detail, "todo-detail"));
    body.append(el("span", text.reason, "todo-reason"));
    const go = el("button", t(`todo.action.${item.kind}`, {}, t("todo.action.open")), "primary");
    go.type = "button";
    go.onclick = () => followTodo(item.action).catch((e) => toast(e.message));
    card.append(body, el("small", t("todo.minutes", { count: item.minutes }), "todo-minutes"), go);
    list.append(card);
  }
  box.append(queueTitle, list);
  if (brief.waiting.length > 3) {
    const more = el(
      "button",
      todoState.open ? t("todo.queue.less") : t("todo.queue.more", { count: brief.waiting.length - 3 }),
      "quiet",
    );
    more.type = "button";
    more.onclick = () => {
      todoState.open = !todoState.open;
      refreshTodo().catch((e) => toast(e.message));
    };
    box.append(more);
  }
}
