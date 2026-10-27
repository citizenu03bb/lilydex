// Exercise the storefront viewer: neighbours, the end of a loaded page, a lot's photos.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[2], "utf8");
const slice = (from, to) => source.slice(source.indexOf(from), source.indexOf(to));
const card = (id, photos = ["front", "back"]) => ({
  id,
  items: [{ index: 0, name: id, photos }],
});
const elements = {};
const shown = [];
let loads = 0;
const context = vm.createContext({
  el: (tag, text) => ({ tag, textContent: text }),
  photo: (listing, item, side) => `${listing.id}/${item.index}/${side}`,
  Image: class {},
  state: { items: [card("a"), card("b")], total: 3 },
  $: (id) =>
    (elements[id] ||= {
      open: true,
      hidden: false,
      disabled: false,
      textContent: "",
      replaceChildren(...children) {
        this.children = children;
      },
    }),
  load: async () => {
    loads++;
    context.state.items.push(card("c"));
  },
  show: (listing) => {
    shown.push(listing.id);
    context.state.current = listing;
  },
});
vm.runInContext(slice("function faces(", "function show("), context);
(async () => {
  const { state } = context;
  state.current = state.items[0];
  context.drawNav();
  assert.equal(elements["detail-previous"].disabled, true);
  assert.equal(elements["detail-next"].disabled, false);
  assert.equal(elements["detail-position"].textContent, "1 / 3");
  await context.step(1);
  await context.step(1); // Past the loaded page: the next one is fetched first.
  assert.deepEqual(shown, ["b", "c"]);
  assert.equal(loads, 1);
  context.drawNav();
  assert.equal(elements["detail-next"].disabled, true);
  await context.step(1);
  assert.deepEqual(shown, ["b", "c"]);
  // A card opened from its address, outside the list: no neighbours offered.
  state.current = card("z");
  context.drawNav();
  assert.equal(elements["detail-next"].hidden, true);
  // A lot shows every photo of every card in turn.
  state.current = { id: "lot", items: [card("x").items[0], { index: 1, name: "y", photos: ["front"] }] };
  state.face = 0;
  context.drawFace();
  assert.equal(elements["detail-flip"].hidden, false);
  context.flip();
  context.flip();
  assert.equal(state.face, 2);
  assert.match(elements["detail-caption"].textContent, /Recto · y/);
  context.flip();
  assert.equal(state.face, 0);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
