// Exercise the actual API client against HTTP response bodies, without a browser.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[2], "utf8");
const apiSource = source.slice(
  source.indexOf("async function api("),
  source.indexOf("\nfunction toast("),
);
let response,
  request,
  accessPrompts = 0;
const context = vm.createContext({
  fetch: async (url, options) => {
    request = { url, options };
    return response;
  },
  showAccess: () => {
    accessPrompts++;
  },
});
vm.runInContext(apiSource, context);
async function error(body, status, path, expected) {
  response = new Response(body, { status });
  await assert.rejects(context.api(path), { message: expected });
}
(async () => {
  response = new Response(JSON.stringify({ username: "test", role: "admin" }), {
    status: 200,
  });
  assert.equal(
    (await context.api("/setup", { method: "POST", body: "{}" })).role,
    "admin",
  );
  assert.equal(request.url, "/api/setup");
  assert.equal(request.options.credentials, "same-origin");
  assert.equal(request.options.headers["Content-Type"], "application/json");
  await error(
    "",
    200,
    "/setup",
    "Réponse vide du serveur (HTTP 200). Actualisez la page puis réessayez.",
  );
  await error(
    "<html>Proxy error</html>",
    200,
    "/setup",
    "Réponse illisible du serveur (HTTP 200). Actualisez la page puis réessayez.",
  );
  await error(
    "null",
    200,
    "/setup",
    "Réponse vide du serveur (HTTP 200). Actualisez la page puis réessayez.",
  );
  await error("", 403, "/setup", "La demande n’a pas abouti (HTTP 403).");
  await error(
    JSON.stringify({ detail: "Connectez-vous." }),
    401,
    "/copies",
    "Connectez-vous.",
  );
  assert.equal(accessPrompts, 1);
  await error(
    JSON.stringify({ detail: "Identifiants incorrects." }),
    401,
    "/login",
    "Identifiants incorrects.",
  );
  assert.equal(accessPrompts, 1);
  await error(
    JSON.stringify({
      detail: [{ loc: ["body", "password"], msg: "Mot de passe trop court" }],
    }),
    422,
    "/setup",
    "password : Mot de passe trop court",
  );
  console.log("API registration response checks passed");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
