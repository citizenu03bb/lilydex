const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const { TextDecoder, TextEncoder } = require("node:util");
const source = fs.readFileSync(process.argv[2], "utf8");
const streamSource = source.slice(source.indexOf("  // Server-sent events"), source.indexOf("  // -- V1.1, contexte"));

function element(text = "") {
  const classes = new Set();
  return { textContent: text, children: [], value: "", disabled: false,
    classList: { add: (s) => classes.add(s), remove: (s) => classes.delete(s), contains: (s) => classes.has(s) },
    replaceChildren(...items) { this.children = items; }, append(...items) { this.children.push(...items); } };
}
function setup(blocks, { breakRead = false } = {}) {
  const controls = Object.fromEntries(["chat-input", "chat-suggestions", "chat-tool"].map((id) => [id, element()]));
  const answers = [], bodies = [];
  const chat = { enabled: true, busy: false, id: null };
  const transport = { reads: 0, cancelled: 0, released: 0 };
  const context = vm.createContext({ chat, TextDecoder, Uint8Array,
    $: (id) => controls[id], resize() {}, scrollDown() {}, usage() {}, flagControl() {}, showAccess() {},
    questionContext: async () => ({}),
    bubble(role) { const body = element(); body.parentElement = element(); if (role === "assistant") answers.push(body); return body; },
    renderAnswer(node, text) { node.replaceChildren(element(text)); },
    el: (tag, text) => element(text), t: (key, args) => args ? `${key}:${args.message}` : key,
    setBusy(busy) { chat.busy = busy; },
    fetch: async (url, options) => {
      bodies.push(JSON.parse(options.body));
      let index = 0;
      return { ok: true, body: { getReader: () => ({ read: async () => {
        transport.reads++;
        if (index < blocks.length) return { done: false, value: new TextEncoder().encode(blocks[index++]) };
        if (breakRead) throw new Error("network lost");
        return { done: true };
      }, cancel: async () => { transport.cancelled++; }, releaseLock() { transport.released++; } }) } };
    },
  });
  vm.runInContext(streamSource, context);
  return { context, answers, bodies, chat, transport };
}
const start = 'event: start\ndata: {"conversation_id":"conversation-1"}\n\n';
const text = 'event: text\ndata: {"text":"Une partie de la réponse"}\n\n';
const done = 'event: done\ndata: {"conversation_id":"conversation-1","message_id":12}\n\n';
(async () => {
  for (const [blocks, breakRead] of [[[start, text], false], [[start], false], [[start, text], true]]) {
    const run = setup(blocks, { breakRead });
    await run.context.send("question");
    assert.equal(run.chat.id, "conversation-1");
    assert.equal(run.chat.busy, false);
    const answer = run.answers[0];
    assert(answer.parentElement.classList.contains("chat-incomplete"));
    assert(!answer.parentElement.classList.contains("chat-pending"));
    if (blocks.includes(text)) assert.equal(answer.children[0].textContent, "Une partie de la réponse");
    const retry = answer.children.at(-1);
    assert.equal(retry.textContent, "chat.retry");
    retry.onclick();
    retry.onclick();
    await new Promise(setImmediate);
    assert.equal(run.bodies.length, 2);
    assert.equal(run.bodies[1].conversation_id, "conversation-1");
    assert.equal(run.transport.cancelled, 2);
    assert.equal(run.transport.released, 2);
  }
  for (const breakRead of [false, true]) {
    // done is authoritative: a later transport error cannot turn success into
    // an incomplete answer and invite a duplicate question.
    const complete = setup([start.slice(0, 15), start.slice(15) + text, done], { breakRead });
    await complete.context.send("question");
    assert(!complete.answers[0].parentElement.classList.contains("chat-incomplete"));
    assert(!complete.answers[0].parentElement.classList.contains("chat-pending"));
    assert.equal(complete.answers[0].children.length, 1);
    assert.equal(complete.transport.reads, 3);
    assert.equal(complete.transport.cancelled, 1);
    assert.equal(complete.transport.released, 1);
  }
})().catch((error) => { console.error(error); process.exit(1); });
