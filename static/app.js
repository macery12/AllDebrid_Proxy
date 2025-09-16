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
  // "Preparing share folder StarFireEternalCyclev1.25.271MULTi8FitGirlRepack-ext.to-1757982845"
  // IMPORTANT: capture to end-of-line (don't stop at the first '.').
  function maybeExtractShareIdFromText(t) {
    if (!t || typeof t !== 'string') return null;
    const m = t.match(/Preparing\s+(?:the\s+)?share\s+folder\s+(.+?)\s*$/i);
    //            ↑ greedy to end-of-line, then trim trailing whitespace
    if (!m) return null;
    const candidate = m[1].trim();
    // Remove only trailing whitespace/colons/ellipsis—not dots inside the name
    return candidate.replace(/[\s:…]+$/u, '');
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
  const activeDownloads = new Map(); // key -> {name, received, total, pct, updatedAt}
  const MAX_ACTIVE = 5;

  function clearDownloadList(){
    const dl = el('#jobDownloads');
    if (dl) dl.innerHTML = '';
    activeDownloads.clear();
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
          <span class="dl-meta mono"></span>
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
  function setDownloadVisuals(key, pct, doneBytes, totalBytes){
    const row = ensureDownloadRow(key);
    if (!row) return;

    const fill = el('.mini-fill', row);
    if (fill) fill.style.width = (typeof pct === 'number' ? Math.max(0, Math.min(100, pct)) : 0) + '%';

    const meta = el('.dl-meta', row);
    if (meta) {
      const dMB = toMB(doneBytes);
      const tMB = toMB(totalBytes);
      const pctTxt = (typeof pct === 'number') ? `${pct.toFixed(0)}%` : '';
      let sizeTxt = '';
      if (typeof dMB === 'number' && typeof tMB === 'number' && tMB > 0) {
        sizeTxt = `${dMB.toFixed(1)} / ${tMB.toFixed(1)} MB`;
      } else if (typeof tMB === 'number' && tMB > 0 && typeof pct === 'number') {
        sizeTxt = `${(tMB*(pct/100)).toFixed(1)} / ${tMB.toFixed(1)} MB`;
      }
      meta.textContent = [pctTxt, sizeTxt].filter(Boolean).join(' — ');
    }
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

  // ---------- Attach to job + SSE ----------
  function attachToJob(jobId, clearLog){
    // close previous
    try { es && es.close(); } catch {}
    es = null;

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

    es = new EventSource('/events/' + encodeURIComponent(jobId));

    es.onmessage = (msg) => {
      if (!msg.data) return;
      let data;
      try { data = JSON.parse(msg.data); } catch { return; }

      // short status + log
      if (data.message) {
        setStatus(data.message);
        logLine(data.message);
        // Try to extract full share name from this message
        setShareIdFromTextIfAny(data.message);
      }
      if (data.status) {
        const txt = data.message ? `${data.status}: ${data.message}` : data.status;
        setStatus(txt);
        if (data.status !== 'running') logLine(`status → ${txt}`);
        // Also try on combined text (covers "uploading: Preparing share folder <name>")
        setShareIdFromTextIfAny(txt);
      }

      // overall progress (support multiple shapes)
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

      // explicit share fields (if server sends them)
      if (data?.public?.shareId) setShareIdExplicit(data.public.shareId);
      else if (typeof data.shareId === 'string') setShareIdExplicit(data.shareId);
      else if (typeof data.share_folder === 'string') setShareIdExplicit(data.share_folder);

      // per-download items
      const list = Array.isArray(data.downloads) ? data.downloads
                 : Array.isArray(data.files)     ? data.files
                 : (data.type === 'progress' ? [data] : null);

      if (Array.isArray(list)) {
        for (const item of list) {
          const key = String(item.key ?? item.id ?? item.file ?? item.name ?? '');
          if (!key) continue;

          const name = item.name || item.file || key;
          const total = (typeof item.total_bytes === 'number') ? item.total_bytes
                      : (typeof item.total === 'number') ? item.total : undefined;
          const received = (typeof item.bytes === 'number') ? item.bytes
                         : (typeof item.received === 'number') ? item.received : undefined;

          let pct = (typeof item.pct === 'number') ? item.pct : undefined;
          if (pct == null && typeof total === 'number' && total > 0 && typeof received === 'number') {
            pct = Math.floor((received * 100) / total);
          }

          const finished = (item.status && /done|complete/i.test(item.status)) ||
                           (typeof pct === 'number' && pct >= 100) ||
                           (typeof total==='number' && typeof received==='number' && received >= total);

          if (finished) {
            activeDownloads.delete(key);
            const node = el(`#jobDownloads [data-dl="${CSS.escape(key)}"]`);
            if (node) node.remove();
          } else {
            activeDownloads.set(key, { name, received, total, pct, updatedAt: Date.now() });
            ensureDownloadRow(key, name);
            setDownloadVisuals(key, pct, received, total);
          }
        }
        pruneActiveList();
        const phase = data.phase || (String(jobStatusEl?.textContent || '').includes('upload') ? 'uploading' : 'downloading');
        recomputeOverall(phase);
      }

      // finals
      if (data.status === 'error') {
        logLine(`ERROR: ${data.error || 'unknown error'}`);
        removeCancel();
        try { es.close(); } catch {}
      }
      if (data.status === 'cancelled') {
        logLine('Cancelled.');
        removeCancel();
        try { es.close(); } catch {}
      }
      if (data.status === 'done') {
        setOverallProgress(100, 'Done');
        setStatus('done');
        // ensure share link is visible if we got the name from earlier messages
        if (CURRENT_SHARE_ID) renderShareHref(shareUrlFromId(CURRENT_SHARE_ID));
        removeCancel();
        try { es.close(); } catch {}
      }

      if (data.type === 'cleared') {
        logLine('Job cleared by server');
        localStorage.removeItem('lastJobId');
        removeCancel();
        try { es.close(); } catch {}
      }
    };

    es.onerror = () => {
      logLine('SSE connection hiccup; waiting for keep-alives.');
    };
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
          headers,            // include X-CSRF; let browser set multipart boundary
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