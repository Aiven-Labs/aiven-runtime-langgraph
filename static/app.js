const $ = id => document.getElementById(id);
let csrf = '', current = null, busy = false;
function notice(text = '') { $('notice').textContent = text; $('notice').hidden = !text; }
async function api(path, options = {}) {
  const response = await fetch(path, {credentials: 'same-origin', ...options,
    headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf, ...(options.headers || {})}});
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401 && path !== '/api/login') showLogin();
    throw new Error(typeof data.detail === 'string' ? data.detail : 'Please check the form and try again.');
  }
  return data;
}
function showLogin() { $('workspace').hidden = true; $('logout').hidden = true; $('login-view').hidden = false; }
async function enter() {
  const session = await api('/api/session'); csrf = session.csrf;
  $('login-view').hidden = true; $('workspace').hidden = false; $('logout').hidden = false;
  $('mode').textContent = session.mode === 'mock' ? 'Demo mode · no model calls' : `Live model · ${session.model}`;
  await refresh();
}
async function refresh() {
  const runs = await api('/api/runs'); $('run-list').replaceChildren();
  if (!runs.length) { const p = document.createElement('p'); p.className = 'small'; p.textContent = 'Your first draft starts here.'; $('run-list').append(p); }
  for (const run of runs) {
    const button = document.createElement('button'); button.className = 'run-button' + (run.id === current?.id ? ' selected' : '');
    button.textContent = run.request.length > 75 ? run.request.slice(0,75) + '…' : run.request;
    const date = document.createElement('span'); date.textContent = new Date(run.created_at).toLocaleString(); button.append(date);
    button.onclick = () => action(async () => render(await api(`/api/runs/${run.id}`)));
    button.disabled = busy; $('run-list').append(button);
  }
}
function render(run) {
  current = run; $('create-view').hidden = true; $('detail-view').hidden = false;
  $('run-title').textContent = run.request; $('run-date').textContent = `Started ${new Date(run.created_at).toLocaleString()}`;
  $('status').textContent = {completed:'Complete', awaiting_review:'Waiting for your review', needs_continue:'Ready to continue'}[run.status];
  $('revision').textContent = run.revision ? `Version ${run.revision} · ${run.mode === 'mock' ? 'demo draft' : 'model draft'}` : '';
  $('draft').textContent = run.draft || 'No draft has been saved yet.';
  $('review-area').hidden = run.status !== 'awaiting_review'; $('continue-area').hidden = run.status !== 'needs_continue'; $('complete-area').hidden = run.status !== 'completed';
  $('feedback').value = '';
  document.querySelectorAll('.steps li').forEach(e => e.classList.remove('active'));
  $(run.status === 'completed' ? 'step-complete' : run.status === 'awaiting_review' ? 'step-review' : 'step-draft').classList.add('active');
  notice(run.error || '');
}
async function action(fn) {
  if (busy) return; busy = true; notice();
  document.querySelectorAll('button').forEach(b => b.disabled = true);
  try { await fn(); } catch (e) { notice(e.message); }
  finally { busy = false; document.querySelectorAll('button').forEach(b => b.disabled = false); }
}
$('login-form').onsubmit = async e => { e.preventDefault(); $('login-error').textContent = ''; const button = e.submitter; button.disabled = true;
  try { await api('/api/login', {method:'POST', body:JSON.stringify({password:$('password').value})}); $('password').value=''; await enter(); }
  catch(e) { $('login-error').textContent=e.message; } finally {button.disabled=false;}
};
$('logout').onclick = () => action(async () => {await api('/api/logout',{method:'POST'}); current=null; csrf=''; $('run-list').replaceChildren(); $('draft').textContent=''; showLogin();});
$('new-run').onclick = () => {current=null; notice(); $('detail-view').hidden=true; $('create-view').hidden=false; document.querySelectorAll('.steps li').forEach(e=>e.classList.remove('active')); $('step-request').classList.add('active'); $('request').focus();};
$('refresh').onclick = () => action(async () => {await refresh(); if(current) render(await api(`/api/runs/${current.id}`));});
$('create-form').onsubmit = e => {e.preventDefault(); action(async()=>{notice('Drafting… Your run will pause for review.'); render(await api('/api/runs',{method:'POST',body:JSON.stringify({request:$('request').value})})); await refresh();});};
async function review(actionName) {await action(async()=>{render(await api(`/api/runs/${current.id}/review`,{method:'POST',body:JSON.stringify({action:actionName,feedback:$('feedback').value,checkpoint:current.checkpoint})}));await refresh();});}
$('review-form').onsubmit = e => {e.preventDefault(); if(!$('feedback').value.trim()){notice('Add feedback before requesting a revision.');return;} review('revise');};
$('approve').onclick=()=>review('approve');
$('continue').onclick=()=>action(async()=>{render(await api(`/api/runs/${current.id}/continue`,{method:'POST'}));await refresh();});
enter().catch(e=>{showLogin(); if(e.message!=='Sign in to continue') $('login-error').textContent=e.message;}).finally(()=>{$('loading').hidden=true;$('step-request').classList.add('active');});
