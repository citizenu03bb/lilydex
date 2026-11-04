"use strict";
// The management chat, V1 (assistant.py, docs/APP.md « Assistant »): a full
// screen panel on the phone. It reads and explains; it writes nothing. The
// answer streams from POST /api/assistant as server-sent events: text, tool,
// card, done, error. Uses app.js's $, el, t, toast, openDetail and editAllowed.
const Assistant = (() => {
  const chat = { user: null, enabled: false, loaded: false, busy: false, id: null };
  const CITED = /\[([A-Za-z0-9_-]{1,120})\]/g;

  // Plain text only: the model is asked for no Markdown, the rest is cleaned here.
  const plain = (text) =>
    text
      .replace(/\*\*(.+?)\*\*/g, "$1")
      .replace(/^\s*[*-] /gm, "• ")
      .replace(/`([^`]+)`/g, "$1")
      .replace(/« /g, "«\u00a0")
      .replace(/ ([»:;?!])/g, "\u00a0$1");
  const cardLabel = (card) => [card.name, card.number].filter(Boolean).join(" ") || t("chat.open_card");

  function cardButton(card) {
    const button = el("button", cardLabel(card), "chat-card");
    button.type = "button";
    button.title = t("chat.open_card");
    button.onclick = () => openDetail(card.copy_id).catch((e) => toast(e.message));
    return button;
  }

  // An id the server confirmed becomes a link to its card; any other stays text.
  function renderAnswer(node, text, cards) {
    const known = new Map(cards.map((c) => [c.copy_id, c]));
    const body = plain(text);
    const parts = [];
    let last = 0;
    for (const match of body.matchAll(CITED)) {
      const card = known.get(match[1]);
      if (!card) continue;
      parts.push(document.createTextNode(body.slice(last, match.index)), cardButton(card));
      last = match.index + match[0].length;
    }
    parts.push(document.createTextNode(body.slice(last)));
    const paragraph = el("p", undefined, "chat-text");
    paragraph.append(...parts);
    node.replaceChildren(paragraph);
    const inline = new Set([...body.matchAll(CITED)].map((m) => m[1]));
    const rest = cards.filter((c) => !inline.has(c.copy_id));
    if (rest.length) {
      const row = el("div", undefined, "chat-cards");
      row.append(...rest.map(cardButton));
      node.append(row);
    }
  }

  function bubble(role, text = "", cards = []) {
    const item = el("li", undefined, `chat-message chat-${role}`);
    item.append(el("span", role === "user" ? t("chat.you") : t("chat.assistant"), "chat-who"));
    const body = el("div", undefined, "chat-body");
    if (role === "user") body.append(el("p", text, "chat-text"));
    else renderAnswer(body, text, cards);
    item.append(body);
    $("chat-log").append(item);
    return body;
  }

  function scrollDown() {
    const box = $("chat-scroll");
    box.scrollTop = box.scrollHeight;
  }

  function usage(u) {
    if (!u) return;
    const tokens = u.last_30_days.input_tokens + u.last_30_days.output_tokens;
    $("chat-usage").textContent = t("chat.usage", {
      questions: u.today.questions,
      limit: u.daily_limit,
      tokens: tokens.toLocaleString(t.locale),
    });
  }

  function suggestions() {
    const box = $("chat-suggestions");
    box.hidden = !chat.enabled || $("chat-log").children.length > 0;
    if (box.children.length) return;
    for (const key of ["waiting", "sales", "why"]) {
      const button = el("button", t(`chat.suggest.${key}`), "chat-suggestion");
      button.type = "button";
      button.onclick = () => {
        if (key === "why") {
          // A blank to fill: the cursor waits where the card's name goes.
          const start = t("chat.suggest.why_start");
          $("chat-input").value = start + t("chat.suggest.why_end");
          $("chat-input").focus();
          $("chat-input").setSelectionRange(start.length, start.length);
        } else send(t(`chat.suggest.${key}`));
      };
      box.append(button);
    }
  }

  function setBusy(busy, tool) {
    chat.busy = busy;
    $("chat-send").disabled = busy || !chat.enabled;
    $("chat-input").disabled = !chat.enabled;
    $("chat-tool").hidden = !busy;
    if (busy) $("chat-tool").textContent = tool ? t(`chat.tool.${tool}`, {}, t("chat.tool.unknown")) : t("chat.thinking");
  }

  async function load() {
    const state = await api("/assistant");
    chat.enabled = state.enabled;
    chat.loaded = true;
    $("chat-off").hidden = state.enabled;
    $("chat-log").replaceChildren();
    chat.id = state.conversation?.id || null;
    for (const m of state.conversation?.messages || []) bubble(m.role, m.text, m.cards);
    usage(state.usage);
    suggestions();
    setBusy(false);
    scrollDown();
  }

  // Server-sent events over fetch: a POST, so no EventSource.
  async function* events(response) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      let end;
      while ((end = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
        const fields = Object.fromEntries(
          block.split("\n").map((line) => [line.slice(0, line.indexOf(": ")), line.slice(line.indexOf(": ") + 2)]),
        );
        if (fields.event) yield [fields.event, JSON.parse(fields.data || "{}")];
      }
      if (done) return;
    }
  }

  async function send(question) {
    question = question.trim();
    if (!question || chat.busy || !chat.enabled) return;
    $("chat-input").value = "";
    resize();
    bubble("user", question);
    $("chat-suggestions").hidden = true;
    const answer = bubble("assistant");
    answer.parentElement.classList.add("chat-pending");
    scrollDown();
    setBusy(true);
    let text = "";
    const cards = [];
    const fail = (message) => {
      answer.replaceChildren(el("p", t("chat.error", { message }), "chat-text error"));
      answer.parentElement.classList.remove("chat-pending");
    };
    try {
      const response = await fetch("/api/assistant", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({ question, conversation_id: chat.id }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        if (response.status === 401) showAccess();
        if (response.status === 404) chat.id = null; // The conversation was erased elsewhere.
        fail(body.detail || `HTTP ${response.status}`);
        return;
      }
      for await (const [kind, data] of events(response)) {
        if (kind === "text") {
          text += data.text;
          renderAnswer(answer, text, cards);
          answer.parentElement.classList.remove("chat-pending");
          setBusy(true);
          $("chat-tool").textContent = t("chat.thinking");
        } else if (kind === "tool") setBusy(true, data.tool);
        else if (kind === "card") {
          cards.push(data);
          renderAnswer(answer, text, cards);
        } else if (kind === "done") {
          chat.id = data.conversation_id;
          usage(data.usage);
        } else if (kind === "error") fail(data.message);
        scrollDown();
      }
    } catch (error) {
      fail(error.message);
    } finally {
      setBusy(false);
      scrollDown();
    }
  }

  function resize() {
    const input = $("chat-input");
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 140) + "px";
  }

  async function open() {
    $("chat-dialog").showModal();
    try {
      if (!chat.loaded) await load();
    } catch (error) {
      toast(error.message);
    }
    if (chat.enabled && matchMedia("(pointer: fine)").matches) $("chat-input").focus();
  }

  function attach(user) {
    chat.user = user;
    chat.loaded = false;
    chat.id = null;
    $("chat-open").hidden = !user || !editAllowed();
    if (!user && $("chat-dialog").open) $("chat-dialog").close();
  }

  $("chat-open").onclick = () => open();
  $("chat-close").onclick = () => $("chat-dialog").close();
  $("chat-new").onclick = () => {
    if (chat.busy) return;
    chat.id = null;
    $("chat-log").replaceChildren();
    suggestions();
    $("chat-input").focus();
  };
  $("chat-erase").onclick = async () => {
    if (chat.busy || !confirm(t("chat.erase_confirm"))) return;
    try {
      await api("/assistant/conversations", { method: "DELETE" });
      chat.loaded = false;
      await load();
      toast(t("chat.erased"));
    } catch (error) {
      toast(error.message);
    }
  };
  $("chat-form").onsubmit = (event) => {
    event.preventDefault();
    send($("chat-input").value);
  };
  $("chat-input").addEventListener("input", resize);
  $("chat-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing && matchMedia("(pointer: fine)").matches) {
      event.preventDefault();
      send($("chat-input").value);
    }
  });
  if (state.user) attach(state.user);
  return { attach, open };
})();
