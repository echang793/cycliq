/* cycliq — core: api, auth gate, onboarding, tab routing, Today, Calendar, logging. */

const State = {
  user: null,
  billing: null,
  prediction: null,
  catalog: null,
  calMonth: null,
  view: 'today',
};

/* ── api ──────────────────────────────────────────────────────── */

async function api(path, opts = {}) {
  const res = await fetch(path, {
    credentials: 'same-origin',
    headers: opts.body ? { 'Content-Type': 'application/json' } : {},
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { raw: text }; }
  if (!res.ok) {
    const err = new Error((data && data.detail && data.detail.message) || `HTTP ${res.status}`);
    err.status = res.status;
    err.detail = (data && data.detail) || data;
    throw err;
  }
  return data;
}

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function toast(message) {
  const el = $('#toast');
  el.textContent = message;
  el.classList.remove('hidden');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.add('hidden'), 2600);
}

// Local calendar date, not UTC — every caller wants "what day is this on this
// device," and toISOString() answers a different question (it round-trips
// through UTC, which shifts the date by one for roughly half the world's
// timezones: backward east of UTC on locally-built midnight dates, forward
// west of UTC on "now" in the evening). Bug found 2026-08-06 debugging session:
// the log-period sheet defaulted to tomorrow for anyone west of UTC after ~5pm.
const pad2 = (n) => String(n).padStart(2, '0');
const iso = (d) => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
const parseISO = (s) => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d); };
const fmtDay = (s) => parseISO(s).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });

/* ── sheet ────────────────────────────────────────────────────── */

function openSheet(html) {
  $('#sheet-content').innerHTML = html;
  $('#sheet').classList.remove('hidden');
}
function closeSheet() { $('#sheet').classList.add('hidden'); }

/* ── premium gate helper, used by every screen ────────────────── */

const ICON_LOCK = '<svg class="icon" viewBox="0 0 24 24"><rect x="5" y="11" width="14" height="9" rx="2.5"/><path d="M8 11V7.5a4 4 0 0 1 8 0V11"/></svg>';

function lockedCard(detail, previewHtml) {
  const feature = (detail && detail.feature) || 'This';
  return `<div class="card locked">
    <div class="blurred">${previewHtml}</div>
    <div class="lock-overlay">
      ${ICON_LOCK}
      <span class="badge">Premium</span>
      <p class="muted">${esc(feature)} is part of Premium.</p>
      <button class="btn primary" onclick="showPaywall()">Start ${detail?.trial_days || 7}-day free trial</button>
    </div>
  </div>`;
}

async function guarded(path, renderOk, previewHtml) {
  try {
    return renderOk(await api(path));
  } catch (err) {
    if (err.status === 402) return lockedCard(err.detail, previewHtml);
    return `<div class="card"><p>${esc(err.message)}</p></div>`;
  }
}

/* ── auth gate ────────────────────────────────────────────────── */

function showGate(which = 'choose') {
  $('#boot').classList.add('hidden');
  $('#gate').classList.remove('hidden');
  $('#app').classList.add('hidden');
  $('#onboarding').classList.add('hidden');
  ['choose', 'signup', 'login', 'recovery'].forEach((k) => {
    const el = k === 'choose' ? $('#gate-choose') : $(`#form-${k}`);
    el.classList.toggle('hidden', k !== which);
  });
  $('#gate-error').classList.add('hidden');
}

function gateError(message) {
  const el = $('#gate-error');
  el.textContent = message;
  el.classList.remove('hidden');
}

function wireGate() {
  $$('[data-gate]').forEach((b) => b.addEventListener('click', () => showGate(b.dataset.gate)));

  $('#form-signup').addEventListener('submit', async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      await api('/api/auth/signup', { method: 'POST', body: { email: f.get('email'), password: f.get('password') } });
      await start();
    } catch (err) { gateError(err.message); }
  });

  $('#form-login').addEventListener('submit', async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      await api('/api/auth/login', { method: 'POST', body: { email: f.get('email'), password: f.get('password') } });
      await start();
    } catch (err) { gateError(err.message); }
  });

  $('#form-recovery').addEventListener('submit', async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      await api('/api/auth/login/recovery', { method: 'POST', body: { handle: f.get('handle'), code: f.get('code') } });
      await start();
    } catch (err) { gateError(err.message); }
  });

  $('[data-gate="anon"]').addEventListener('click', async () => {
    try {
      const out = await api('/api/auth/anonymous', { method: 'POST' });
      alert(`Anonymous Mode is on.\n\nHandle: ${out.user.handle}\nRecovery code: ${out.recovery_code}\n\nWrite these down. With no email on the account there is no other way back in.`);
      await start();
    } catch (err) { gateError(err.message); }
  });
}

/* ── onboarding ───────────────────────────────────────────────── */

const Onb = { step: 0, goal: null, birth_year: null, lmp: null, cycle: 28, period: 5 };

function onbShow(step) {
  Onb.step = step;
  $$('.onb-step').forEach((el) => el.classList.toggle('hidden', Number(el.dataset.step) !== step));
  $('#onb-bar').style.width = `${((step + 1) / 4) * 100}%`;
}

function wireOnboarding() {
  $$('#onb-goal .choice').forEach((b) => b.addEventListener('click', () => {
    Onb.goal = b.dataset.value;
    $$('#onb-goal .choice').forEach((x) => x.classList.remove('sel'));
    b.classList.add('sel');
    setTimeout(() => onbShow(1), 140);
  }));

  $$('#onb-age .choice').forEach((b) => b.addEventListener('click', () => {
    Onb.birth_year = Number(b.dataset.value);
    $$('#onb-age .choice').forEach((x) => x.classList.remove('sel'));
    b.classList.add('sel');
    setTimeout(() => onbShow(2), 140);
  }));

  $('#onb-lmp').value = iso(new Date());
  $('#onb-lmp-next').addEventListener('click', () => { Onb.lmp = $('#onb-lmp').value; onbShow(3); });
  $('#onb-lmp-skip').addEventListener('click', () => { Onb.lmp = null; onbShow(3); });

  const cycle = $('#onb-cycle'); const period = $('#onb-period');
  cycle.addEventListener('input', () => { Onb.cycle = +cycle.value; $('#onb-cycle-out').textContent = `${cycle.value} days`; });
  period.addEventListener('input', () => { Onb.period = +period.value; $('#onb-period-out').textContent = `${period.value} days`; });

  $('#onb-finish').addEventListener('click', async () => {
    await api('/api/me', {
      method: 'PATCH',
      body: {
        goal: Onb.goal,
        mode: Onb.goal === 'pregnant' ? 'pregnancy' : Onb.goal === 'ttc' ? 'ttc' : 'cycle',
        birth_year: Onb.birth_year,
        avg_cycle_len: Onb.cycle,
        avg_period_len: Onb.period,
        onboarded: true,
      },
    });
    if (Onb.lmp) {
      const end = parseISO(Onb.lmp);
      end.setDate(end.getDate() + Onb.period - 1);
      await api('/api/periods', { method: 'POST', body: { start_date: Onb.lmp, end_date: iso(end) } });
    }
    if (Onb.goal === 'pregnant' && Onb.lmp) {
      await api('/api/pregnancy/start', { method: 'POST', body: { lmp_date: Onb.lmp } });
    }
    await start();
  });
}

/* ── Today: the ring ──────────────────────────────────────────── */

function ringSvg(p) {
  const R = 120, C = 2 * Math.PI * R;
  const len = Math.max(p.cycle_len || 28, 1);
  const day = p.cycle_day || 0;
  const seg = (from, to, color, width) => {
    const a = Math.max(0, Math.min(from, len)) / len;
    const b = Math.max(0, Math.min(to, len)) / len;
    if (b <= a) return '';
    return `<circle r="${R}" cx="150" cy="150" fill="none" stroke="${color}" stroke-width="${width}"
      stroke-dasharray="${((b - a) * C).toFixed(1)} ${C}" stroke-dashoffset="${(-a * C).toFixed(1)}"
      transform="rotate(-90 150 150)" stroke-linecap="round"/>`;
  };
  const ovDay = Math.max(1, (p.cycle_len || 28) - (p.luteal_len || 14));
  const progress = day ? (day / len) * C : 0;

  const headline = p.days_to_period === null || p.days_to_period === undefined
    ? 'Log a period'
    : p.days_to_period > 0 ? `${p.days_to_period} days`
      : p.days_to_period === 0 ? 'Today' : `${Math.abs(p.days_to_period)} days late`;
  const lead = p.next_period ? 'until your period' : 'to start predictions';
  const windowText = p.next_period
    ? `window ${fmtDay(p.next_period_low)} – ${fmtDay(p.next_period_high)}`
    : '';
  const dayLine = day ? `Day ${day}${p.phase ? ` · ${p.phase} phase` : ''}` : 'No data yet';
  const innerR = R - 20, innerC = 2 * Math.PI * innerR;

  return `<svg class="ring" viewBox="0 0 300 300" role="img" aria-label="Cycle ring: ${esc(dayLine)}, ${esc(headline)} ${esc(lead)}">
    <circle r="${R}" cx="150" cy="150" fill="none" stroke="var(--line)" stroke-width="16"/>
    ${seg(0, p.period_len || 5, 'var(--plum)', 16)}
    ${seg(ovDay - 5, ovDay + 2, 'var(--fertile)', 16)}
    ${seg(ovDay - 0.5, ovDay + 0.5, 'var(--ovul)', 16)}
    <circle r="${innerR}" cx="150" cy="150" fill="none" stroke="var(--ink)" stroke-width="2"
      stroke-dasharray="${(progress / C * innerC).toFixed(1)} ${innerC.toFixed(1)}" transform="rotate(-90 150 150)" stroke-linecap="round" opacity=".35"/>
    <text x="150" y="124" text-anchor="middle" class="ring-day">${esc(dayLine)}</text>
    <text x="150" y="168" text-anchor="middle" class="ring-big">${esc(headline)}</text>
    <text x="150" y="192" text-anchor="middle" class="ring-sub">${esc(lead)}</text>
    <text x="150" y="212" text-anchor="middle" class="ring-sub">${esc(windowText)}</text>
  </svg>`;
}

function cardHtml(c) {
  const link = c.article_id
    ? `<p style="margin-top:8px"><a href="#" onclick="openArticle('${c.article_id}');return false">Read: ${esc(c.article_title)} →</a></p>` : '';
  if (c.locked) {
    return lockedCard({ feature: c.title, trial_days: 7 },
      `<h3>${esc(c.title)}</h3><p>${esc(c.body)}</p>`);
  }
  return `<div class="card">
    <span class="kicker">${esc(c.kind)}</span>
    <h3>${esc(c.title)}</h3><p>${esc(c.body)}</p>${link}</div>`;
}

async function renderToday() {
  const data = await api('/api/insights/today');
  State.prediction = data.prediction;
  State.billing = State.billing || (await api('/api/billing/status'));

  $('#today-date').textContent = new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' });
  $('#ring-host').innerHTML = ringSvg(data.prediction);
  $('#today-cards').innerHTML = data.cards.map(cardHtml).join('');
  await renderDailyQuiz();

  const due = await api('/api/reminders/due');
  $('#due-reminders').innerHTML = due.due.length
    ? `<div class="card"><span class="kicker">reminders</span>${due.due.map((r) => `<p>• ${esc(r.label)} at ${esc(r.time_of_day)}</p>`).join('')}</div>`
    : '';

  $('#mode-panel').innerHTML = '';
  if (State.user.mode === 'pregnancy') await renderPregnancyPanel();
  else if (State.user.mode === 'ttc') await renderTtcPanel();
}

/* ── logging ──────────────────────────────────────────────────── */

async function openPeriodSheet() {
  const today = iso(new Date());
  openSheet(`<h2>Log a period</h2>
    <p class="muted">Predictions are anchored to the start date.</p>
    <div class="stack" style="margin-top:14px">
      <label class="muted">Start date<input type="date" id="p-start" value="${today}"></label>
      <label class="muted">End date (optional)<input type="date" id="p-end"></label>
      <button class="btn primary" onclick="savePeriod()">Save</button>
      <button class="btn ghost" onclick="closeSheet()">Cancel</button>
    </div>
    <div id="period-history" class="list" style="margin-top:20px"></div>`);
  const data = await api('/api/periods');
  $('#period-history').innerHTML = `<div class="group-label">Logged periods</div>` + (data.periods.length
    ? data.periods.slice(0, 8).map((p) => `<div class="row"><span><strong>${fmtDay(p.start_date)}</strong>
        <small>${p.end_date ? 'to ' + fmtDay(p.end_date) : 'no end date'}</small></span>
        <button class="btn small" onclick="deletePeriod(${p.id})">Remove</button></div>`).join('')
    : '<p class="muted">None yet.</p>');
}

async function savePeriod() {
  const start = $('#p-start').value; const end = $('#p-end').value || null;
  if (!start) return toast('Pick a start date');
  await api('/api/periods', { method: 'POST', body: { start_date: start, end_date: end } });
  closeSheet(); toast('Period logged'); await renderToday(); await renderCalendar();
}

async function deletePeriod(id) {
  await api(`/api/periods/${id}`, { method: 'DELETE' });
  closeSheet(); toast('Removed'); await renderToday(); await renderCalendar();
}

async function openLogSheet(dateStr) {
  const day = dateStr || iso(new Date());
  State.catalog = State.catalog || (await api('/api/log/catalog'));
  const current = await api(`/api/log/${day}`);
  const active = new Set(current.entries.map((e) => e.code));
  const values = Object.fromEntries(current.entries.filter((e) => e.value !== null).map((e) => [e.code, e.value]));

  const groups = State.catalog.categories.map((cat) => {
    if (cat.kind === 'number') {
      return `<div class="group-label">${esc(cat.label)}</div>
        <div class="stack">${cat.options.map((o) => `<label class="muted">${esc(o.label)}
          <input type="number" step="0.01" id="num-${o.code}" value="${values[o.code] ?? ''}"
            onchange="logNumber('${day}','${o.code}',this.value)"></label>`).join('')}</div>`;
    }
    if (cat.kind === 'text') {
      const note = current.entries.find((e) => e.code === 'note');
      return `<div class="group-label">${esc(cat.label)}</div>
        <textarea rows="3" placeholder="Anything worth remembering"
          onchange="logNote('${day}',this.value)">${esc(note ? note.text : '')}</textarea>`;
    }
    return `<div class="group-label">${esc(cat.label)}</div>
      <div class="chipset">${cat.options.map((o) => `<button class="chip ${active.has(o.code) ? 'on' : ''}"
        onclick="toggleLog('${day}','${o.code}',this)">${esc(o.label)}</button>`).join('')}</div>`;
  }).join('');

  openSheet(`<h2>Log ${fmtDay(day)}</h2>
    <p class="muted">${State.catalog.total_trackable} things you can track. Consistency beats completeness.</p>
    ${groups}
    <button class="btn primary" style="width:100%;margin-top:16px" onclick="finishLog()">Done</button>`);
}

async function toggleLog(day, code, el) {
  const on = el.classList.contains('on');
  await api('/api/log', { method: on ? 'DELETE' : 'POST', body: { date: day, code } });
  el.classList.toggle('on');
  if (!on && el.parentElement.dataset.single === '1') {
    [...el.parentElement.children].forEach((c) => { if (c !== el) c.classList.remove('on'); });
  }
}
async function logNumber(day, code, value) {
  if (value === '') return api('/api/log', { method: 'DELETE', body: { date: day, code } });
  return api('/api/log', { method: 'POST', body: { date: day, code, value: Number(value) } });
}
async function logNote(day, text) {
  return api('/api/log', { method: 'POST', body: { date: day, code: 'note', text } });
}
async function finishLog() { closeSheet(); toast('Saved'); await renderToday(); await renderCalendar(); }

/* ── calendar ─────────────────────────────────────────────────── */

async function renderCalendar() {
  const base = State.calMonth || new Date();
  State.calMonth = new Date(base.getFullYear(), base.getMonth(), 1);
  const first = State.calMonth;
  const daysInMonth = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate();
  const lead = (first.getDay() + 6) % 7; // Monday-first

  $('#cal-title').textContent = first.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
  const data = await api(`/api/calendar?start=${iso(first)}&days=${daysInMonth}`);
  const today = iso(new Date());

  let html = '<div class="cell blank"></div>'.repeat(lead);
  for (let d = 1; d <= daysInMonth; d++) {
    const key = iso(new Date(first.getFullYear(), first.getMonth(), d));
    const m = data.days[key] || {};
    const cls = ['cell',
      m.logged_period ? 'period' : '', m.predicted_period ? 'predicted' : '',
      m.fertile ? 'fertile' : '', m.ovulation ? 'ovulation' : '',
      key === today ? 'today' : ''].filter(Boolean).join(' ');
    html += `<button class="${cls}" onclick="openDay('${key}')">${d}</button>`;
  }
  $('#cal-grid').innerHTML = html;
  $('#cal-detail').innerHTML = `<span class="kicker">this month</span>
    <p>Tap any day to log it or mark a period start.</p>`;
}

async function openDay(key) {
  const log = await api(`/api/log/${key}`);
  const items = log.entries.length
    ? log.entries.map((e) => `<span class="pill">${esc(e.label)}${e.value !== null ? ': ' + e.value : ''}</span>`).join(' ')
    : '<span class="muted">Nothing logged.</span>';
  $('#cal-detail').innerHTML = `<span class="kicker">${fmtDay(key)}</span>
    <p style="margin:8px 0">${items}</p>
    <div class="row-actions">
      <button class="btn small" onclick="openLogSheet('${key}')">Log symptoms</button>
      <button class="btn small" onclick="markPeriodStart('${key}')">Period started</button>
    </div>`;
}

async function markPeriodStart(key) {
  await api('/api/periods', { method: 'POST', body: { start_date: key } });
  toast('Period start logged'); await renderCalendar(); await renderToday();
}

/* ── routing ──────────────────────────────────────────────────── */

const RENDERERS = {
  today: renderToday,
  calendar: renderCalendar,
  insights: () => renderInsights(),
  chat: () => renderChat(),
  profile: () => renderProfile(),
};

async function go(view) {
  State.view = view;
  $$('.view').forEach((v) => v.classList.toggle('hidden', v.id !== `view-${view}`));
  $$('.tab').forEach((t) => t.classList.toggle('active', t.dataset.view === view));
  window.scrollTo(0, 0);
  try { await RENDERERS[view](); } catch (err) { toast(err.message); }
}

/* ── boot ─────────────────────────────────────────────────────── */

async function start() {
  let me;
  try { me = await api('/api/me'); } catch { return showGate('choose'); }
  State.user = me.user; State.billing = me.billing;
  $('#boot').classList.add('hidden');
  $('#gate').classList.add('hidden');

  if (!State.user.onboarded) {
    $('#app').classList.add('hidden');
    $('#onboarding').classList.remove('hidden');
    onbShow(0);
    return;
  }
  $('#onboarding').classList.add('hidden');
  $('#app').classList.remove('hidden');
  await go('today');
}

function wireShell() {
  $$('.tab').forEach((t) => t.addEventListener('click', () => go(t.dataset.view)));
  $('.sheet-backdrop').addEventListener('click', closeSheet);
  $('#btn-log-period').addEventListener('click', openPeriodSheet);
  $('#btn-log-today').addEventListener('click', () => openLogSheet());
  $('#cal-prev').addEventListener('click', () => {
    State.calMonth.setMonth(State.calMonth.getMonth() - 1); renderCalendar();
  });
  $('#cal-next').addEventListener('click', () => {
    State.calMonth.setMonth(State.calMonth.getMonth() + 1); renderCalendar();
  });
  $$('#insights-tabs .seg').forEach((b) => b.addEventListener('click', () => {
    $$('#insights-tabs .seg').forEach((x) => x.classList.remove('active'));
    b.classList.add('active'); renderInsights(b.dataset.seg);
  }));
  $$('#chat-tabs .seg').forEach((b) => b.addEventListener('click', () => {
    $$('#chat-tabs .seg').forEach((x) => x.classList.remove('active'));
    b.classList.add('active'); renderChat(b.dataset.seg);
  }));
}

window.addEventListener('DOMContentLoaded', () => {
  wireGate(); wireOnboarding(); wireShell(); start();
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
});
