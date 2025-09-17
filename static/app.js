(() => {
  const el  = (sel, parent=document) => parent.querySelector(sel);
  const els = (sel, parent=document) => Array.from(parent.querySelectorAll(sel));

  let currentKind = 'magnet';
  let CURRENT_JOB_ID   = null;
  let CURRENT_SHARE_ID = null;
  let CSRF = null;
  let es = null;

  const SHARE_BASE = 'https://debrid.macery12.xyz/d/';

  // ---------- DOM Ready ----------
  onReady(init);
  function onReady(fn) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', fn, { once: true });
    } else {
      fn();
    }
  }

  // ---------- Elements ----------
  const jobIdEl      = el('#jobId');
  const jobStatusEl  = el('#jobStatus');
  const overallFill  = el('#overallFill');
  const overallText  = el('#overallText');
  const jobActionsEl = el('#jobActions');
  const logBox       = el('#logBox');
  const toggle       = el('#includeTrackers');

  // ---------- Utilities ----------
  const MB = 1024 * 1024;
  const toMB = n => (typeof n === 'number' && isFinite(n)) ? (n / MB) : undefined;

  function escapeHtml(s){
    return String(s).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  }
  function logLine(txt){
    if (!logBox) return;
    const time = new Date().toLocaleTimeString();
    const div = document.createElement('div');
    div.className = 'logline';
    div.innerHTML = `<span class="logtime">[${time}]</span> ${escapeHtml(txt)}`;
    logBox.appendChild(div);
    logBox.scrollTop = logBox.scrollHeight;
  }

  // ---------- CSRF ----------
  async function fetchCsrf() {
    try {
      const r = await fetch('/auth/status', { credentials: 'same-origin' });
      const j = await r.json().catch(()=>null);
      if (j && j.authed && j.csrf) {
        CSRF = j.csrf;
        return CSRF;
      }
    } catch {}
    return null;
  }
  async function ensureCsrf() {
    if (CSRF) return CSRF;
    return await fetchCsrf();
  }
  fetchCsrf(); // prime

  // ---------- Tabs ----------
  document.addEventListener('click', (e) => {
    if (e.target.matches('.tab')) {
      const btn = e.target;
      els('.tab').forEach(t=>t.classList.remove('active'));
      btn.classList.add('active');
      els('.tabpane').forEach(p=>p.classList.remove('active'));
      el(btn.dataset.target)?.classList.add('active');
      currentKind = btn.dataset.kind || 'magnet';
    }
  });

  // ---------- Persist "Include Trackers" -> /pref (with X-CSRF) ----------
  if (toggle) {
    const saved = localStorage.getItem('includeTrackers');
    if (saved !== null) toggle.checked = (saved === 'true');

    toggle.addEventListener('change', async () => {
      localStorage.setItem('includeTrackers', toggle.checked ? 'true' : 'false');
      try {
        await ensureCsrf();
        const headers = { 'Content-Type': 'application/json' };
        if (CSRF) headers['X-CSRF'] = CSRF;
        await fetch('/pref', {
          method:'POST',
          headers,
          credentials:'same-origin',
          body: JSON.stringify({ includeTrackers: toggle.checked })
        });
      } catch {}
    });
  }

  // ---------- Status + share link + per-download rows in #jobStatus ----------
  function renderStatusHeader(text){
    if (!jobStatusEl) return;
    jobStatusEl.innerHTML = '';

    // 1) compact status line
    const line = document.createElement('div');
    line.id = 'jobStatusText';
    line.textContent = text || '';
    jobStatusEl.appendChild(line);

    // 2) plain share <a> (hidden until we know shareId)
    const share = document.createElement('div');
    share.id = 'shareHref';
    share.style.display = 'none';
    jobStatusEl.appendChild(share);

    // 3) per-download rows container
    const dl = document.createElement('div');
    dl.id = 'jobDownloads';
    jobStatusEl.appendChild(dl);
  }
  function setStatus(text){
    const s = el('#jobStatusText');
    if (s) s.textContent = text || '';
    else renderStatusHeader(text);
  }
  function shareUrlFromId(id){ return id ? `${SHARE_BASE}${encodeURIComponent(id)}/` : null; }
  function renderShareHref(url) {
    const row = el('#shareHref');
    if (!row) return;
    if (url) {
      row.innerHTML = `Share: <a href="${url}" target="_blank" rel="noopener">${url}</a>`;
      row.style.display = '';
    } else {
      row.innerHTML = '';
      row.style.display = 'none';
    }
  }
  function clearShareHref() { renderShareHref(null); }

  // Extract full share folder name from messages like:
  // "Preparing share folder Star Fire v1.2.3-...-1757982845"
  function maybeExtractShareIdFromText(t) {
    if (!t || typeof t !== 'string') return null;
    const m = t.match(/Preparing\s+(?:the\s+)?share\s+folder\s+(.+?)\s*$/i);
    const candidate = m ? m[1].trim() : null;
    return candidate ? candidate.replace(/[\s:…]+$/u, '') : null;
  }
  function setShareIdFromTextIfAny(text) {
    const id = maybeExtractShareIdFromText(text);
    if (id && id !== CURRENT_SHARE_ID) {
      CURRENT_SHARE_ID = id;
      renderShareHref(shareUrlFromId(id));
    }
  }
  function setShareIdExplicit(id) {
    if (id && id !== CURRENT_SHARE_ID) {
      CURRENT_SHARE_ID = id;
      renderShareHref(shareUrlFromId(id));
    }
  }

  // ----- per-download rows (limit 5) -----
  const activeDownloads = new Map(); // key -> {name, received, total, pct, status, updatedAt}
  const MAX_ACTIVE = 5;

  function clearDownloadList(){
    const dl = el('#jobDownloads');
    if (dl) dl.innerHTML = '';
    activeDownloads.clear();
  }

  // NEW: mark a file as "segmenting" when backend logs "Segmented download xN for <name>"
  function maybeMarkSegmenting(msg){
    if (!msg || typeof msg !== 'string') return;
    const m = msg.match(/Segmented download x\d+\s+for\s+(.+)$/i);
    if (!m) return;
    const name = m[1].trim();
    const key  = name;
    const rec  = activeDownloads.get(key) || { name, received: 0, total: undefined, pct: undefined, updatedAt: Date.now() };
    rec.status = 'segmenting';
    rec.updatedAt = Date.now();
    activeDownloads.set(key, rec);
    ensureDownloadRow(key, name);
    setDownloadVisuals(key, rec.pct, rec.received, rec.total, rec.status);
  }

  function ensureDownloadRow(key, name){
    const dl = el('#jobDownloads');
    if (!dl || !key) return null;

    let row = el(`[data-dl="${CSS.escape(key)}"]`, dl);
    if (!row) {
      row = document.createElement('div');
      row.className = 'dl-row';
      row.dataset.dl = key;
      row.innerHTML = `
        <div class="dl-top">
          <span class="dl-name" title="${escapeHtml(name || key)}">${escapeHtml(name || key)}</span>
          <span class="dl-meta mono">
            <span class="dl-status">waiting</span>
            <span class="dl-sep"> — </span>
            <span class="dl-sizes"></span>
          </span>
        </div>
        <div class="mini-bar"><div class="mini-fill" style="width:0%"></div></div>
      `;
      dl.appendChild(row);
    } else {
      const nm = el('.dl-name', row);
      if (nm && name && nm.textContent !== name) { nm.textContent = name; nm.title = name; }
    }
    return row;
  }

  function setDownloadVisuals(key, pct, doneBytes, totalBytes, status){
    const row = ensureDownloadRow(key);
    if (!row) return;

    const fill = el('.mini-fill', row);
    if (fill) fill.style.width = (typeof pct === 'number' ? Math.max(0, Math.min(100, pct)) : 0) + '%';

    const statusEl = el('.dl-status', row);
    const sizesEl  = el('.dl-sizes', row);

    // status label
    let label = 'downloading';
    if (status) {
      label = status;
    } else if (typeof pct === 'number' && pct >= 100) {
      label = 'complete';
    } else if (typeof pct === 'number') {
      label = 'downloading';
    } else if (typeof doneBytes === 'number' && doneBytes > 0) {
      label = 'downloading';
    } else {
      label = 'waiting';
    }
    if (statusEl) statusEl.textContent = label;

    // sizes + %
    const dMB = toMB(doneBytes);
    const tMB = toMB(totalBytes);
    let metaTxt = '';

    if (typeof dMB === 'number' && typeof tMB === 'number' && tMB > 0) {
      const pctTxt = (typeof pct === 'number') ? `${pct.toFixed(0)}%` : `${(dMB*100/tMB).toFixed(0)}%`;
      metaTxt = `${pctTxt} — ${dMB.toFixed(1)} / ${tMB.toFixed(1)} MB`;
    } else if (typeof tMB === 'number' && tMB > 0 && typeof pct === 'number') {
      metaTxt = `${pct.toFixed(0)}% — ${(tMB*(pct/100)).toFixed(1)} / ${tMB.toFixed(1)} MB`;
    } else if (typeof pct === 'number') {
      metaTxt = `${pct.toFixed(0)}%`;
    } else {
      metaTxt = '';
    }

    if (sizesEl) sizesEl.textContent = metaTxt;
  }

  function pruneActiveList(){
    const dl = el('#jobDownloads');
    if (!dl) return;

    // drop rows not tracked anymore (finished)
    els('[data-dl]', dl).forEach(node => {
      const key = node.getAttribute('data-dl') || '';
      if (!activeDownloads.has(key)) node.remove();
    });

    // keep only 5 most-recently updated
    const entries = Array.from(activeDownloads.entries())
      .sort((a,b) => b[1].updatedAt - a[1].updatedAt);
    const keep = new Set(entries.slice(0, MAX_ACTIVE).map(([k]) => k));

    for (const [key] of activeDownloads) {
      if (!keep.has(key)) {
        activeDownloads.delete(key);
        const node = el(`[data-dl="${CSS.escape(key)}"]`, dl);
        if (node) node.remove();
      }
    }
  }

  // ---------- Overall progress ----------
  function setOverallProgress(pct, label){
    if (overallFill && typeof pct === 'number') {
      overallFill.style.width = Math.max(0, Math.min(100, pct)) + '%';
    }
    if (overallText) {
      overallText.textContent = label || (typeof pct === 'number' ? `${pct.toFixed(0)}%` : '');
    }
  }
  function recomputeOverall(phaseHint){
    let totalKnown = 0, recvKnown = 0, totalFiles = activeDownloads.size, completed = 0;
    for (const [, v] of activeDownloads) {
      if (typeof v.total === 'number' && v.total > 0) {
        totalKnown += v.total;
        recvKnown += Math.min(v.received || 0, v.total);
      } else if (v.pct === 100) {
        completed++;
      }
    }
    let pct = null;
    if (totalKnown > 0) pct = Math.floor(recvKnown * 100 / totalKnown);
    else if (totalFiles > 0) pct = Math.floor((completed * 100) / totalFiles);

    if (pct !== null) setOverallProgress(pct, `${phaseHint || 'downloading'} — ${pct}%`);
    else setOverallProgress(undefined, phaseHint || 'downloading');
  }

  // ---------- Actions area (visible only when a job is attached) ----------
  function clearActions(){
    if (jobActionsEl) jobActionsEl.innerHTML = '';
  }
  function ensureActionsVisible(){
    if (!jobActionsEl) return;
    jobActionsEl.style.display = CURRENT_JOB_ID ? '' : 'none';
  }
  async function handleCancel(jobId){
    try {
      await ensureCsrf();
      const headers = {};
      if (CSRF) headers['X-CSRF'] = CSRF;
      const r = await fetch(`/job/${encodeURIComponent(jobId)}/cancel`, {
        method: 'POST',
        headers,
        credentials: 'same-origin'
      });
      if (!r.ok) {
        const t = await r.text().catch(()=> '');
        logLine(`Cancel failed (${r.status}): ${t || 'server error'}`);
        return;
      }
      logLine('Cancel requested…');
    } catch {
      logLine('Cancel error: network issue.');
    }
  }
  function renderCancel(){
    if (!jobActionsEl || !CURRENT_JOB_ID) return;
    let btn = el('#cancelBtn', jobActionsEl);
    if (!btn) {
      btn = document.createElement('button');
      btn.id = 'cancelBtn';
      btn.type = 'button';
      btn.textContent = 'Cancel';
      btn.className = 'button danger';
      btn.addEventListener('click', () => handleCancel(CURRENT_JOB_ID));
      jobActionsEl.appendChild(btn);
    }
  }
  function removeCancel(){
    const b = el('#cancelBtn', jobActionsEl);
    if (b) b.remove();
  }

  // ========== Snapshot + always-on SSE with auto-reconnect ==========
  let esRetryTimer = null;

  async function snapshotJobState(jobId) {
    try {
      const r = await fetch('/jobs?limit=10', { credentials: 'same-origin' });
      const j = await r.json().catch(()=>null);
      const items = j && Array.isArray(j.items) ? j.items : [];
      const it = items.find(x => x.id === jobId);
      if (!it) return;

      if (it.status) setStatus(it.status);

      if (it.status === 'done' && it.public) {
        const pid = it.public.pid || it.public.shareId;
        if (pid) setShareIdExplicit(pid);
        setOverallProgress(100, 'Done');
        removeCancel();
      }
      if (it.status === 'error') {
        logLine('ERROR: ' + (it.error || 'unknown error'));
        removeCancel();
      }
      if (it.status === 'cancelled') {
        logLine('Cancelled.');
        removeCancel();
      }
    } catch {}
  }

  function connectSSE(jobId) {
    // close previous, if any
    try { es && es.close(); } catch {}
    es = new EventSource('/events/' + encodeURIComponent(jobId));

    es.onmessage = (msg) => {
      if (!msg.data) return;
      let data;
      try { data = JSON.parse(msg.data); } catch { return; }

      // short status + log
      if (data.message) {
        setStatus(data.message);
        logLine(data.message);
        setShareIdFromTextIfAny(data.message);
        maybeMarkSegmenting(data.message); // NEW: mark row as 'segmenting' when we see that message
      }
      if (data.status) {
        const txt = data.message ? `${data.status}: ${data.message}` : data.status;
        setStatus(txt);
        if (data.status !== 'running') logLine(`status → ${txt}`);
        setShareIdFromTextIfAny(txt);
      }

      // overall progress (many shapes)
      if (data.type === 'overall') {
        const pct = (typeof data.pct === 'number') ? data.pct
                  : (typeof data.total === 'number' && data.total > 0)
                    ? Math.floor((data.received||0) * 100 / data.total)
                    : null;
        const phase = data.phase || 'downloading';
        if (pct !== null) setOverallProgress(pct, `${phase} — ${pct}%`);
        else setOverallProgress(undefined, phase);
      } else if (typeof data.progress === 'number' || data.progress_text) {
        setOverallProgress(data.progress, data.progress_text || undefined);
      }

      // explicit share fields (server may send them)
      if (data?.public?.shareId) setShareIdExplicit(data.public.shareId);
      else if (typeof data.shareId === 'string') setShareIdExplicit(data.shareId);
      else if (typeof data.share_folder === 'string') setShareIdExplicit(data.share_folder);

      // per-download items
      const list = Array.isArray(data.downloads) ? data.downloads
                 : Array.isArray(data.files)     ? data.files
                 : (data.type === 'progress' ? [data] : null);

      if (list) {
        for (const item of list) {
          const key = item.key || item.name || item.file || item.url || item.l || item.link || '';
          const name = item.name || item.file || key;
          const pct = typeof item.pct === 'number' ? item.pct
                   : (typeof item.total === 'number' && item.total > 0 && typeof item.received === 'number')
                     ? Math.floor(item.received * 100 / item.total)
                     : undefined;
          const received = item.received;
          const total    = item.total;

          const finished = (item.status && /done|complete/i.test(item.status)) ||
                           (typeof pct === 'number' && pct >= 100) ||
                           (typeof total==='number' && typeof received==='number' && received >= total);

          if (finished) {
            activeDownloads.delete(key);
            const node = document.querySelector(`#jobDownloads [data-dl="${CSS.escape(key)}"]`);
            if (node) node.remove();
          } else {
            const rec = activeDownloads.get(key) || { name };
            rec.name      = name;
            rec.received  = received;
            rec.total     = total;
            rec.pct       = pct;
            rec.status    = rec.status || 'downloading';  // keep "segmenting" if already set
            rec.updatedAt = Date.now();
            activeDownloads.set(key, rec);

            ensureDownloadRow(key, name);
            setDownloadVisuals(key, pct, received, total, rec.status);
          }
        }
        pruneActiveList();    // caps visible rows to 5
        const phase = data.phase || (String(jobStatusEl?.textContent || '').includes('upload') ? 'uploading' : 'downloading');
        recomputeOverall(phase);
      }

      // finals — IMPORTANT: DO NOT close SSE here
      if (data.status === 'error') {
        logLine(`ERROR: ${data.error || 'unknown error'}`);
        removeCancel();
      }
      if (data.status === 'cancelled') {
        logLine('Cancelled.');
        removeCancel();
      }
      if (data.status === 'done') {
        setOverallProgress(100, 'Done');
        setStatus('done');
        if (CURRENT_SHARE_ID) renderShareHref(shareUrlFromId(CURRENT_SHARE_ID));
        removeCancel();
      }

      if (data.type === 'cleared') {
        logLine('Job cleared by server');
        localStorage.removeItem('lastJobId');
        removeCancel();
        // keep connection open; server will just send keepalives
      }
    };

    es.onerror = () => {
      logLine('SSE hiccup — reconnecting…');
      try { es && es.close(); } catch {}
      es = null;
      clearTimeout(esRetryTimer);
      esRetryTimer = setTimeout(() => {
        if (CURRENT_JOB_ID) connectSSE(CURRENT_JOB_ID);
      }, 1000);
    };

    // In case the job already finished (fast duplicate), pull one-shot snapshot
    snapshotJobState(jobId);
  }

  // ---------- Attach to job + SSE (uses connectSSE; never auto-close) ----------
  function attachToJob(jobId, clearLog){
    CURRENT_JOB_ID   = jobId || null;
    CURRENT_SHARE_ID = null;

    clearActions();
    ensureActionsVisible();

    if (!CURRENT_JOB_ID) return;

    if (clearLog && logBox) logBox.innerHTML = '';

    if (jobIdEl) jobIdEl.textContent = `(${jobId})`;
    setOverallProgress(0, '');
    renderStatusHeader('queued');
    clearShareHref();
    clearDownloadList();
    renderCancel(); // show cancel now that a job is attached

    logLine(`Job ${jobId} attached`);
    localStorage.setItem('lastJobId', jobId);

    // persistent SSE connection + snapshot
    connectSSE(jobId);
  }

  // ---------- Start job (/job with X-CSRF) ----------
  const form = el('#jobForm');
  if (form) {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();

      const fd = new FormData();
      fd.append('includeTrackers', toggle && toggle.checked ? 'true' : 'false');

      if (currentKind === 'magnet') {
        const m = (el('textarea[name="magnet"]')?.value || '').trim();
        if (!m) return alert('Enter a magnet link');
        fd.append('kind', 'magnet');
        fd.append('magnet', m);
      } else if (currentKind === 'torrent') {
        const file = el('input[name="torrent"]')?.files?.[0];
        if (!file) return alert('Choose a .torrent file');
        fd.append('kind', 'torrent');
        fd.append('torrent', file);
      } else {
        const urls = (el('textarea[name="urls"]')?.value || '').trim();
        if (!urls) return alert('Enter at least one URL');
        fd.append('kind', 'url');
        fd.append('urls', urls);
      }

      try {
        await ensureCsrf();
        const headers = {};
        if (CSRF) headers['X-CSRF'] = CSRF;

        const res = await fetch('/job', {
          method:'POST',
          headers,            // include X-CSRF; browser sets multipart boundary
          body: fd,
          credentials:'same-origin'
        });
        const data = await res.json();
        if (!data || !data.ok || !data.jobId) {
          return alert('Failed to start: ' + (data && data.error || 'unknown error'));
        }
        attachToJob(data.jobId, true);
        ensureActionsVisible(); // show actions now that a job is attached
      } catch (err) {
        console.error(err);
        alert('Network error creating job');
      }
    });
  }

  // ---------- Reattach last job on load ----------
  function init(){
    const saved = localStorage.getItem('lastJobId');
    if (saved) {
      attachToJob(saved, false);
    } else {
      CURRENT_JOB_ID = null;
      clearActions();
      ensureActionsVisible(); // hide actions when no job
    }
  }
})();
