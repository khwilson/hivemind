const $ = selector => document.querySelector(selector);
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let token = sessionStorage.getItem('hivemind-token') || '';
let state = {projects: [], actor: null};
let projectId = null, taskId = null, filter = 'all', query = '';
const admin = () => state.actor?.id === 'admin';
const currentProject = () => state.projects.find(p => p.id === projectId);
const count = (tasks, status) => tasks.filter(t => t.status === status).length;
const ready = t => t.status === 'queued' && !t.blocked_by.length;
const taskStatus = t => t.status === 'queued' && t.blocked_by.length ? 'blocked' : t.status;
const badge = status => `<span class="badge ${escape(status)}">${({queued:'Queued',active:'In progress',blocked:'Blocked',done:'Complete'})[status] || escape(status)}</span>`;
const ago = timestamp => {
  const seconds = Math.max(0, Date.now() / 1000 - timestamp);
  return seconds < 60 ? 'just now' : seconds < 3600 ? `${Math.floor(seconds/60)}m ago` : seconds < 86400 ? `${Math.floor(seconds/3600)}h ago` : `${Math.floor(seconds/86400)}d ago`;
};
const safeLink = url => {try {const u = new URL(url); return u.protocol === 'https:' ? escape(u.href) : '#';} catch {return '#';}};

async function api(path, body) {
  const response = await fetch(path, {method:body === undefined ? 'GET':'POST', headers:{Authorization:`Bearer ${token}`, 'Content-Type':'application/json'}, ...(body === undefined ? {} : {body:JSON.stringify(body)})});
  const result = await response.json();
  if (!response.ok) throw Error(result.error || (Array.isArray(result.detail) ? result.detail.map(e=>`${e.loc.slice(1).join('.')}: ${e.msg}`).join('; ') : result.detail) || 'Request failed');
  return result;
}
function toast(message) { $('#toast').textContent = message; $('#toast').classList.add('show'); setTimeout(() => $('#toast').classList.remove('show'), 4500); }
async function load(silent = false) {
  if (!token) {render(); return;}
  try {
    state = await api('/api/state');
    $('#connection').textContent = 'Queue connected · updated ' + new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
    render();
  } catch (error) {$('#connection').textContent = 'Connection unavailable'; if (!silent) toast(error.message);}
}
function stat(label, value, note = '') {return `<div class="stat"><div class="stat-label">${label}</div><div class="stat-value">${value}${note ? `<small>${note}</small>` : ''}</div></div>`;}
function render() {
  $('#project-count').textContent = state.projects.length;
  $('#identity-label').innerHTML = state.actor ? `${escape(state.actor.name)}<small>${admin() ? 'Workspace administrator':'Authorized agent'}</small>` : 'Connect your workspace<small>Administrator or agent token</small>';
  $('#breadcrumb').innerHTML = `Workspace <span>/</span> Projects${currentProject() ? `<span>/</span>${escape(currentProject().name)}`:''}`;
  if (currentProject()) renderProject(); else renderProjects();
}
function renderProjects() {
  const tasks = state.projects.flatMap(p => p.tasks);
  $('#main').innerHTML = `<div class="page-heading"><div><div class="eyebrow">The work, in motion</div><h1>Projects</h1><p class="description">A shared queue for your repositories. A clear next step for every agent.</p></div>${admin() ? '<button class="button" data-action="new-project">＋ New project</button>' : !state.actor ? '<button class="button" data-action="auth">Connect workspace ↗</button>' : ''}</div>
    <div class="stats">${stat('Repositories',state.projects.length,'governed projects')}${stat('In progress',count(tasks,'active'),'claimed by agents')}${stat('Ready to work',tasks.filter(ready).length,'dependencies cleared')}${stat('Completed',count(tasks,'done'),'GitHub evidence verified')}</div>
    <div class="toolbar"><div class="tabs"><button class="tab ${filter==='all'?'active':''}" data-filter="all">All projects <span>${state.projects.length}</span></button><button class="tab ${filter==='active'?'active':''}" data-filter="active">In progress</button><button class="tab ${filter==='done'?'active':''}" data-filter="done">Completed</button></div><input class="search" id="search" type="search" aria-label="Search projects" placeholder="Search repositories…" value="${escape(query)}"></div><div class="cards" id="cards"></div>`;
  renderCards();
  $('#search').addEventListener('input', e => {query = e.target.value;renderCards();});
}
function renderCards() {
  const projects = state.projects.filter(p => `${p.name} ${p.repo}`.toLowerCase().includes(query.toLowerCase()) && (filter === 'all' || filter === 'active' && p.tasks.some(t=>t.status === 'active') || filter === 'done' && p.tasks.length && p.tasks.every(t=>t.status === 'done')));
  $('#cards').innerHTML = projects.map(p => {
    const done = count(p.tasks,'done'), active = count(p.tasks,'active'), agents = p.agents.filter(a=>!a.revoked), progress = p.tasks.length ? Math.round(done/p.tasks.length*100) : 0;
    return `<button class="project-card" data-project="${p.id}"><div class="card-top"><span class="repo-icon">⌘</span>${badge(progress === 100 ? 'done' : active ? 'active':'queued')}</div><h3>${escape(p.name)}</h3><div class="repo-name">↳ ${escape(p.repo)}</div><p class="card-description">${escape(p.description || 'A repository, a queue, and a shared direction.')}</p><div class="progress-label"><strong>${done} of ${p.tasks.length} tasks complete</strong><span>${progress}%</span></div><progress class="progress" max="100" value="${progress}" aria-label="Project completion">${progress}%</progress><div class="card-bottom"><span class="agents-stack">${agents.slice(0,3).map(a=>`<span class="mini-avatar">${escape(a.name.slice(0,1).toUpperCase())}</span>`).join('')}${agents.length} authorized ${agents.length === 1 ? 'agent':'agents'}</span><span>${p.tasks.filter(ready).length} ready <span>↗</span></span></div></button>`;
  }).join('') || `<div class="empty"><div class="empty-icon">▦</div><h2>${state.projects.length ? 'No matching projects' : 'Your next project starts here'}</h2><p>${state.projects.length ? 'Try another search or filter.' : 'Connect a GitHub repository, define the work, and authorize your agents.'}</p>${admin() ? '<button class="button" data-action="new-project">＋ Add a repository</button>' : !state.actor ? '<button class="button" data-action="auth">Connect workspace</button>' : ''}</div>`;
}
function renderProject() {
  const p = currentProject(), tasks = p.tasks;
  if (!taskId || !tasks.some(t=>t.id === taskId)) taskId = tasks[0]?.id;
  const t = tasks.find(t=>t.id === taskId);
  $('#main').innerHTML = `<button class="back" data-action="home">← All projects</button><div class="page-heading"><div><div class="eyebrow">Repository workspace</div><h1>${escape(p.name)}</h1><a class="repo-name external" href="https://github.com/${escape(p.repo)}" target="_blank" rel="noopener">${escape(p.repo)} ↗</a></div><div class="row-actions">${admin() ? '<button class="button secondary" data-action="agent">＋ Authorize agent</button>' : '<button class="button secondary" data-action="claim">Claim next task</button>'}<button class="button" data-action="new-task">＋ New task</button></div></div>
    <div class="stats">${stat('Total tasks',tasks.length)}${stat('In progress',count(tasks,'active'))}${stat('Ready to work',tasks.filter(ready).length)}${stat('Completed',count(tasks,'done'))}</div>
    <div class="setup-bar"><div><strong>Shared context, inside the repository.</strong><p>Install the agent workflow in AGENTS.md. Commit handoff notes to .hivemind/hints/.</p></div><button class="button secondary" data-action="instructions">Agent setup ↗</button></div>
    <div class="project-layout"><div><div class="panel"><div class="panel-heading"><h2>Work queue <span class="badge">${tasks.length}</span></h2><span class="help">Priority → oldest first</span></div>${tasks.map(t=>`<button class="task-row ${t.id===taskId?'selected':''}" data-task="${t.id}"><div class="task-row-top"><strong>${t.parent ? '↳ ' : ''}${escape(t.title)}</strong>${badge(taskStatus(t))}</div><div class="task-meta"><span class="priority">${['','↑ High','— Normal','↓ Low'][t.priority]}</span><span>${t.dependencies.length} dependencies</span><span>${tasks.filter(x=>x.parent===t.id).length} subtasks</span>${t.agent?`<span>${escape(p.agents.find(a=>a.id===t.agent)?.name || 'Agent')}</span>`:''}</div></button>`).join('') || '<div class="empty"><h2>No tasks yet</h2><p>Add a task with clear acceptance criteria.</p><button class="button" data-action="new-task">＋ Create first task</button></div>'}</div>
    <div class="panel activity"><div class="panel-heading"><h2>Activity</h2><span class="help">Last 100 events</span></div>${p.events.slice(0,12).map(e=>`<div class="event"><span class="pulse"></span><div>${escape(e.action.replaceAll('_',' '))}${e.task ? ` · ${escape(tasks.find(t=>t.id===e.task)?.title || e.task)}`:''}<small>${escape(e.actor === 'admin' ? 'Human administrator' : e.actor === 'system' ? 'Hivemind' : p.agents.find(a=>a.id===e.actor)?.name || e.actor)} · ${ago(e.created)}</small></div></div>`).join('')}</div></div>
    <div><div class="panel detail">${t ? taskDetail(p,t) : '<div class="empty-icon">◎</div><h2>The full picture</h2><p class="help">Select a task to inspect its criteria, dependencies, subtasks, and proof.</p>'}</div><div class="panel detail agent-list"><h2>Project settings</h2><div class="detail-label">Required GitHub checks</div>${p.required_checks.map(c=>`<div class="check">✓ ${escape(c)}</div>`).join('')}<p class="help">Tasks complete automatically once these checks pass on the submitted PR head. All reported checks must also pass.</p><div class="detail-label">Authorized agents</div>${p.agents.map(a=>`<div class="agent-row"><span>${escape(a.name)} ${a.revoked?'<small>· revoked</small>':''}</span>${admin() && !a.revoked ? `<button data-revoke="${a.id}">Revoke access</button>`:''}</div>`).join('') || '<p class="help">Authorize an agent to start claiming work.</p>'}</div></div></div>`;
}
function taskDetail(p,t) {
  const related = id => {const x = p.tasks.find(v=>v.id===id);return x ? `<button class="dependency" data-task="${x.id}">${x.status === 'done'?'✓':'○'} ${escape(x.title)} ${badge(taskStatus(x))}</button>` : '';};
  const owned = t.agent === state.actor?.id && t.status === 'active';
  return `${badge(taskStatus(t))}<h2>${escape(t.title)}</h2><div class="mono">${t.id}</div><div class="detail-label">Acceptance criteria</div><div class="prose">${escape(t.criteria)}</div>${t.feedback?`<div class="detail-label">Feedback</div><div class="prose">${escape(t.feedback)}</div>`:''}${t.parent?`<div class="detail-label">Parent task</div>${related(t.parent)}`:''}<div class="detail-label">Dependencies</div>${t.dependencies.map(related).join('') || '<p class="help">No dependencies.</p>'}<div class="detail-label">Subtasks</div>${p.tasks.filter(x=>x.parent===t.id).map(x=>related(x.id)).join('') || '<p class="help">No subtasks.</p>'}${t.status!=='done'?'<button class="text-button" data-action="subtask">＋ Add a subtask</button>':''}${t.status === 'active' ? `<div class="detail-label">Claim</div><p class="help">${escape(p.agents.find(a=>a.id===t.agent)?.name)} · expires ${new Date(t.lease*1000).toLocaleTimeString()}</p>${owned?'<div class="row-actions"><button class="button secondary" data-action="heartbeat">Renew claim</button><button class="button" data-action="submit">Submit proof</button></div>':''}`:''}${t.proof ? `<div class="detail-label">Verified completion evidence</div><a class="proof-link" href="${safeLink(t.proof.url)}" target="_blank" rel="noopener">Pull request #${t.proof.pr} ↗</a><div class="mono">${escape(t.proof.commit)}</div><p class="prose">${escape(t.proof.summary)}</p>${t.proof.checks.map(c=>`<div class="check">✓ ${c.url ? `<a href="${safeLink(c.url)}" target="_blank" rel="noopener">${escape(c.name)} ↗</a>` : escape(c.name)}</div>`).join('')}<p class="help">Verified ${new Date(t.proof.submitted_at*1000).toLocaleString()}</p>` : ''}`;
}
function modal(title, html, onSubmit) {
  $('#modal-title').textContent = title;
  $('#modal-content').innerHTML = html;
  const form = $('#modal-content form');
  if (form && onSubmit) form.addEventListener('submit', async event => {
    event.preventDefault();
    const button = form.querySelector('[type=submit]');
    button.disabled = true;
    $('.form-error').textContent = '';
    try {await onSubmit(Object.fromEntries(new FormData(form)), form);} catch (error) {$('.form-error').textContent = error.message;} finally {button.disabled = false;}
  });
  if (!$('#modal').open) $('#modal').showModal();
}
const actions = label => `<div class="form-error" role="alert"></div><div class="form-actions"><button type="button" class="button secondary" data-action="close">Cancel</button><button type="submit" class="button">${label}</button></div>`;
function authModal() {
  modal('Connect your workspace', `<form><p class="help">For local development, enter the token stored in <code>.hivemind-data/admin-token</code>, or your authorized agent token. It is kept in this browser tab only.</p><label for="token">Access token</label><input id="token" name="token" type="password" required autocomplete="off">${actions('Connect')}</form>${token?'<button class="text-button" data-action="logout">Disconnect this session</button>':''}`, async data => {
    const prior = token; token = data.token.trim();
    try {state = await api('/api/state');} catch (error) {token = prior;throw error;}
    sessionStorage.setItem('hivemind-token',token);$('#modal').close();await load();
  });
}
function projectModal() {
  modal('Create a project', `<form><p class="help">Every project governs one GitHub repository. Required check names must match your CI configuration exactly.</p><label for="name">Project name</label><input id="name" name="name" placeholder="e.g. Local zeta functions" maxlength="120" required><label for="repo">GitHub repository</label><input id="repo" name="repo" placeholder="owner/repository" required><label for="description">Project goal</label><textarea id="description" name="description" placeholder="What are we working toward?"></textarea><label for="required_checks">Required GitHub checks · one per line</label><textarea id="required_checks" name="required_checks" placeholder="build&#10;test" required></textarea>${actions('Create project')}</form>`, async data => {
    const result = await api('/api/projects', {...data, required_checks:data.required_checks.split('\n').map(s=>s.trim()).filter(Boolean)});
    projectId = result.id;taskId = null;$('#modal').close();await load();toast('Repository added. Create a task to get started.');
  });
}
function taskModal(parent = '') {
  const p = currentProject();
  modal(parent?'Add a subtask':'Add a task', `<form><label for="title">Task title</label><input id="title" name="title" required maxlength="200" placeholder="A specific, actionable outcome"><label for="criteria">Acceptance criteria</label><textarea id="criteria" name="criteria" required placeholder="What evidence will demonstrate that this work is complete?"></textarea><label for="priority">Priority</label><select id="priority" name="priority"><option value="1">High</option><option value="2" selected>Normal</option><option value="3">Low</option></select><label for="parent">Parent task · optional</label><select id="parent" name="parent"><option value="">No parent · standalone task</option>${p.tasks.filter(t=>t.status!=='done').map(t=>`<option value="${t.id}" ${parent===t.id?'selected':''}>${escape(t.title)}</option>`).join('')}</select><label for="dependencies">Dependencies · optional</label><select id="dependencies" name="dependencies" multiple>${p.tasks.map(t=>`<option value="${t.id}">${escape(t.title)}</option>`).join('')}</select><p class="help">Hold Command or Control to select multiple tasks. A parent waits for all subtasks to finish.</p>${actions('Add to queue')}</form>`, async (data,form) => {
    const result = await api(`/api/projects/${p.id}/tasks`, {...data, priority:Number(data.priority), dependencies:Array.from(form.elements.dependencies.selectedOptions).map(o=>o.value)});
    taskId=result.id;$('#modal').close();await load();toast('Task added to the queue.');
  });
}
function agentModal() {
  const p = currentProject();
  modal('Authorize an agent', `<form><p class="help">This credential can read, create, claim, and complete tasks only in ${escape(p.repo)}. It cannot change project settings or authorize other agents.</p><label for="agent-name">Agent name</label><input id="agent-name" name="name" required maxlength="120" placeholder="e.g. proof-worker-01">${actions('Create credential')}</form>`,async data => {
    const a=await api(`/api/projects/${p.id}/agents`,data);
    modal('Agent credential created', `<p class="help">Copy this token now. Only its hash is stored, so it cannot be retrieved again.</p><div class="code-block">${escape(a.token)}</div><p class="help">Configure the agent's environment:</p><div class="code-block">export HIVEMIND_URL=http://127.0.0.1:8765\nexport HIVEMIND_PROJECT=${p.id}\nexport HIVEMIND_TOKEN=&lt;token above&gt;\nhivemind claim</div><div class="form-actions"><button class="button" data-action="close">I've saved the token</button></div>`);await load();
  });
}
async function instructionsModal() {
  const p = currentProject(), data = await api(`/api/projects/${p.id}/instructions`);
  modal('Repository agent setup', `<p class="help">From this hivemind checkout, configure an authorized token and run this command against a checkout whose origin matches <code>${escape(p.repo)}</code>.</p><div class="code-block">hivemind --project ${p.id} install --repo /path/to/checkout</div><p class="help">The installer preserves existing AGENTS.md content. Review and commit the update so every agent can read it in GitHub.</p><div class="detail-label">Installed AGENTS.md section</div><pre class="code-block">${escape(data.content)}</pre><div class="form-actions"><button class="button secondary" data-action="download-instructions">Download section</button><button class="button" data-action="close">Done</button></div>`);
}
function submitModal() {
  const t=currentProject().tasks.find(t=>t.id===taskId);
  modal('Submit completion evidence', `<form><p class="help">The hivemind verifies your pull request and required checks with GitHub. Passing verification marks this task done immediately.</p><label for="commit">Full commit SHA</label><input id="commit" name="commit" pattern="[0-9a-fA-F]{40}" required placeholder="40-character PR head commit"><label for="pr">Pull request number</label><input id="pr" name="pr" type="number" min="1" required><label for="summary">How did you meet the acceptance criteria?</label><textarea id="summary" name="summary" required></textarea>${actions('Verify & complete')}</form>`,async data=>{await api(`/api/tasks/${t.id}/submit`,{...data,pr:Number(data.pr)});$('#modal').close();await load();toast('GitHub checks verified. Task complete.');});
}
document.addEventListener('click',async e=>{
  const button=e.target.closest('button');if(!button)return;
  try {
    if(button.dataset.project){projectId=button.dataset.project;taskId=null;render();return;}
    if(button.dataset.task){taskId=button.dataset.task;renderProject();return;}
    if(button.dataset.filter){filter=button.dataset.filter;renderProjects();return;}
    if(button.dataset.revoke){const id=button.dataset.revoke;modal('Revoke agent access',`<p class="help">This immediately disables the credential and returns the agent's active claims to the queue.</p><form>${actions('Revoke access')}</form>`,async()=>{await api(`/api/projects/${projectId}/agents/${id}/revoke`,{});$('#modal').close();await load();});return;}
    const action=button.dataset.action;
    if(action==='home'){projectId=null;taskId=null;render();}
    else if(action==='auth')authModal();
    else if(action==='close')$('#modal').close();
    else if(action==='logout'){token='';sessionStorage.removeItem('hivemind-token');state={projects:[],actor:null};projectId=null;$('#modal').close();$('#connection').textContent='Connect to load your queue';render();}
    else if(action==='new-project')projectModal();
    else if(action==='new-task')taskModal();
    else if(action==='subtask')taskModal(taskId);
    else if(action==='agent')agentModal();
    else if(action==='instructions')await instructionsModal();
    else if(action==='claim'){const result=await api(`/api/projects/${projectId}/claim`,{});if(result.task)taskId=result.task.id;await load();toast(result.task?'Task claimed for 30 minutes.':'No tasks are ready. Check dependencies or retry later.');}
    else if(action==='heartbeat'){await api(`/api/tasks/${taskId}/heartbeat`,{});await load();toast('Claim renewed for 30 minutes.');}
    else if(action==='submit')submitModal();
    else if(action==='download-instructions'){const data=await api(`/api/projects/${projectId}/instructions`);const link=document.createElement('a');link.href=URL.createObjectURL(new Blob([data.content],{type:'text/markdown'}));link.download='AGENTS.hivemind.md';link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000);}
  }catch(error){toast(error.message);}
});
$('#home-nav').addEventListener('click',()=>{projectId=null;taskId=null;render();});
$('.brand').addEventListener('click',()=>{projectId=null;taskId=null;render();});
$('#auth-button').addEventListener('click',authModal);
$('#refresh').addEventListener('click',()=>load());
$('#close-modal').addEventListener('click',()=>$('#modal').close());
setInterval(()=>{if(token&&!$('#modal').open&&!$('#search')?.matches(':focus'))load(true);},15000);
render();load();
