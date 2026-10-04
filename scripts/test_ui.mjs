import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const elements = new Map();
const element = selector => {
  if (!elements.has(selector)) elements.set(selector, {
    innerHTML:'', textContent:'', open:false,
    addEventListener(){}, insertAdjacentHTML(_position, text){this.innerHTML += text;},
    close(){this.open=false;}, showModal(){this.open=true;},
    classList:{add(){},remove(){}},
  });
  return elements.get(selector);
};
const store = () => {const data=new Map();return {getItem:k=>data.get(k) ?? null,setItem:(k,v)=>data.set(k,v),removeItem:k=>data.delete(k)};};
const fixture = {
  repo:'owner/math',actor:{login:'owner'},agents:[{id:'worker',name:'Alice'}],
  projects:[{id:'math',name:'Math',repo:'owner/math',description:'Proofs',revision:7,agents:[],events:[],tasks:[
    {id:'aaaaaaaaaaaa',title:'<img src=x onerror=alert(1)>',criteria:'Prove it',priority:1,status:'active',agent:'worker',revision:3,parent:null,dependencies:[],blocked_by:[],notes:[],lease:2000000000},
    {id:'bbbbbbbbbbbb',title:'Dependent proof',criteria:'Use the first proof',priority:2,status:'queued',revision:1,parent:null,dependencies:['aaaaaaaaaaaa'],blocked_by:['aaaaaaaaaaaa'],notes:[]},
  ]}],
};
let receipt={status:'pending',request_id:'c'.repeat(32),result:{}};
let posts=0;
const context=vm.createContext({
  document:{querySelector:element,addEventListener(){}},
  location:{hash:'#session=test',pathname:'/'},history:{replaceState(){}},
  sessionStorage:store(),localStorage:store(),URL,URLSearchParams,
  crypto:{randomUUID:()=> 'd'.repeat(32)},setTimeout(){},setInterval(){},
  fetch:async(path, options)=>{
    if(options.method==='POST'){posts++;return {ok:true,json:async()=>({id:'d'.repeat(32)})};}
    const result=path==='/api/state'?fixture:path.includes('/api/jobs/')?{status:'finished',result:{status:'pending',request_id:'c'.repeat(32)}}:receipt;
    return {ok:true,json:async()=>structuredClone(result)};
  },
});
vm.runInContext(readFileSync('hivemind/web/app.js','utf8'),context);
await new Promise(resolve=>setImmediate(resolve));
vm.runInContext("projectId='math';taskId='aaaaaaaaaaaa';render()",context);
assert.match(element('#main').innerHTML,/queue revision 7/);
assert.match(element('#queue').innerHTML,/&lt;img/);
assert.doesNotMatch(element('#queue').innerHTML,/<img/);
assert.match(element('#task-detail').innerHTML,/Alice/);
assert.equal(vm.runInContext("status(state.projects[0].tasks[1])",context),'blocked');
vm.runInContext("save(key('draft:math:new'),{title:'Original'});",context);
await vm.runInContext("run('add',{title:'Original',criteria:'Proof'},'Original',key('draft:math:new'))",context);
assert.equal(posts,1);
assert.equal(vm.runInContext('requests[0].status',context),'pending');
receipt={status:'rejected',message:'Task revision conflict',request_id:'c'.repeat(32),result:{}};
await vm.runInContext('pollRequests()',context);
assert.equal(vm.runInContext('requests[0].status',context),'rejected');
assert.match(element('#main').innerHTML,/Task revision conflict/);
assert.equal(vm.runInContext("saved(key('draft:math:new')).title",context),'Original');
// An old accepted request must never erase a newer edit of the same draft.
vm.runInContext("requests[0].status='pending';save(key('draft:math:new'),{title:'Newer'})",context);
receipt={status:'accepted',request_id:'c'.repeat(32),result:{id:'eeeeeeeeeeee'}};
await vm.runInContext('pollRequests()',context);
assert.equal(vm.runInContext('requests[0].status',context),'accepted');
assert.equal(vm.runInContext("saved(key('draft:math:new')).title",context),'Newer');
vm.runInContext("requests[0].status='pending';save(key('draft:math:new'),{title:'Original'})",context);
await vm.runInContext('pollRequests()',context);
assert.equal(vm.runInContext("saved(key('draft:math:new'))",context),null);
assert.equal(posts,1,'Receipt polling must never replay writes');
console.log('UI checks passed: rendering, escaping, dependencies, pending/rejected/accepted receipts, and draft preservation.');
