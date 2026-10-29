// Exercise the real responsive-image helper: public variants, sizes and JPEG recovery.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.handlers = {}; this.hidden = false; }
  append(child) { this.children.push(child); child.parentNode = this; }
  addEventListener(name, fn) { this.handlers[name] = fn; }
  closest(tag) { return this.tag === tag ? this : this.parentNode?.closest(tag); }
  querySelectorAll(tag) { return this.children.flatMap(c => [...(c.tag === tag ? [c] : []), ...c.querySelectorAll(tag)]); }
  querySelector(selector) { return this.children.find(c => selector === '.photo-retry' && c.className === 'photo-retry'); }
  remove() { this.parentNode.children = this.parentNode.children.filter(c => c !== this); }
}
const code = fs.readFileSync(process.argv[2], 'utf8');
const context = vm.createContext({
  el: (tag, text, cls) => Object.assign(new Node(tag), { textContent: text, className: cls }),
  t: key => key, encodeURIComponent, state: {},
});
vm.runInContext(code.slice(code.indexOf('function watchPhoto('), code.indexOf('function facts(')), context);
const variants = [
  { size: 'thumb', format: 'jpeg', width: 265, height: 392, url: '/photo/thumb' },
  { size: 'grid2', format: 'jpeg', width: 530, height: 784, url: '/photo/grid2.jpg' },
  { size: 'grid2', format: 'webp', width: 530, height: 784, url: '/photo/grid2.webp' },
  { size: 'view', format: 'jpeg', width: 640, height: 946, url: '/photo/view.jpg' },
  // A source smaller than view2 still advertises its actual width.
  { size: 'view2', format: 'jpeg', width: 800, height: 1183, url: '/photo/view2.jpg' },
  { size: 'view2', format: 'webp', width: 800, height: 1183, url: '/photo/view2.webp' },
];
const item = { index: 0, media: { front: { width: 800, height: 1183, variants } } };
const holder = new Node('div');
const grid = context.adaptivePhoto({ id: 'public' }, item, 'front', 'grid');
holder.append(grid);
const gridImage = grid.children.find(c => c.tag === 'img');
assert.equal(gridImage.loading, 'lazy');
assert.equal(gridImage.srcset, '/photo/thumb 265w, /photo/grid2.jpg 530w');
assert(!gridImage.srcset.includes('full'));
assert(!gridImage.srcset.includes('view'));
assert.equal(grid.querySelectorAll('source').length, 0);
assert.equal(gridImage.width, 800);
assert.equal(gridImage.height, 1183);
gridImage.handlers.error();
assert.equal(gridImage.hidden, true);
assert.equal(holder.children[1].textContent, 'photo.unavailable');
const detail = context.adaptivePhoto({ id: 'public' }, item, 'front', 'detail', 'Front', true);
const detailImage = detail.children.find(c => c.tag === 'img');
holder.children = [];
holder.append(detail);
detailImage.handlers.error();
assert.equal(detail.querySelectorAll('source').length, 0); // optional WebP fails, JPEG remains
assert.equal(holder.children.length, 1);
assert.equal(detailImage.srcset, '/photo/view.jpg 640w, /photo/view2.jpg 800w');
assert(!detailImage.srcset.includes('1280w'));
assert(!detailImage.srcset.includes('full'));
assert.equal(detailImage.alt, 'Front');
const legacy = context.adaptivePhoto({ id: 'public' }, { index: 0 }, 'front', 'detail');
assert.match(legacy.children[0].src, /size=full$/);
