/* cycliq — Insights tab: library, courses, patterns, symptom checker, paywall. */

let insightsSeg = 'library';

async function renderInsights(seg) {
  insightsSeg = seg || insightsSeg;
  $$('#insights-tabs .seg').forEach((b) => b.classList.toggle('active', b.dataset.seg === insightsSeg));
  const host = $('#insights-body');
  host.innerHTML = '<div class="card"><p>Loading…</p></div>';
  const renderers = {
    library: renderLibrary,
    courses: renderCourses,
    patterns: renderPatterns,
    checker: renderChecker,
  };
  host.innerHTML = await renderers[insightsSeg]();
}

/* ── library ──────────────────────────────────────────────────── */

async function renderLibrary() {
  const data = await api('/api/content/library');
  const byCat = {};
  data.articles.forEach((a) => { (byCat[a.category] ||= []).push(a); });

  const banner = data.premium ? '' : `<div class="card">
    <span class="badge">Premium</span>
    <h3 style="margin-top:8px">${data.free_count} of ${data.total} articles are free</h3>
    <p>Premium opens the whole library plus every course.</p>
    <p style="margin-top:10px"><button class="btn primary small" onclick="showPaywall()">See Premium</button></p>
  </div>`;

  const sections = Object.entries(byCat).map(([cat, items]) => `
    <div class="group-label">${esc(cat)}</div>
    <div class="list">${items.map((a) => `
      <button class="row" onclick="openArticle('${a.id}')">
        <span><strong>${esc(a.title)}</strong><small>${esc(a.blurb)}</small></span>
        <span class="pill">${a.locked ? 'Premium' : a.minutes + ' min'}</span>
      </button>`).join('')}</div>`).join('');

  return `<input placeholder="Search the library" oninput="searchLibrary(this.value)" style="margin-bottom:14px">
    <div id="search-results"></div>${banner}${sections}
    <p class="fine" style="margin-top:16px">${esc(data.disclaimer)}</p>`;
}

async function searchLibrary(q) {
  const host = $('#search-results');
  if (!host) return;
  if (!q || q.length < 2) { host.innerHTML = ''; return; }
  const data = await api(`/api/content/search?q=${encodeURIComponent(q)}`);
  host.innerHTML = data.results.length
    ? `<div class="list" style="margin-bottom:16px">${data.results.map((a) => `
        <button class="row" onclick="openArticle('${a.id}')">
          <span><strong>${esc(a.title)}</strong><small>${esc(a.blurb)}</small></span>
          <span class="pill">${a.locked ? 'Premium' : a.minutes + ' min'}</span></button>`).join('')}</div>`
    : '<p class="muted" style="margin-bottom:16px">No matches.</p>';
}

async function openArticle(id) {
  try {
    const data = await api(`/api/content/articles/${id}`);
    const a = data.article;
    openSheet(`<h2>${esc(a.title)}</h2>
      <p class="muted">${esc(a.category)} · ${a.minutes} min read</p>
      <div class="article-body" style="margin-top:16px">
        ${a.body.split('\n\n').map((p) => `<p>${esc(p)}</p>`).join('')}
      </div>
      <p class="source-note">${esc(a.source)}<br><br>${esc(data.disclaimer)}</p>
      <button class="btn" style="width:100%;margin-top:14px" onclick="closeSheet()">Close</button>`);
  } catch (err) {
    if (err.status === 402) return showPaywall(err.detail);
    toast(err.message);
  }
}

/* ── courses ──────────────────────────────────────────────────── */

async function renderCourses() {
  const data = await api('/api/content/courses');
  const cards = data.courses.map((c) => {
    const pct = c.lessons ? Math.round((c.completed / c.lessons) * 100) : 0;
    return `<button class="row" onclick="openCourse('${c.id}')">
      <span><strong>${esc(c.title)}</strong><small>${esc(c.blurb)}</small>
        <small>${c.lessons} lessons · ${c.minutes} min${c.locked ? '' : ` · ${pct}% done`}</small>
        ${c.locked ? '' : `<span class="bar" style="margin-top:6px"><i style="width:${pct}%"></i></span>`}
      </span>
      <span class="pill">${c.locked ? 'Premium' : 'Open'}</span></button>`;
  }).join('');
  return `<div class="list">${cards}</div>
    <p class="fine" style="margin-top:16px">${esc(data.disclaimer)}</p>`;
}

async function openCourse(id) {
  try {
    const data = await api(`/api/content/courses/${id}`);
    const c = data.course;
    openSheet(`<h2>${esc(c.title)}</h2>
      <p class="muted">${esc(c.expert || '')}</p>
      <div class="list" style="margin-top:14px">${c.lessons.map((l, i) => `
        <button class="row" onclick="openLesson('${c.id}',${i})">
          <span><strong>${i + 1}. ${esc(l.title)}</strong><small>${l.minutes} min</small></span>
          <span class="pill">${l.completed ? 'Done' : 'Start'}</span></button>`).join('')}</div>
      <button class="btn" style="width:100%;margin-top:14px" onclick="closeSheet()">Close</button>`);
    window._course = c;
  } catch (err) {
    if (err.status === 402) return showPaywall(err.detail);
    toast(err.message);
  }
}

async function openLesson(courseId, index) {
  const c = window._course;
  const l = c.lessons[index];
  openSheet(`<h2>${esc(l.title)}</h2>
    <p class="muted">${esc(c.title)} · lesson ${index + 1} of ${c.lessons.length}</p>
    <div class="article-body" style="margin-top:16px"><p>${esc(l.body)}</p></div>
    <button class="btn primary" style="width:100%" onclick="completeLesson('${courseId}','${l.slug}')">
      Mark complete</button>
    <button class="btn ghost" style="width:100%;margin-top:8px" onclick="openCourse('${courseId}')">Back to course</button>`);
}

async function completeLesson(courseId, slug) {
  await api('/api/content/progress', { method: 'POST', body: { item_id: courseId, lesson_slug: slug } });
  toast('Lesson complete');
  openCourse(courseId);
}

/* ── patterns ─────────────────────────────────────────────────── */

async function renderPatterns() {
  const preview = `<h3>Headaches cluster in your luteal phase</h3>
    <p>You log headaches 3.2× more often during your luteal phase than on an average logged day.</p>`;

  const patternsHtml = await guarded('/api/patterns', (data) => {
    if (!data.ready) return `<div class="card"><h3>Not enough data yet</h3><p>${esc(data.message)}</p></div>`;
    if (!data.patterns.length) {
      return `<div class="card"><h3>No strong patterns yet</h3>
        <p>Across ${data.logged_days} logged days nothing stands out above your own baseline.
        That is a real result, not a failure — keep logging and this will change.</p></div>`;
    }
    return data.patterns.map((p) => `<div class="card">
      <span class="kicker">${esc(p.phase_label)}</span>
      <h3>${esc(p.label)}</h3><p>${esc(p.sentence)}</p>
      <p class="fine" style="margin-top:8px">${p.rate_pct}% of those days vs ${p.baseline_pct}% overall</p>
    </div>`).join('') + `<p class="fine">${esc(data.message)}</p>`;
  }, preview);

  const trendsHtml = await guarded('/api/patterns/trends', (data) => {
    if (!data.ready) return '';
    const rows = data.cycles.map((c) => `<tr><td>${fmtDay(c.start)}</td><td>${c.length} days</td>
      <td>${c.typical ? 'typical' : 'outside your usual'}</td></tr>`).join('');
    return `<div class="card"><span class="kicker">trends</span>
      <h3>Median ${data.median_length} days, range ${data.shortest}–${data.longest}</h3>
      <p>${esc(data.message)}</p>
      <table class="mini" style="margin-top:12px">
        <tr><th>Cycle start</th><th>Length</th><th></th></tr>${rows}</table></div>`;
  }, `<h3>Median 29 days, range 26–33</h3><p>Your last 8 cycles are consistent.</p>`);

  return `<div class="cards">${trendsHtml}${patternsHtml}</div>`;
}

/* ── symptom checker ──────────────────────────────────────────── */

async function renderChecker() {
  const preview = `<h3>PCOS pattern check</h3><p>10 questions, answered partly from your own logged cycles.</p>`;
  return await guarded('/api/checker/tools', (data) => `
    <div class="list">${data.tools.map((t) => `
      <button class="row" onclick="openChecker('${t.key}')">
        <span><strong>${esc(t.title)}</strong><small>${esc(t.blurb)}</small></span>
        <span class="pill">${t.questions} questions</span></button>`).join('')}</div>
    <p class="fine" style="margin-top:16px">${esc(data.disclaimer)}</p>`, preview);
}

async function openChecker(tool) {
  const data = await api(`/api/checker/${tool}`);
  window._checker = { tool, questions: data.questions, answers: { ...data.prefill } };
  const questions = data.questions.map((q, i) => `
    <div class="group-label">${i + 1}. ${esc(q.text)}</div>
    <div class="chipset" data-q="${q.key}">
      ${q.options.map((o) => `<button class="chip ${data.prefill[q.key] === o ? 'on' : ''}"
        onclick="answerChecker('${q.key}',this)">${esc(o)}</button>`).join('')}
    </div>`).join('');
  openSheet(`<h2>${esc(data.title)}</h2>
    <p class="muted">${esc(data.blurb)}</p>
    ${Object.keys(data.prefill).length ? '<p class="fine">Some answers are pre-filled from your logged cycles — change any that are wrong.</p>' : ''}
    ${questions}
    <button class="btn primary" style="width:100%;margin-top:16px" onclick="submitChecker()">See result</button>
    <p class="fine" style="margin-top:12px">${esc(data.disclaimer)}</p>`);
}

function answerChecker(key, el) {
  window._checker.answers[key] = el.textContent;
  [...el.parentElement.children].forEach((c) => c.classList.toggle('on', c === el));
}

async function submitChecker() {
  const { tool, answers, questions } = window._checker;
  const missing = questions.filter((q) => !answers[q.key]);
  if (missing.length) return toast(`${missing.length} question(s) unanswered`);
  const result = await api(`/api/checker/${tool}`, { method: 'POST', body: { answers, save: false } });
  const bandLabel = { strong: 'Close match', moderate: 'Partial match', low: 'Not a close match' }[result.band];
  openSheet(`<h2>${esc(result.title)}</h2>
    <span class="badge">${esc(bandLabel)}</span>
    <p style="margin-top:12px">${esc(result.headline)}</p>
    <p class="muted" style="margin-top:10px">${esc(result.explanation)}</p>
    ${result.red_flags.length ? `<div class="card" style="margin-top:14px">
      <span class="kicker">worth a call</span>
      ${result.red_flags.map((f) => `<p>• ${esc(f)}</p>`).join('')}</div>` : ''}
    <div class="group-label">Next steps</div>
    ${result.next_steps.map((s) => `<p class="muted">• ${esc(s)}</p>`).join('')}
    <button class="btn primary" style="width:100%;margin-top:16px" onclick="saveChecker()">Save to my history</button>
    <button class="btn ghost" style="width:100%;margin-top:8px" onclick="closeSheet()">Close without saving</button>
    <p class="fine" style="margin-top:12px">${esc(result.disclaimer)}</p>`);
}

async function saveChecker() {
  const { tool, answers } = window._checker;
  await api(`/api/checker/${tool}`, { method: 'POST', body: { answers, save: true } });
  closeSheet(); toast('Saved to your history');
}

/* ── paywall ──────────────────────────────────────────────────── */

async function showPaywall(detail) {
  const status = await api('/api/billing/status');
  const plans = Object.entries(status.plans).map(([key, p]) => `
    <button class="row" onclick="subscribe('${key}')">
      <span><strong>${esc(p.label)}</strong><small>$${p.price_usd}${key === 'annual' ? ' per year' : ' per month'}</small></span>
      <span class="pill">${p.note ? esc(p.note) : 'Choose'}</span></button>`).join('');

  openSheet(`<h2>cycliq Premium</h2>
    ${detail && detail.feature ? `<p class="muted">${esc(detail.feature)} is part of Premium.</p>` : ''}
    <div class="group-label">What Premium adds</div>
    ${status.premium_features.map((f) => `<p class="muted">✦ ${esc(f)}</p>`).join('')}
    <div class="group-label">Always free</div>
    ${status.free_features.map((f) => `<p class="muted">• ${esc(f)}</p>`).join('')}
    ${status.active
      ? `<div class="card" style="margin-top:16px"><h3>Premium is active</h3>
          <p>${status.days_left} days left on the ${esc(status.plan)} plan.</p>
          <button class="btn small" style="margin-top:10px" onclick="cancelPlan()">Cancel</button></div>`
      : `${status.trial_used ? '' : `<button class="btn primary" style="width:100%;margin-top:16px"
            onclick="startTrial()">Start ${status.plans.annual ? 7 : 7}-day free trial</button>`}
         <div class="group-label">Plans</div><div class="list">${plans}</div>
         <p class="fine" style="margin-top:12px">No card is collected anywhere in this app — checkout is a
         local entitlement record.</p>`}
    <button class="btn ghost" style="width:100%;margin-top:12px" onclick="closeSheet()">Close</button>`);
}

async function startTrial() {
  try {
    State.billing = await api('/api/billing/trial', { method: 'POST' });
    closeSheet(); toast('Premium trial started'); await go(State.view);
  } catch (err) { toast(err.message); }
}

async function subscribe(plan) {
  State.billing = await api('/api/billing/subscribe', { method: 'POST', body: { plan } });
  closeSheet(); toast('Premium active'); await go(State.view);
}

async function cancelPlan() {
  State.billing = await api('/api/billing/cancel', { method: 'POST' });
  closeSheet(); toast('Premium cancelled'); await go(State.view);
}
