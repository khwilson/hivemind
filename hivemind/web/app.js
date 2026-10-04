const $ = s => document.querySelector(s);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fragment = new URLSearchParams(location.hash.slice(1));
const token = fragment.get('session') || sessionStorage.getItem('hivemind-ui-session') || '';
if (fragment.has('session')) {sessionStorage.setItem('hivemind-ui-session',token); history.replaceState(null,'',location.pathname);}
let state={projects:[],agents:[]}, projectId=null, taskId=null, query='', requests=[], loading=false;
const project=()=>state.projects.find(p=>p.id===projectId);
const task=()=>project()?.tasks.find(t=>t.id===taskId);
const ready=t=>t.status==='queued' && !(t.blocked_by || []).length;
const status=t=>t.status==='queued' ? ready(t)?'ready':'blocked' : t.status;
const worker=id=>state.agents.find(a=>a.id===id)?.name || id || 'Unclaimed';
const badge=s=>`<span class="badge ${esc(s)}">${esc(s)}</span>`;
const key=suffix=>`hivemind-ui:${state.repo}:${suffix}`;
const saved=k=>{try{return JSON.parse(localStorage.getItem(k));}catch{return null;}};
const save=(k,v)=>localStorage.setItem(k,JSON.stringify(v));
const link=url=>{try{const u=new URL(url);return u.protocol==='https:' && u.hostname==='github.com'?esc(u.href):'#';}catch{return '#';}};
async function api(path,body) {
  const response=await fetch(path,{method:body===undefined?'GET':'POST',headers:{'X-Hivemind-Session':token,'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)})});
  const result=await response.json();
  if(!response.ok) throw Error(result.error || (Array.isArray(result.detail)?result.detail.map(e=>`${e.loc.slice(1).join('.')}: ${e.msg}`).join('; '):result.detail) || 'Request failed');
  return result;
}
function toast(message){$('#toast').textContent=message;$('#toast').classList.add('show');setTimeout(()=>$('#toast').classList.remove('show'),6000);}
async function load(){
  if(loading)return;loading=true;
  try{const first=!state.repo;state=await api('/api/state');if(first)requests=saved(key('requests')) || [];$('#connection').textContent=`Live GitHub queue · updated ${new Date().toLocaleTimeString()}`;if(!$('#modal').open)render();}
  catch(error){$('#connection').textContent=`Unable to refresh · ${error.message}`;toast(error.message);}finally{loading=false;}
}
const stat=(label,value)=>`<div class="stat"><div class="stat-label">${label}</div><div class="stat-value">${value}</div></div>`;
function render(){
  $('#project-count').textContent=state.projects.length;
  $('#identity-label').textContent=state.actor?`GitHub: ${state.actor.login}`:'Local GitHub login';
  $('#breadcrumb').innerHTML=`Workspace <span>/</span> Projects${project()?`<span>/</span>${esc(project().name)}`:''}`;
  const all=state.projects.flatMap(p=>p.tasks);
  const stats=`<div class="stats">${stat('In progress',all.filter(t=>t.status==='active').length)}${stat('Ready to work',all.filter(ready).length)}${stat('Blocked',all.filter(t=>status(t)==='blocked').length)}${stat('Completed',all.filter(t=>t.status==='done').length)}</div>`;
  $('#main').innerHTML=project()?projectPage(stats):`<div class="page-heading"><div><div class="eyebrow">The work, in motion</div><h1>Projects</h1><p class="description">Your repositories, with a clear next step for every agent.</p></div></div>${stats}<div class="cards">${state.projects.map(p=>`<button class="project-card" data-project="${esc(p.id)}"><div class="card-top"><span class="repo-icon">⌘</span>${badge(p.tasks.some(t=>t.status==='active')?'active':'ready')}</div><h3>${esc(p.name)}</h3><div class="repo-name">${esc(p.repo)}</div><p class="card-description">${esc(p.description)}</p><div class="progress-label"><strong>${p.tasks.filter(t=>t.status==='done').length} of ${p.tasks.length} complete</strong></div><progress class="progress" max="${p.tasks.length || 1}" value="${p.tasks.filter(t=>t.status==='done').length}"></progress><div class="card-bottom"><span>${p.agents.filter(a=>!a.revoked).length} authorized workers</span><span>${p.tasks.filter(ready).length} ready ↗</span></div></button>`).join('') || '<div class="empty"><h2>No projects yet</h2><p>Initialize this repository with Hivemind first.</p></div>'}</div>`;
  $('#main').insertAdjacentHTML('beforeend',requestsPanel());
  $('#search')?.addEventListener('input',e=>{query=e.target.value;renderQueue();});renderQueue();
}
function projectPage(stats){
  const p=project();if(!p.tasks.some(t=>t.id===taskId))taskId=p.tasks[0]?.id;
  return `<button class="back" data-action="home">← All projects</button><div class="page-heading"><div><div class="eyebrow">Repository workspace · queue revision ${p.revision}</div><h1>${esc(p.name)}</h1><a class="repo-name external" href="https://github.com/${esc(p.repo)}" target="_blank" rel="noopener">${esc(p.repo)} ↗</a></div><div class="row-actions"><button class="button secondary" data-action="reorder">Reorder queue</button><button class="button" data-action="add">＋ New task</button></div></div>${stats}<div class="toolbar"><p class="help">Edits use your GitHub identity. The broker validates authorization and revisions.</p><input class="search" id="search" type="search" aria-label="Search tasks" placeholder="Search tasks…" value="${esc(query)}"></div><div class="project-layout"><div class="panel"><div class="panel-heading"><h2>Work queue <span class="badge">${p.tasks.length}</span></h2><span class="help">Priority first, then queue order</span></div><div id="queue"></div></div><div><div class="panel detail" id="task-detail"></div><div class="panel detail agent-list"><h2>Activity</h2>${(p.events || []).slice(0,8).map(e=>`<div class="event"><div>${esc(e.action.replaceAll('_',' '))}<small>${esc(worker(e.actor))} · ${new Date(e.created*1000).toLocaleString()}</small></div></div>`).join('') || '<p class="help">No activity yet.</p>'}</div></div></div>`;
}
function renderQueue(){
  const p=project();if(!p)return;
  $('#queue').innerHTML=p.tasks.filter(t=>`${t.title} ${t.id}`.toLowerCase().includes(query.toLowerCase())).map(t=>`<button class="task-row ${taskId===t.id?'selected':''}" data-task="${esc(t.id)}"><div class="task-row-top"><strong>${t.parent?'↳ ':''}${esc(t.title)}</strong>${badge(status(t))}</div><div class="task-meta"><span class="mono">${esc(t.id)}</span><span>P${t.priority}</span><span>${t.dependencies.length} dependencies</span><span>${esc(worker(t.agent))}</span></div></button>`).join('') || '<div class="empty"><h2>No matching tasks</h2><p>Add a task or change your search.</p></div>';
  $('#task-detail').innerHTML=taskDetail(p,task());
}
function taskDetail(p,t){
  if(!t)return '<h2>Select a task</h2><p class="help">Inspect criteria, dependencies and completion evidence.</p>';
  const related=id=>{const x=p.tasks.find(v=>v.id===id);return `<button class="dependency" data-task="${esc(id)}">${esc(x?.title || id)} ${x?badge(status(x)):''}</button>`;};
  return `${badge(status(t))}<h2>${esc(t.title)}</h2><div class="mono">${esc(t.id)} · revision ${t.revision}</div><div class="row-actions"><button class="button secondary" data-action="edit">Edit task</button><button class="button secondary" data-action="subtask">＋ Subtask</button></div><div class="detail-label">Acceptance criteria</div><p class="prose">${esc(t.criteria)}</p>${t.parent?`<div class="detail-label">Parent</div>${related(t.parent)}`:''}<div class="detail-label">Dependencies</div>${t.dependencies.map(related).join('') || '<p class="help">None · this task can run independently.</p>'}<div class="detail-label">Subtasks</div>${p.tasks.filter(x=>x.parent===t.id).map(x=>related(x.id)).join('') || '<p class="help">None.</p>'}${t.status==='active'?`<div class="detail-label">Claim</div><p class="help">${esc(worker(t.agent))} · expires ${new Date(t.lease*1000).toLocaleString()}</p>`:''}${t.proof?`<div class="detail-label">Verified evidence</div><a class="proof-link" href="https://github.com/${esc(p.repo)}/pull/${t.proof.pr}" target="_blank" rel="noopener">PR #${t.proof.pr} ↗</a><div class="mono">${esc(t.proof.commit)}</div><p class="prose">${esc(t.proof.summary)}</p>${t.proof.checks.map(c=>`<div class="check">✓ ${esc(c.name)}</div>`).join('')}`:''}<div class="detail-label">Notes</div>${t.notes.map(n=>`<p class="prose">${esc(n.text)}<small class="help"> · ${esc(worker(n.actor))}</small></p>`).join('') || '<p class="help">No notes yet.</p>'}<div class="row-actions"><button class="text-button" data-action="note">＋ Add note</button>${!['done','cancelled'].includes(t.status)?'<button class="text-button" data-action="cancel">Cancel task</button>':''}</div>`;
}
function requestsPanel(){return `<div class="panel activity"><div class="panel-heading"><h2>Background commands & receipts</h2><span class="help">Pending changes are not applied yet</span></div>${requests.slice().reverse().slice(0,12).map(r=>`<div class="event"><div>${badge(r.status)} <strong>${esc(r.label)}</strong><p class="help">${esc(r.message || '')}</p>${r.request_id?`<div class="mono">${esc(r.request_id)}</div>`:''}${r.url?`<a class="text-button" href="${link(r.url)}" target="_blank" rel="noopener">Inspect on GitHub ↗</a>`:''}</div></div>`).join('') || '<div class="event">Your edits and their broker receipts appear here.</div>'}</div>`;}
const actions=text=>`<div class="form-error" role="alert"></div><div class="form-actions"><button type="button" class="button secondary" data-action="close">Close</button><button type="submit" class="button">${text}</button></div>`;
function modal(title,html,submit){
  $('#modal-title').textContent=title;$('#modal-content').innerHTML=html;
  const form=$('#modal-content form');if(form)form.addEventListener('submit',async e=>{e.preventDefault();const button=form.querySelector('[type=submit]');button.disabled=true;try{await submit(form);}catch(error){$('.form-error').textContent=error.message;}finally{button.disabled=false;}});
  $('#modal').showModal();
}
async function run(action,args,label,draftKey=null){
  const id=crypto.randomUUID().replaceAll('-','');const r={id,label,status:'running',draftKey,draftSnapshot:draftKey?saved(draftKey):null};requests.push(r);save(key('requests'),requests);
  try{await api('/api/commands',{id,project:project()?.id || state.projects[0].id,action,args});}
  catch(error){r.status='unknown';r.message=`${error.message}. Inspect GitHub Issues before retrying; draft retained.`;save(key('requests'),requests);throw error;}
  $('#modal').close();render();toast('Command started. Waiting for broker validation.');await pollRequests();
}
function taskModal(edit=false,parent=''){
  const p=project(),t=edit?task():null,k=key(`draft:${p.id}:${t?.id || 'new'}`);
  const draft=saved(k) || {title:t?.title || '',criteria:t?.criteria || '',priority:t?.priority || 2,parent:t?.parent || parent,dependencies:t?.dependencies || [],expected_revision:t?.revision,release_claim:false};
  const options=(chosen,multi)=>p.tasks.filter(x=>x.id!==t?.id).map(x=>`<option value="${esc(x.id)}" ${(multi?chosen.includes(x.id):chosen===x.id)?'selected':''}>${esc(x.title)}</option>`).join('');
  const read=form=>({...Object.fromEntries(new FormData(form)),priority:Number(form.elements.priority.value),dependencies:Array.from(form.elements.dependencies.selectedOptions).map(o=>o.value),expected_revision:draft.expected_revision,release_claim:!!form.elements.release_claim?.checked});
  modal(edit?'Edit task':'Add a task',`<form><p class="help">${edit?`Draft bound to task revision ${draft.expected_revision}. Material edits invalidate existing completion evidence.`:'Describe a concrete outcome and the evidence required.'} Drafts stay on this computer until accepted or discarded.</p><label for="title">Title</label><input id="title" name="title" required maxlength="200" value="${esc(draft.title)}"><label for="criteria">Acceptance criteria</label><textarea id="criteria" name="criteria" required maxlength="10000">${esc(draft.criteria)}</textarea><label for="priority">Priority</label><select id="priority" name="priority">${[1,2,3].map(n=>`<option value="${n}" ${Number(draft.priority)===n?'selected':''}>${['','1 · High','2 · Normal','3 · Low'][n]}</option>`).join('')}</select><label for="parent">Parent task</label><select id="parent" name="parent"><option value="">No parent</option>${options(draft.parent,false)}</select><label for="dependencies">Dependencies</label><select id="dependencies" name="dependencies" multiple>${options(draft.dependencies,true)}</select><p class="help">Use Command / Control to select multiple tasks.</p>${t?`<label class="checkbox-label"><input type="checkbox" name="release_claim" ${draft.release_claim?'checked':''}> Release any active claim for a material edit</label><p class="help">Changing title, criteria, parent or dependencies of active work requires releasing its claim. Priority changes alone preserve it.</p>`:''}<button type="button" class="text-button" id="discard-draft">Discard draft and reload latest values</button>${actions(edit?'Submit edit':'Add to queue')}</form>`,async form=>{
    const data=read(form);save(k,data);const args={title:data.title,criteria:data.criteria,priority:data.priority,parent:data.parent || null,dependencies:data.dependencies};
    if(t)Object.assign(args,{task:t.id,expected_revision:data.expected_revision,release_claim:data.release_claim});
    await run(t?'edit':'add',args,data.title,k);
  });
  const form=$('#modal-content form');form.addEventListener('input',()=>save(k,read(form)));form.addEventListener('change',()=>save(k,read(form)));
  $('#discard-draft').addEventListener('click',async()=>{localStorage.removeItem(k);$('#modal').close();await load();taskModal(edit,parent);});
}
function reorderModal(){
  const p=project(),draftKey=key(`draft:${p.id}:order`),draft=saved(draftKey),revision=draft?.expected_revision || p.revision,ids=draft?.tasks || p.tasks.map(t=>t.id);
  modal('Prioritize the queue',`<form><p class="help">Queue revision ${revision}. Priority levels still apply; this orders tasks within a level. Active claims are preserved.</p><div id="order-list"></div><button type="button" class="text-button" id="discard-order">Discard draft and reload latest order</button>${actions('Submit order')}</form>`,async()=>{save(draftKey,{tasks:ids,expected_revision:revision});await run('prioritize',{tasks:ids,expected_revision:revision},'Reorder queue',draftKey);});
  const draw=()=>{$('#order-list').innerHTML=ids.map((id,i)=>`<div class="order-row"><span>${esc(p.tasks.find(t=>t.id===id)?.title || id)}</span><button type="button" class="icon-button" aria-label="Move task up" data-index="${i}" data-direction="-1" ${i===0?'disabled':''}>↑</button><button type="button" class="icon-button" aria-label="Move task down" data-index="${i}" data-direction="1" ${i===ids.length-1?'disabled':''}>↓</button></div>`).join('');};
  $('#order-list').addEventListener('click',e=>{const b=e.target.closest('[data-direction]');if(!b)return;const i=Number(b.dataset.index),j=i+Number(b.dataset.direction);if(j>=0 && j<ids.length){[ids[i],ids[j]]=[ids[j],ids[i]];save(draftKey,{tasks:ids,expected_revision:revision});draw();}});draw();$('#discard-order').addEventListener('click',async()=>{localStorage.removeItem(draftKey);$('#modal').close();await load();reorderModal();});
}
async function pollRequests(){
  if(!state.repo)return;let changed=false,refresh=false;
  for(const r of requests.filter(x=>['running','pending'].includes(x.status))){
    try{const result=r.request_id?await api(`/api/requests/${r.request_id}`):await api(`/api/jobs/${r.id}`);if(result.status==='running')continue;
      if(result.status==='failed'){r.status='failed';r.message=`${result.error}. Draft retained. Inspect GitHub before retrying.`;}
      else{const receipt=result.status==='finished'?result.result:result;r.status=receipt.status==='dispatched'?'accepted':receipt.status || 'accepted';r.request_id=receipt.request_id || r.request_id;r.url=receipt.url || r.url;r.message=receipt.message || (r.status==='pending'?'Waiting for broker receipt.':receipt.status==='dispatched'?'Broker run dispatched; inspect its result on GitHub.':'Broker accepted the change.');if(r.status==='accepted'){if(r.draftKey && JSON.stringify(saved(r.draftKey))===JSON.stringify(r.draftSnapshot))localStorage.removeItem(r.draftKey);refresh=true;}}
      changed=true;
    }catch(error){r.message=error.message;if(error.message.includes('Job is not in this UI session')){r.status='unknown';r.message='UI session restarted. Inspect GitHub Issues before retrying; draft retained.';}changed=true;}
  }
  if(changed){save(key('requests'),requests);if(!$('#modal').open)render();}if(refresh)await load();
}
 document.addEventListener('click',async e=>{
  const b=e.target.closest('button');if(!b)return;
  try{if(b.dataset.project){projectId=b.dataset.project;taskId=null;render();return;}if(b.dataset.task){taskId=b.dataset.task;renderQueue();return;}
    const a=b.dataset.action;
    if(a==='home'){projectId=null;render();}else if(a==='close')$('#modal').close();else if(a==='add')taskModal();else if(a==='edit')taskModal(true);else if(a==='subtask')taskModal(false,taskId);else if(a==='reorder')reorderModal();
    else if(a==='note'){const t=task();modal('Add a note',`<form><label for="note">Handoff or question</label><textarea id="note" name="text" required maxlength="10000"></textarea>${actions('Submit note')}</form>`,form=>run('note',{task:t.id,text:form.elements.text.value},`Note: ${t.title}`));}
    else if(a==='cancel'){const t=task();modal('Cancel task',`<form><p class="prose">Cancel ${esc(t.title)} at revision ${t.revision}? Its history stays in GitHub.</p>${actions('Cancel task')}</form>`,()=>run('cancel',{task:t.id,expected_revision:t.revision},`Cancel: ${t.title}`));}
    else if(a==='kick')await run('kick',{},'Kick broker');
  }catch(error){toast(error.message);}
});
$('#home-nav').addEventListener('click',()=>{projectId=null;render();});$('.brand').addEventListener('click',()=>{projectId=null;render();});$('#refresh').addEventListener('click',load);$('#close-modal').addEventListener('click',()=>$('#modal').close());
setInterval(()=>{if(!$('#modal').open)load();},60000);
let polling=false;setInterval(async()=>{if(polling)return;polling=true;try{await pollRequests();}finally{polling=false;}},15000);
$('#main').innerHTML='<div class="empty"><h2>Connecting to your GitHub queue…</h2><p>Using the GitHub login from your terminal.</p></div>';load().then(pollRequests);
