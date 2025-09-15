/* Minimal, reliable frontend:
   - Tabs
   - Persist “Include Trackers” locally
   - CSRF header on /pref and /job
   - Start job + render one simple job card
   - SSE stream for live status
*/

const el  = (sel, parent=document) => parent.querySelector(sel);
const els = (sel, parent=document) => Array.from(parent.querySelectorAll(sel));

let CSRF = null;

// Fetch auth status to grab CSRF (index.html is served only after login)
(async function getCsrf(){
  try {
    const r = await fetch('/auth/status', { credentials: 'same-origin' });
    const j = await r.json();
    if (j && j.authed && j.csrf) CSRF = j.csrf;
  } catch {}
})();

// Tabs
document.addEventListener('click', (e) => {
  if (e.target.matches('.tab')) {
    const btn = e.target;
    els('.tab').forEach(t=>t.classList.remove('active'));
    btn.classList.add('active');
    els('.tabpane').forEach(p=>p.classList.remove('active'));
    el(btn.dataset.target)?.classList.add('active');
  }
});

// Persist Include Trackers toggle
const toggle = el('#includeTrackers');
if (toggle) {
  const saved = localStorage.getItem('includeTrackers');
  if (saved !== null) toggle.checked = (saved === 'true');

  toggle.addEventListener('change', async () => {
    const val = toggle.checked ? 'true' : 'false';
    localStorage.setItem('includeTrackers', val);
    try {
      const headers = { 'Content-Type': 'application/json' };
      if (CSRF) headers['X-CSRF'] = CSRF;
      await fetch('/pref', {
        method:'POST',
        headers,
        credentials: 'same-origin',
        body: JSON.stringify({ includeTrackers: toggle.checked })
      });
    } catch {}
  });
}

// submit
const form = el('#jobForm');
if (form) {
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const activeTab = el('.tab.active')?.dataset.target || '#tab-magnet';

    const fd = new FormData();
    fd.append('includeTrackers', toggle && toggle.checked ? 'true' : 'false');

    if (activeTab === '#tab-magnet') {
      fd.append('kind', 'magnet');
      fd.append('magnet', (el('textarea[name="magnet"]')?.value || '').trim()); // raw magnet, no "?magnet="
    } else if (activeTab === '#tab-torrent') {
      fd.append('kind', 'torrent');
      const file = el('input[name="torrent"]')?.files?.[0];
      if (!file) { alert('Choose a .torrent file'); return; }
      fd.append('torrent', file);
    } else {
      fd.append('kind', 'url');
      fd.append('urls', (el('textarea[name="urls"]')?.value || '').trim());
    }

    try {
      const headers = {};
      if (CSRF) headers['X-CSRF'] = CSRF;

      const res = await fetch('/job', { method:'POST', headers, body: fd, credentials: 'same-origin' });
      if (!res.ok) {
        const t = await res.text().catch(()=> '');
        console.error('POST /job failed', res.status, t);
        alert('Failed to start job');
        return;
      }
      const data = await res.json();
      if (!data.ok || !data.jobId) {
        alert('Failed to start: ' + (data.error || 'unexpected response'));
        return;
      }
      addJobCard(data.jobId);
    } catch(err) {
      console.error('submit failed', err);
      alert('Network error starting job');
    }
  });
}

// render jobs list (resume)
async function refreshJobs(){
  try {
    const res = await fetch('/jobs?limit=5', { credentials: 'same-origin' });
    if (!res.ok) return;
    const { items } = await res.json();
    const container = el('#jobs');
    container.innerHTML = '';
    for (const j of items) addJobCard(j.id, j);
  } catch(e) {
    console.warn('refreshJobs failed', e);
  }
}

function addJobCard(id, initial=null){
  const container = el('#jobs');
  const div = document.createElement('div');
  div.className = 'job';
  div.id = 'job-'+id;
  div.innerHTML = `
    <div><strong>Job</strong> <span class="mono">${id}</span></div>
    <div class='status'>${initial ? (initial.status || 'queued') : 'queued'}</div>
    <div class='links'></div>
    <div class='err'></div>
  `;
  container.prepend(div);

  // SSE subscribe
  const ev = new EventSource('/events/'+encodeURIComponent(id));
  ev.onmessage = (msg) => {
    try {
      const data = JSON.parse(msg.data);
      if (data.message) div.querySelector('.status').textContent = data.message;
      if (data.status) {
        div.querySelector('.status').textContent = data.status + (data.message?': '+data.message:'');
        if (data.status === 'error') {
          div.querySelector('.err').textContent = data.error || 'error';
          ev.close();
        }
        if (data.status === 'done' && (data.public || data.share_url)) {
          const links = div.querySelector('.links');
          links.innerHTML = '';
          const url = data.share_url || data.public?.web || (data.public?.shareId ? `/d/${data.public.shareId}/` : null);
          if (url) {
            const a = document.createElement('a'); a.className='link'; a.href=url; a.textContent='Open files'; a.target='_blank';
            links.append(a);
          }
          div.querySelector('.status').textContent = 'done';
          ev.close();
        }
      }
    } catch(e) {
      console.warn('SSE parse failed', e);
    }
  };
  ev.onerror = (e) => {
    console.warn('SSE error', e);
  };
}

refreshJobs();
