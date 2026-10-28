const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[2], 'utf8');
let capture;
const context = vm.createContext({
 document: {addEventListener: (name, handler) => { if(name === 'submit') capture = handler; }},
 t: () => 'Sending',
 el: () => ({setAttribute(){},textContent:''}),
});
vm.runInContext(source.slice(source.indexOf('const pendingForms'),source.indexOf('// The basket is')),context);
const form = id => ({id, method:'post', attributes:{}, querySelector(){return this.status;},append(status){this.status=status;},setAttribute(k,v){this.attributes[k]=v;},removeAttribute(k){delete this.attributes[k];}});
const event = target => ({target, prevented:false, stopped:false,preventDefault(){this.prevented=true;},stopImmediatePropagation(){this.stopped=true;}});
for(const id of ['login-form','signup-form','basket-form','password-form']) {
 const f=form(id), first=event(f), second=event(f);
 capture(first); capture(second);
 assert(!first.prevented); assert(second.prevented && second.stopped);
 assert.equal(f.attributes['aria-busy'],'true');
 context.releaseForm(f);
 const retry=event(f);capture(retry);assert(!retry.prevented);
 context.releaseForm(f);
}
const filters=form('filters');capture(event(filters));const repeated=event(filters);capture(repeated);assert(!repeated.prevented);
