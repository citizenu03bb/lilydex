// Exercise the storefront logout listener against a failing, then a working, API.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const { t } = require("./i18n_runtime.cjs");
const source = fs.readFileSync(process.argv[2], "utf8");
const slice = (from, to) => source.slice(source.indexOf(from), source.indexOf(to));
const listener = slice('$("logout").addEventListener(', '$("login-form").addEventListener(');
const elements = {};
let handler, respond;
const context = vm.createContext({
  t,
  fetch: async () => respond(),
  Response,
  state: { me: { role: "client" } },
  renderAccount: () => {},
  $: (id) =>
    (elements[id] ||= {
      hidden: true,
      textContent: "",
      addEventListener: (_, fn) => {
        handler = fn;
      },
    }),
});
vm.runInContext(slice("async function call(", "\nconst euros") + listener, context);
(async () => {
  respond = () => Promise.reject(new TypeError("Failed to fetch"));
  await handler();
  // The server session may still be valid: the page must not claim otherwise.
  assert.deepEqual(context.state.me, { role: "client" });
  assert.equal(elements.error.hidden, false);
  assert.match(elements.error.textContent, /Déconnexion/);
  respond = () => new Response(JSON.stringify({ detail: "Non connecté." }), { status: 401 });
  await handler();
  assert.equal(context.state.me, null); // Already signed out on the server.
  context.state.me = { role: "client" };
  respond = () => new Response(JSON.stringify({ ok: true }), { status: 200 });
  await handler();
  assert.equal(context.state.me, null);
  assert.equal(elements.error.hidden, true);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
