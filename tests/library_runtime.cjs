const fs=require('node:fs'),vm=require('node:vm');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const elements=Object.fromEntries(['search','album','sort','summary','results'].map(id=>[id,{value:id==='sort'?'name':'',textContent:'',innerHTML:'',events:{},addEventListener(type,fn){this.events[type]=fn;}}]));
const context=vm.createContext({document:{getElementById(id){return elements[id];}}});
vm.runInContext(input.script,context);
function snap(){return {summary:elements.summary.textContent,results:elements.results.innerHTML};}
const output=[snap()];
for(const action of input.actions){elements[action.field].value=action.value;elements[action.field].events[action.field==='search'?'input':'change']();output.push(snap());}
process.stdout.write(JSON.stringify(output));
