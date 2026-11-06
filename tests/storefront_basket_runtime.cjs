const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { t } = require('./i18n_runtime.cjs');
const source = fs.readFileSync(process.argv[2], 'utf8');
const slice = (from, to) => source.slice(source.indexOf(from), source.indexOf(to));
let submit;
let responses = [];
const requests = [];
const form = { message: {value: 'Bonjour'}, email: {value: 'invite@example.org'},
 display_name: {value: 'Invité'}, consent: {checked: true}, querySelector: () => ({value:'hand'}), reset(){} };
const elements = {};
const context = vm.createContext({
  t, Response, console,
  state: {me: {email: 'client@example.org'}, basket: []},
  document: {querySelector: () => ({value:'hand'})},
  $: id => elements[id] ||= {addEventListener: (event, handler) => {submit = handler;}, close(){},showModal(){}},
  fetch: async (path, options) => {
    requests.push({path, body:JSON.parse(options.body)});
    const response = responses.shift();
    if (typeof response === 'function') return response();
    if (response instanceof Error) throw response;
    return new Response(JSON.stringify(response?.body ?? response), {status:response?.status || 200});
  },
  saveBasket(){}, renderBasket(){}, renderRequests(){}, load(){}, releaseForm(){},
  formError: (form, message) => {form.error = message;},
});
vm.runInContext(slice('async function call(', '\nconst euros') +
 slice('// A quote never', 'function renderBasket()') +
 slice('$("basket-form").addEventListener("submit"', '$("password-form").addEventListener'), context);
const item = (id='a', price=120) => ({id, label:`Carte ${id}`, price_cents:price, card_count:1});
const quote = (items, unavailable=[]) => ({items, unavailable, delivery:'hand', shipping_cents:0});
const event = () => ({preventDefault(){},target:form});
(async () => {
  // The first click presents changed prices; a second click explicitly accepts them.
  context.state.basket = [item()];
  responses = [quote([item('a', 220)])]; requests.length = 0;
  await submit(event());
  assert.equal(requests.length, 1); assert.equal(requests[0].path, '/api/public/quote');
  assert.equal(context.state.basket[0].price_cents, 220);
  assert.equal(context.state.basket[0].previous_price_cents, 120);
  assert.match(context.state.basketNotice, /prix ont changé/);
  responses = [quote([item('a', 220)]), {id:'demande'}];
  await submit(event());
  assert.equal(requests.at(-1).path, '/api/me/requests');
  assert.deepEqual(requests.at(-1).body.expected_prices, {a:220});
  assert.equal(context.state.basket.length, 0);

  // The guest path carries the same accepted snapshot.
  context.state.me = null; context.state.basket = [item()];
  responses = [quote([item()]), {detail:'envoyé'}];
  await submit(event());
  assert.equal(requests.at(-1).path, '/api/public/requests');
  assert.deepEqual(requests.at(-1).body.expected_prices, {a:120});
  assert.equal(requests.at(-1).body.email, 'invite@example.org');

  // An item disappearing after the quote is named and removed, without auto-submitting.
  context.state.basket = [item(),item('b')];
  responses = [quote([item(),item('b')]), {status:409, body:{code:'basket_changed', quote:quote([item()],['b'])}}];
  await submit(event());
  assert.equal(context.state.basket.length, 1);
  assert.match(context.state.basketNotice, /Carte b/);
  assert.match(form.error, /pendant l’envoi/);

  // Restore revalidates stale local contents, but a network failure never empties them.
  context.state.basket = [item(),item('b')];
  responses = [quote([item()],['b'])]; await context.restoreBasket();
  assert.equal(context.state.basket.length, 1);
  responses = [new Error('network')]; await context.restoreBasket();
  assert.equal(context.state.basket.length, 1);
  assert.match(context.state.basketNotice, /sélection est conservée/);
  requests.length=0; responses = [new Error('network')]; await submit(event());
  assert.equal(requests.length, 1); assert.match(form.error, /Impossible de vérifier/);

  // Render the actual basket with a quote received before shipping configuration.
  class Node {
    constructor(tag, text, className) {this.tag=tag; this.textContent=text; this.className=className; this.children=[];}
    append(...nodes){this.children.push(...nodes);}
    replaceChildren(...nodes){this.children=[...nodes];}
    addEventListener(){} setAttribute(){} after(){}
  }
  const nodes = {};
  const renderContext = vm.createContext({
    t, state:{me:null,basket:[{...item('a',220),previous_price_cents:120}],
      basketNotice:'Les prix ont changé.', basketQuote:{...quote([item('a',220)]),
        delivery:'shipping', registered:true, shipping_cents:729, registered_threshold_cents:5000}},
    shippingRates:null, shippingQuote:()=>null, photo:()=>'/photo', euros:c=>`${c} cents`,
    document:{querySelector:()=>({value:'shipping'})},
    $:id=>nodes[id] ||= new Node('div'), el:(...args)=>new Node(...args), saveBasket(){},
  });
  vm.runInContext(slice('function renderBasket()', '// Shown only while'), renderContext);
  renderContext.renderBasket();
  const firstLine = nodes['basket-items'].children[0];
  assert(firstLine.children.some(node=>node.textContent==='220 cents'));
  assert(firstLine.children.some(node=>node.textContent==='Ancien prix : 120 cents'));
  assert.match(nodes['basket-registered-notice'].textContent, /5000 cents/);
  assert.equal(nodes['basket-updates'].textContent,'Les prix ont changé.');

  // A stale background result cannot re-add an item removed while fetching.
  let finish;
  responses = [() => new Promise(resolve => {finish=resolve;})];
  const pending = context.refreshBasket();
  context.state.basket = [item('new')];
  finish(new Response(JSON.stringify(quote([item('a',999)]))));
  assert.equal(await pending, false);
  assert.equal(context.state.basket[0].id, 'new');
  assert.equal(context.state.basket[0].price_cents,120);
})().catch(error => { console.error(error); process.exit(1); });
