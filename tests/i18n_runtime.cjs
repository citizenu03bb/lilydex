// t() as a page builds it, from the French dictionary, for the storefront runtimes.
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const web = path.resolve(__dirname, "../src/pokeprice/web");
const source = fs.readFileSync(path.join(web, "components.js"), "utf8");
const context = vm.createContext({});
vm.runInContext(source.slice(source.indexOf("function translator("), source.indexOf("\nconst t =")), context);
const messages = JSON.parse(fs.readFileSync(path.join(web, "messages/fr.json"), "utf8"));

module.exports = { t: context.translator(messages, "fr"), translator: context.translator };
