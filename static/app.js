// static/app.js
const el = (sel, parent=document) => parent.querySelector(sel);
const els = (sel, parent=document) => [...parent.querySelectorAll(sel)];

let currentKind = 'magnet';
let currentJobId = null;
let es = null;
const MAX_LOG_LINES = 500;
const MAX_VISIBLE_ACTIVE = 8; // keep UI short even with many files

// Tabs
document.addEventListener('click', (e) => {
  if (e.target.matches('.tab')) {
    const btn = e.target;
    els('.tab').forEach(t=>t.classList.remove('active'));
    btn.classList.add('active');
    els('.tabpane').forEach(p=>p.classList.remove('active'));
    el(btn.dataset.target).classList.add('active');
    currentKind = btn.dataset.kind || 'magnet';
  }
});

// Persist Include Trackers toggle
const toggle = el('#includeTrackers');
const saved = localStorage.getItem('includeTrackers');
if (saved !== null) toggle.checked = saved === 'true';
toggle.addEventListener('change', async () => {
  localStorage.setItem('includeTrackers', toggle.checked ? 'true' : 'false');
  try { await fetch('/pref', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ includeTrackers: toggle.checked })}); } catch {}
});

// form submit
el('#jobForm').addEventListener('submit', async (e) => {
  e.preventDefault();

  const fd = new FormData();
  fd.append('includeTrackers', toggle.checked ? 'true' : 'false');

  if (currentKind === 'magnet') {
    const m = (el('textarea[name="magnet"]').value || '').trim();
    if (!m) return alert('Enter a magnet link');
    fd.append('kind', 'magnet');
    fd.append('magnet', m);
  } else if (currentKind === 'torrent') {
    const file = el('input[name="torrent"]').files[0];
    if (!file) return alert('Choose a .torrent file');
    fd.append('kind', 'torrent');
    fd.append('torrent', file);
  } else {
    const urls = (el('textarea[name="urls"]').value || '').trim();
    if (!urls) return alert('Enter at least one URL');
    fd.append('kind', 'url');
    fd.append('urls', urls);
  }

  let res, data;
  try {
    res = await fetch('/job', { method:'POST', body: fd });
    data = await res.json();
  } catch (err) {
    console.error(err);
    return alert('Network error creating job');
  }
  if (!data || !data.ok) {
    return alert('Failed to start: ' + (data && data.error || 'unknown error'));
  }

  attachToJob(data.jobId, true);
});

// -------------- Current job UI --------------
const jobIdEl = el('#jobId');
const jobStatusEl = el('#jobStatus');
const overallFill = el('#overallFill');
const overallText = el('#overallText');
const filesBox = el('#filesBox');
const jobActions = el('#jobActions');
const logBox = el('#logBox');

function logLine(txt){
  const time = new Date().toLocaleTimeString();
  const div = document.createElement('div');
  div.className = 'logline';
  div.innerHTML = `<span class="logtime">[${time}]</span>${txt}`;
  logBox.appendChild(div);
  while (logBox.children.length > MAX_LOG_LINES) logBox.removeChild(logBox.firstChild);
  const nearBottom = (logBox.scrollTop + logBox.clientHeight + 50) >= logBox.scrollHeight;
  if (nearBottom) logBox.scrollTop = logBox.scrollHeight;
}

function humanBytes(n){
  if (!n && n !== 0) return '';
  const k = 1024, units = ['B','KB','MB','GB','TB'];
  let i = 0; let v = n;
  while (v >= k && i < units.length-1){ v /= k; i++; }
  return (v.toFixed(v >= 10 || i === 0 ? 0 : 1)) + ' ' + units[i];
}

const fileStats = new Map(); // name -> {received,total,pct,done}
let completedCount = 0;

function renderFiles(){
  const active = [];
  const completed = [];
  for (const [name, s] of fileStats){
    (s.done ? completed : active).push([name, s]);
  }
  // keep only a handful active on screen
  const toShow = active.slice(0, MAX_VISIBLE_ACTIVE);

  const rows = [];
  for (const [name, s] of toShow){
    const pct = (typeof s.pct === 'number') ? s.pct : (s.total ? Math.floor((s.received||0)*100/s.total) : null);
    rows.push(`
      <div class="file-row">
        <div class="file-name" title="${name}">${name}</div>
        <div class="mini-bar"><div class="mini-fill" style="width:${pct!=null?Math.max(0,Math.min(100,pct)):0}%"></div></div>
        <div class="file-size mono">${pct!=null? (pct+'%') : (s.total ? (humanBytes(s.received||0)+' / '+humanBytes(s.total)) : (s.received? humanBytes(s.received):''))}</div>
      </div>
    `);
  }

  // summary line for hidden items
  const hiddenActive = Math.max(0, active.length - toShow.length);
  completedCount = completed.length;
  const summary = [];
  if (hiddenActive > 0) summary.push(`${hiddenActive} more active…`);
  if (completedCount > 0) summary.push(`${completedCount} completed`);
  const line = summary.length ? `<div class="summary-row">${summary.join(' • ')}</div>` : '';

  filesBox.innerHTML = line + rows.join('');
}

function recomputeOverall(phaseHint){
  let totalKnown = 0, receivedKnown = 0, doneCount = 0, totalFiles = fileStats.size;
  for (const [, s] of fileStats){
    if (typeof s.total === 'number' && s.total > 0){
      totalKnown += s.total;
      receivedKnown += Math.min(s.received || 0, s.total);
    } else if (s.done) {
      doneCount++;
    }
  }
  let pct = null;
  if (totalKnown > 0){
    pct = Math.floor(receivedKnown * 100 / totalKnown);
  } else if (totalFiles > 0){
    const completed = [...fileStats.values()].filter(s => s.done).length;
    pct = Math.floor((completed * 100) / totalFiles);
  }
  if (pct !== null){
    overallFill.style.width = Math.max(0, Math.min(100, pct)) + '%';
    overallText.textContent = `${phaseHint || 'downloading'} — ${pct}%`;
  } else {
    overallText.textContent = phaseHint || 'downloading';
  }
}

function ensureCancel(jobId){
  if (!jobActions) return;
  if (el('#cancelBtn')) return;
  const btn = document.createElement('button');
  btn.id='cancelBtn';
  btn.textContent='Cancel';
  btn.addEventListener('click', async ()=>{
    try{
      await fetch(`/job/${jobId}/cancel`, {method:'POST'});
      logLine('Cancel requested…');
    }catch{}
  });
  jobActions.prepend(btn);
}
function removeCancel(){ const b = el('#cancelBtn'); if (b) b.remove(); }

function attachToJob(jobId, clearLog){
  try { es && es.close(); } catch {}
  if (clearLog) logBox.innerHTML = '';
  fileStats.clear(); renderFiles();

  currentJobId = jobId;
  localStorage.setItem('lastJobId', jobId);

  el('#jobId').textContent = jobId ? `#${jobId.slice(0,8)}` : '';
  jobStatusEl.textContent = 'queued';
  overallFill.style.width = '0%';
  overallText.textContent = '';
  if (jobActions) jobActions.innerHTML = '';

  es = new EventSource('/events/' + jobId);
  logLine(`Job ${jobId} attached`);

  es.onmessage = (msg) => {
    if (!msg.data) return;
    const data = JSON.parse(msg.data);

    const finalStates = new Set(['done','error','cancelled']);
    if (!finalStates.has(data.status || '') && !el('#cancelBtn')) ensureCancel(jobId);

    if (data.type === 'unlock'){
      const u = data.unlocked|0, t = data.total|0;
      jobStatusEl.textContent = `retrieving links… ${u}/${t}`;
      overallText.textContent = `retrieving links… ${u}/${t}`;
      logLine(`Retrieving links… ${u}/${t}`);
    }

    if (data.message) {
      jobStatusEl.textContent = data.message;
      logLine(data.message);
    }
    if (data.status) {
      const txt = data.message ? `${data.status}: ${data.message}` : data.status;
      jobStatusEl.textContent = txt;
      if (finalStates.has(data.status)) { removeCancel(); }
      if (data.status !== 'running') logLine(`status → ${txt}`);
    }

    if (data.type === 'overall'){
      const pct = (typeof data.pct === 'number') ? data.pct :
                  (data.total ? Math.floor((data.received||0)*100/data.total) : null);
      const phase = data.phase || 'downloading';
      if (pct !== null) {
        overallFill.style.width = Math.max(0,Math.min(100,pct)) + '%';
        overallText.textContent = `${phase} — ${pct}%`;
      } else {
        overallText.textContent = phase;
      }
    }

    if (data.type === 'progress'){
      const name = data.file || 'file';
      const total = (typeof data.total === 'number' && data.total >= 0) ? data.total : null;
      const received = (typeof data.received === 'number' && data.received >= 0) ? data.received : 0;
      const pct = (typeof data.pct === 'number') ? data.pct : (total ? Math.floor(received * 100 / total) : null);
      const done = pct === 100 || (total && received >= total);
      fileStats.set(name, { total, received, pct, done });
      renderFiles();
      const phase = (data.phase || (jobStatusEl.textContent.includes('upload') ? 'uploading' : 'downloading'));
      recomputeOverall(phase);
    }

    if (data.status === 'error'){
      logLine(`ERROR: ${data.error || 'unknown error'}`);
      removeCancel(); es.close();
    }
    if (data.status === 'cancelled'){
      logLine('Cancelled.'); removeCancel(); es.close();
    }
    if (data.status === 'done' && (data.share_url || (data.public && data.public.shareId))){
      const url = data.share_url || `/d/${data.public.shareId}/`;
      logLine(`Done. Link: ${url}`);
      if (jobActions) {
        jobActions.innerHTML = '';
        const a = document.createElement('a'); a.className='link'; a.href=url; a.target='_blank'; a.textContent='Open files';
        const copy = document.createElement('button'); copy.className='copy'; copy.textContent='Copy link';
        copy.addEventListener('click', async ()=>{
          try { await navigator.clipboard.writeText(url); copy.textContent='Copied!'; setTimeout(()=>copy.textContent='Copy link',1500); } catch {}
        });
        jobActions.append(a); jobActions.append(copy);
      }
      overallFill.style.width = '100%';
      overallText.textContent = 'complete';
      jobStatusEl.textContent = 'done';
      removeCancel(); es.close();
    }

    if (data.type === 'cleared'){
      logLine('Job cleared by server');
      localStorage.removeItem('lastJobId');
      removeCancel();
      try { es.close(); } catch {}
    }
  };

  es.onerror = () => {
    logLine('SSE connection error; waiting for server keep-alives.');
  };
}

// Reattach to last in-progress job on refresh (if present)
const last = localStorage.getItem('lastJobId');
if (last) attachToJob(last, false);
