const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[2], "utf8");
// Only the pure helpers: the module body needs the page.
const context = vm.createContext({});
vm.runInContext(
  source.slice(
    source.indexOf("  function neighbour("),
    source.indexOf("  const lastOffset"),
  ),
  context,
);
const { neighbour, pageOffset } = context;
const cell = (row, column) => ({ top: row * 300, left: column * 200, width: 180, height: 280 });

// Four columns, last row incomplete: 0-3, 4-7, 8-9.
const grid = Array.from({ length: 10 }, (_, i) => cell(Math.floor(i / 4), i % 4));
assert.equal(neighbour(grid, 1, 1), 5);
assert.equal(neighbour(grid, 5, -1), 1);
assert.equal(neighbour(grid, 7, 1), 9, "the closest card of a shorter row");
assert.equal(neighbour(grid, 9, 1), -1, "nothing below the last row");
assert.equal(neighbour(grid, 2, -1), -1, "nothing above the first row");

// Editions stack grids of different lengths, each below the previous one.
const stacked = [cell(0, 0), cell(0, 1), cell(1.2, 0), cell(2.4, 0), cell(2.4, 1)];
assert.equal(neighbour(stacked, 1, 1), 2, "next group even if it is shorter");
assert.equal(neighbour(stacked, 2, 1), 3);

assert.equal(pageOffset(0, 40, 85), 80);
assert.equal(pageOffset(40, 40, 39), 0);
assert.equal(pageOffset(13, 40, 60), 53, "pages keep the offset given in the address");
assert.equal(pageOffset(13, 40, 5), 0);
