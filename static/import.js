/* cycliq — importing history from Apple Health, a Flo export, or CSV. */

async function openImport() {
  const guide = await api('/api/import/guide');
  openSheet(`<h2>Import your history</h2>
    <p class="muted">Nothing is written until you have seen what was found.</p>
    <input type="file" id="import-file" accept=".zip,.xml,.json,.csv"
      style="margin-top:14px" onchange="previewImport()">
    <div id="import-result"></div>
    <div class="group-label">Where to get an export</div>
    ${guide.sources.map((s) => `<div class="card" style="margin-bottom:10px">
      <h3>${esc(s.title)}</h3>
      <p>${esc(s.why)}</p>
      <p style="margin-top:8px">${s.steps.map((step) => `• ${esc(step)}`).join('<br>')}</p>
      ${s.caveat ? `<p class="fine" style="margin-top:8px">${esc(s.caveat)}</p>` : ''}
      <p class="fine" style="margin-top:8px"><strong>Brings over:</strong> ${esc(s.brings)}</p>
    </div>`).join('')}
    ${guide.notes.map((n) => `<p class="fine">• ${esc(n)}</p>`).join('')}`);
}

async function previewImport() {
  const input = $('#import-file');
  const host = $('#import-result');
  if (!input.files.length) return;
  host.innerHTML = '<div class="card"><p>Reading…</p></div>';

  const form = new FormData();
  form.append('file', input.files[0]);
  let data;
  try {
    const res = await fetch('/api/import/preview', {
      method: 'POST', credentials: 'same-origin', body: form,
    });
    data = await res.json();
    if (!res.ok) throw new Error(data.detail?.message || `HTTP ${res.status}`);
  } catch (err) {
    host.innerHTML = `<div class="card"><span class="kicker">could not read it</span>
      <p>${esc(err.message)}</p></div>`;
    return;
  }

  const p = data.preview;
  const range = p.date_range ? `${fmtDay(p.date_range[0])} – ${fmtDay(p.date_range[1])}` : '—';
  host.innerHTML = `<div class="card" style="margin-top:14px">
    <span class="kicker">found in ${esc(data.filename || 'your file')}</span>
    <h3>${p.period_start_count} periods · ${p.log_entries} entries</h3>
    <p>Across ${p.logged_days} days, ${esc(range)}. Read as <strong>${esc(p.source)}</strong>.</p>
    <p class="muted" style="margin-top:8px">You currently have ${data.existing.periods} periods
      and ${data.existing.logs} entries. Importing merges — nothing is overwritten or duplicated.</p>
    ${p.warnings.map((w) => `<p class="fine" style="margin-top:8px">⚠︎ ${esc(w)}</p>`).join('')}
    ${p.by_symptom.length ? `<div class="group-label">What came through</div>
      <div class="chipset">${p.by_symptom.slice(0, 18).map((s) =>
        `<span class="chip">${esc(s.label)} · ${s.count}</span>`).join('')}</div>` : ''}
    ${p.skipped.length ? `<div class="group-label">Skipped</div>
      ${p.skipped.slice(0, 8).map((s) => `<p class="fine">• ${esc(s.reason)} (${s.count})</p>`).join('')}
      <p class="fine" style="margin-top:6px">Anything listed here was left out rather than guessed at.</p>` : ''}
    <button class="btn primary" style="width:100%;margin-top:14px" onclick="applyImport()">
      Import ${p.period_start_count} periods and ${p.log_entries} entries</button>
  </div>`;
}

async function applyImport() {
  try {
    const out = await api('/api/import/apply', { method: 'POST' });
    closeSheet();
    toast(`Imported ${out.periods_added} periods, ${out.logs_added} entries`);
    await go('today');
  } catch (err) { toast(err.message); }
}
