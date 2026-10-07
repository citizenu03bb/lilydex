// Run generated report event handlers against a minimal DOM, without a browser or network.
const vm = require('node:vm');
const input = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
function element(attrs = {}) {
  return {
    innerHTML: '', textContent: '', value: '', checked: 'checked' in attrs,
    hidden: 'hidden' in attrs, disabled: 'disabled' in attrs, open: false,
    dataset: attrs['data-filter'] ? {filter: attrs['data-filter']} : {},
    events: {}, classList: {add() {}, remove() {}},
    addEventListener(type, fn) {this.events[type] = fn;},
    showModal() {this.open = true;}, close() {this.open = false;}
  };
}
const elements = Object.fromEntries(Object.entries(input.elements).map(([id, attrs]) => [id, element(attrs)]));
const filters = input.filters.map(element);
const options = input.options.map(element);
const context = vm.createContext({document: {
  getElementById(id) {if (!(id in elements)) throw Error('Missing DOM element: ' + id); return elements[id];},
  querySelectorAll(selector) {return selector === '.filter-btn' ? filters : options;}
}});
vm.runInContext(input.script, context);
function snapshot() {
  return {grid: elements.cardsGrid.innerHTML, modal: elements.modalDetails.innerHTML,
    panelHidden: elements.simulationPanel.hidden, sort: elements.sortSelect.value,
    options: options.map(o => ({hidden: o.hidden, disabled: o.disabled}))};
}
const result = [snapshot()];
for (const action of input.actions) {
  if (action.type === 'toggle') {
    elements.simulationToggle.checked = action.value;
    elements.simulationToggle.events.change();
  } else if (action.type === 'sort') {
    elements.sortSelect.value = action.value;
    elements.sortSelect.events.change({target: elements.sortSelect});
  } else if (action.type === 'filter') {
    filters.find(b => b.dataset.filter === action.value).events.click();
  } else if (action.type === 'search') {
    elements.searchInput.value = action.value;
    elements.searchInput.events.input({target: elements.searchInput});
  } else if (action.type === 'zoom') {
    vm.runInContext('openZoom(' + Number(action.id) + ')', context);
  }
  result.push(snapshot());
}
process.stdout.write(JSON.stringify(result));
