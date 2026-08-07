/* cycliq — Chat tab (Secret Chats + Health Assistant), Profile, Partner, modes. */

let chatSeg = 'secret';

async function renderChat(seg) {
  chatSeg = seg || chatSeg;
  $$('#chat-tabs .seg').forEach((b) => b.classList.toggle('active', b.dataset.seg === chatSeg));
  const host = $('#chat-body');
  host.innerHTML = '<div class="card"><p>Loading…</p></div>';
  host.innerHTML = chatSeg === 'secret' ? await renderSecret() : await renderAssistant();
  if (chatSeg === 'assistant') {
    const input = $('#assistant-input');
    if (input) input.addEventListener('keydown', (e) => { if (e.key === 'Enter') sendAssistant(); });
  }
}

/* ── Secret Chats ─────────────────────────────────────────────── */

async function renderSecret() {
  const [topics, posts] = await Promise.all([
    api('/api/community/topics'),
    api('/api/community/posts?limit=30'),
  ]);
  return `<div class="card">
      <span class="kicker">anonymous</span>
      <p>You post as <strong>${esc(State.user.handle)}</strong>. That name is generated and is not
      linked to your email anywhere in the interface. Contact details are stripped automatically.</p>
    </div>
    <button class="btn primary" style="width:100%;margin:12px 0" onclick="openNewPost()">Start a conversation</button>
    <div class="group-label">Topics</div>
    <div class="list">${topics.topics.map((t) => `
      <button class="row" onclick="openTopic('${t.slug}')">
        <span><strong>${esc(t.label)}</strong><small>${esc(t.blurb)}</small></span>
        <span class="pill">${t.posts}</span></button>`).join('')}</div>
    <div class="group-label">Latest</div>
    <div class="list">${posts.posts.length
      ? posts.posts.map(postRow).join('')
      : '<p class="muted">Nothing here yet. Be the first.</p>'}</div>`;
}

const postRow = (p) => `<button class="row" onclick="openPost(${p.id})">
  <span><strong>${esc(p.handle)}</strong><small>${esc(p.body.slice(0, 110))}${p.body.length > 110 ? '…' : ''}</small></span>
  <span class="pill">${p.replies} ↩ ${p.hearts} ♥</span></button>`;

async function openTopic(slug) {
  const data = await api(`/api/community/posts?topic=${slug}&limit=50`);
  openSheet(`<h2>${esc(slug)}</h2>
    <button class="btn primary" style="width:100%;margin:10px 0" onclick="openNewPost('${slug}')">Post here</button>
    <div class="list">${data.posts.length ? data.posts.map(postRow).join('') : '<p class="muted">No posts yet.</p>'}</div>
    <button class="btn ghost" style="width:100%;margin-top:12px" onclick="closeSheet()">Close</button>`);
}

async function openNewPost(topic) {
  const topics = await api('/api/community/topics');
  openSheet(`<h2>New post</h2>
    <select id="post-topic" style="margin-top:10px">
      ${topics.topics.map((t) => `<option value="${t.slug}" ${t.slug === topic ? 'selected' : ''}>${esc(t.label)}</option>`).join('')}
    </select>
    <textarea id="post-body" rows="6" placeholder="What's on your mind?" style="margin-top:10px"></textarea>
    <button class="btn primary" style="width:100%;margin-top:10px" onclick="submitPost()">Post anonymously</button>
    <p class="fine" style="margin-top:10px">Emails, phone numbers and messaging handles are removed automatically.</p>`);
}

async function submitPost() {
  const topic = $('#post-topic').value;
  const body = $('#post-body').value.trim();
  if (!body) return toast('Write something first');
  await api('/api/community/posts', { method: 'POST', body: { topic, body } });
  closeSheet(); toast('Posted'); renderChat('secret');
}

async function openPost(id) {
  const data = await api(`/api/community/posts/${id}`);
  const p = data.post;
  openSheet(`<h2>${esc(p.handle)}</h2>
    <p class="muted">${esc(p.topic)}</p>
    <p style="margin:12px 0;white-space:pre-wrap">${esc(p.body)}</p>
    <div class="row-actions">
      <button class="btn small" onclick="react('post',${p.id})">♥ ${p.hearts}</button>
      <button class="btn small" onclick="reportItem('post',${p.id})">Report</button>
      ${p.mine ? `<button class="btn small" onclick="deletePost(${p.id})">Delete</button>` : ''}
    </div>
    <div class="group-label">${data.replies.length} replies</div>
    <div class="list">${data.replies.map((r) => `<div class="row">
      <span><strong>${esc(r.handle)}</strong><small style="white-space:pre-wrap">${esc(r.body)}</small></span>
      <button class="btn small" onclick="react('reply',${r.id})">♥ ${r.hearts}</button></div>`).join('')}</div>
    <textarea id="reply-body" rows="3" placeholder="Reply" style="margin-top:12px"></textarea>
    <button class="btn primary" style="width:100%;margin-top:8px" onclick="submitReply(${p.id})">Reply</button>
    <button class="btn ghost" style="width:100%;margin-top:8px" onclick="closeSheet()">Close</button>`);
}

async function submitReply(postId) {
  const body = $('#reply-body').value.trim();
  if (!body) return toast('Write something first');
  await api(`/api/community/posts/${postId}/replies`, { method: 'POST', body: { body } });
  toast('Replied'); openPost(postId);
}

async function react(kind, id) {
  await api('/api/community/react', { method: 'POST', body: { target_kind: kind, target_id: id } });
  if (kind === 'post') openPost(id); else toast('Thanks');
}

async function reportItem(kind, id) {
  await api('/api/community/report', { method: 'POST', body: { target_kind: kind, target_id: id } });
  closeSheet(); toast('Reported for review');
}

async function deletePost(id) {
  await api(`/api/community/posts/${id}`, { method: 'DELETE' });
  closeSheet(); toast('Deleted'); renderChat('secret');
}

/* ── Health Assistant ─────────────────────────────────────────── */

async function renderAssistant() {
  const preview = `<h3>Health Assistant</h3><p>Ask anything about your cycle, symptoms or the guidance —
    answers are grounded in the app's own library.</p>`;
  return await guarded('/api/assistant/history', (data) => `
    <div class="card"><span class="kicker">how this works</span>
      <p>Answers run on a local model when one is available, so your data does not leave the machine.
      Only aggregates — cycle day, phase, cycle length — are ever sent anywhere.</p></div>
    <div class="bubbles" id="assistant-log" style="margin-top:14px">
      ${data.messages.length
        ? data.messages.map((m) => `<div class="bubble ${m.role === 'user' ? 'me' : 'bot'}">${esc(m.body)}</div>`).join('')
        : `<div class="bubble bot">Ask me about your cycle, a symptom, contraception, fertility or pregnancy.
           ${esc(data.disclaimer)}</div>`}
    </div>
    <div class="composer">
      <input id="assistant-input" placeholder="Ask a question">
      <button class="btn primary" onclick="sendAssistant()">Send</button>
    </div>
    <button class="btn ghost small" onclick="clearAssistant()">Clear history</button>`, preview);
}

async function sendAssistant() {
  const input = $('#assistant-input');
  const message = input.value.trim();
  if (!message) return;
  input.value = '';
  const log = $('#assistant-log');
  log.insertAdjacentHTML('beforeend', `<div class="bubble me">${esc(message)}</div>`);
  log.insertAdjacentHTML('beforeend', '<div class="bubble bot" id="thinking">…</div>');
  try {
    const out = await api('/api/assistant/chat', { method: 'POST', body: { message } });
    const sources = out.sources.length
      ? `\n\nSources: ${out.sources.map((s) => s.title).join(', ')}` : '';
    $('#thinking').outerHTML = `<div class="bubble bot">${esc(out.reply + sources)}</div>`;
  } catch (err) {
    $('#thinking').outerHTML = `<div class="bubble bot">${esc(err.message)}</div>`;
    if (err.status === 402) showPaywall(err.detail);
  }
}

async function clearAssistant() {
  await api('/api/assistant/history', { method: 'DELETE' });
  renderChat('assistant');
}

/* ── Today-screen mode panels ─────────────────────────────────── */

async function renderPregnancyPanel() {
  const p = await api('/api/pregnancy/status');
  if (!p.active) {
    $('#mode-panel').innerHTML = `<div class="card"><h3>Pregnancy mode</h3>
      <p>Set a due date or your last period date to switch the Today screen to weeks.</p>
      <button class="btn small primary" style="margin-top:10px" onclick="openPregnancyStart()">Set it up</button></div>`;
    return;
  }
  const detail = p.premium
    ? `<p><strong>About the size of a ${esc(p.size || '—')}.</strong> ${esc(p.development || '')}</p>
       ${p.movement_guidance ? `<p class="fine" style="margin-top:10px">${esc(p.movement_guidance)}</p>` : ''}
       ${p.labour_guidance ? `<p class="fine" style="margin-top:8px">${esc(p.labour_guidance)}</p>` : ''}
       <div class="row-actions" style="margin-top:12px">
         <button class="btn small" onclick="openKicks()">Kick counter</button>
         <button class="btn small" onclick="openContractions()">Contraction timer</button>
       </div>`
    : lockedCard({ feature: 'Detailed pregnancy tracking' },
      '<p>Week-by-week development, the kick counter and the contraction timer.</p>');

  $('#mode-panel').innerHTML = `<div class="card">
    <span class="kicker">week ${p.week} · trimester ${p.trimester}</span>
    <h3>${p.days_to_due} days to your due date</h3>
    <p class="muted">Due ${fmtDay(p.due_date)} — a midpoint, not a deadline. About 4% arrive on it.</p>
    ${detail}</div>`;
}

function openPregnancyStart() {
  openSheet(`<h2>Pregnancy mode</h2>
    <div class="stack" style="margin-top:12px">
      <label class="muted">First day of your last period<input type="date" id="preg-lmp"></label>
      <p class="fine">Or set a due date directly if a scan gave you one.</p>
      <label class="muted">Due date<input type="date" id="preg-due"></label>
      <button class="btn primary" onclick="startPregnancy()">Start</button>
      <button class="btn ghost" onclick="closeSheet()">Cancel</button>
    </div>`);
}

async function startPregnancy() {
  const lmp = $('#preg-lmp').value || null;
  const due = $('#preg-due').value || null;
  if (!lmp && !due) return toast('Enter one of the two dates');
  await api('/api/pregnancy/start', { method: 'POST', body: { lmp_date: lmp, due_date: due } });
  State.user.mode = 'pregnancy';
  closeSheet(); toast('Pregnancy mode on'); renderToday();
}

async function openKicks() {
  const out = await api('/api/pregnancy/kicks', { method: 'POST', body: {} });
  window._kicks = out.session_id;
  openSheet(`<h2>Kick counter</h2>
    <p class="fine">${esc(out.guidance)}</p>
    <div style="text-align:center;margin:24px 0">
      <div style="font-size:56px;font-weight:700;color:var(--plum)" id="kick-count">${out.kicks}</div>
      <p class="muted">movements this session</p>
    </div>
    <button class="btn primary" style="width:100%" onclick="addKick()">Count a movement</button>
    <button class="btn ghost" style="width:100%;margin-top:8px" onclick="endKicks()">End session</button>`);
}

async function addKick() {
  const out = await api('/api/pregnancy/kicks', { method: 'POST', body: { session_id: window._kicks } });
  $('#kick-count').textContent = out.kicks;
}

async function endKicks() {
  await api(`/api/pregnancy/kicks/${window._kicks}/end`, { method: 'POST' });
  closeSheet(); toast('Session saved');
}

async function openContractions() {
  const data = await api('/api/pregnancy/contractions');
  const rows = data.contractions.map((c) => `<tr><td>${new Date(c.started_at).toLocaleTimeString()}</td>
    <td>${Math.round(c.duration_s)}s</td></tr>`).join('');
  openSheet(`<h2>Contraction timer</h2>
    <p class="fine">${esc(data.guidance)}</p>
    <div style="text-align:center;margin:20px 0">
      <button class="btn primary" id="ctx-btn" style="width:100%" onclick="toggleContraction()">Start contraction</button>
    </div>
    <p class="muted">Average length ${data.average_duration_s ?? '—'}s · average gap
      ${data.average_gap_s ? Math.round(data.average_gap_s / 60) + ' min' : '—'}</p>
    <table class="mini" style="margin-top:12px"><tr><th>Started</th><th>Length</th></tr>${rows}</table>
    <button class="btn ghost" style="width:100%;margin-top:12px" onclick="closeSheet()">Close</button>`);
}

async function toggleContraction() {
  const btn = $('#ctx-btn');
  if (!window._ctxStart) {
    window._ctxStart = new Date();
    btn.textContent = 'Stop contraction';
    return;
  }
  const started = window._ctxStart;
  window._ctxStart = null;
  await api('/api/pregnancy/contractions', {
    method: 'POST',
    body: { started_at: started.toISOString(), duration_s: (Date.now() - started.getTime()) / 1000 },
  });
  openContractions();
}

async function renderTtcPanel() {
  const w = await api('/api/ttc/window');
  if (!w.ready) { $('#mode-panel').innerHTML = ''; return; }
  const bars = w.days.map((d) => `<div style="display:flex;align-items:center;gap:8px;margin:4px 0">
    <span style="width:120px;font-size:12px;color:var(--muted)">${esc(d.label)}</span>
    <span class="bar" style="flex:1"><i style="width:${Math.round(d.probability * 300)}%"></i></span>
    <span style="font-size:12px;width:34px;text-align:right">${Math.round(d.probability * 100)}%</span>
  </div>`).join('');
  $('#mode-panel').innerHTML = `<div class="card">
    <span class="kicker">${w.in_window ? 'fertile window is open' : 'fertile window'}</span>
    <h3>${fmtDay(w.fertile_start)} – ${fmtDay(w.fertile_end)}</h3>
    <p class="muted">Ovulation estimated ${fmtDay(w.ovulation)} (${fmtDay(w.ovulation_low)}–${fmtDay(w.ovulation_high)}),
      confidence ${esc(w.confidence)}.</p>
    <div style="margin-top:12px">${bars}</div>
    <p class="fine" style="margin-top:10px">${esc(w.note)}</p>
    <button class="btn small" style="margin-top:10px" onclick="openTtcChart()">Fertility chart</button>
  </div>`;
}

async function openTtcChart() {
  const c = await api('/api/ttc/chart');
  const temps = c.days.filter((d) => d.bbt !== null);
  const rows = c.days.map((d) => `<tr><td>${d.cycle_day}</td><td>${d.bbt ?? '—'}</td>
    <td>${d.mucus ? d.mucus.replace('dis_', '') : '—'}</td>
    <td>${d.lh === 'ovulation_test_pos' ? 'LH +' : d.lh ? 'LH −' : '—'}</td></tr>`).join('');
  openSheet(`<h2>Fertility chart</h2>
    <p class="muted">${temps.length} temperature reading${temps.length === 1 ? '' : 's'} this cycle.
      ${c.luteal_measured ? `Ovulation observed ${fmtDay(c.observed_ovulation)}; your luteal phase measures ${c.luteal_len} days.`
        : `No confirmed ovulation yet this cycle — using a ${c.luteal_len}-day luteal phase.`}</p>
    <p class="fine" style="margin-top:8px">${esc(c.note)}</p>
    <table class="mini" style="margin-top:14px">
      <tr><th>Day</th><th>BBT</th><th>Mucus</th><th>Test</th></tr>${rows}</table>
    <button class="btn ghost" style="width:100%;margin-top:12px" onclick="closeSheet()">Close</button>`);
}

/* ── Profile ──────────────────────────────────────────────────── */

async function renderProfile() {
  const [me, links, rem] = await Promise.all([
    api('/api/me'), api('/api/partner/links'), api('/api/reminders'),
  ]);
  State.user = me.user; State.billing = me.billing;
  const b = me.billing;

  const partnerRows = links.owned.map((l) => `<div class="row">
      <span><strong>${l.status === 'pending' ? `Invite code ${esc(l.invite_code)}` : 'Partner connected'}</strong>
        <small>Sharing: ${l.effective_scopes.join(', ') || 'nothing yet'}</small></span>
      <button class="btn small" onclick="editScopes(${l.id})">Edit</button></div>`).join('')
    + links.following.map((l) => `<button class="row" onclick="openPartnerView(${l.id})">
        <span><strong>Following ${esc(l.owner_handle)}</strong><small>Tap to see what they share</small></span>
        <span class="pill">View</span></button>`).join('');

  return $('#profile-body').innerHTML = `
    <div class="card">
      <span class="kicker">${b.active ? b.tier : 'free'}</span>
      <h3>${esc(State.user.handle)}</h3>
      <p class="muted">${State.user.anonymous ? 'Anonymous Mode — no email on this account.' : esc(State.user.email)}</p>
      ${b.active
        ? `<p class="muted" style="margin-top:8px">Premium active, ${b.days_left} days left.</p>`
        : `<button class="btn primary small" style="margin-top:10px" onclick="showPaywall()">See Premium</button>`}
    </div>

    <div class="group-label">Mode</div>
    <div class="list">
      ${['cycle', 'ttc', 'pregnancy'].map((m) => `<button class="row" onclick="setMode('${m}')">
        <span><strong>${{ cycle: 'Cycle tracking', ttc: 'Trying to conceive', pregnancy: 'Pregnancy' }[m]}</strong></span>
        <span class="pill">${State.user.mode === m ? 'On' : 'Switch'}</span></button>`).join('')}
    </div>

    <div class="group-label">Six-month report</div>
    <div class="list">
      <button class="row" onclick="openReport()">
        <span><strong>Report for a clinician</strong><small>Cycle lengths, symptoms by phase, screener results</small></span>
        <span class="pill">${b.active ? 'PDF' : 'Premium'}</span></button>
    </div>

    <div class="group-label">Partner Mode</div>
    <div class="list">${partnerRows || '<p class="muted">No partner connected.</p>'}
      <button class="row" onclick="openInvite()"><span><strong>Invite a partner</strong>
        <small>You choose exactly what is shared</small></span><span class="pill">New</span></button>
      <button class="row" onclick="openJoin()"><span><strong>Join with a code</strong></span><span class="pill">Join</span></button>
    </div>

    <div class="group-label">Reminders</div>
    <div class="list">${rem.reminders.map((r) => `<div class="row">
        <span><strong>${esc(r.label)}</strong><small>${r.anchor === 'daily' ? 'every day' : `${r.offset_days >= 0 ? '+' : ''}${r.offset_days} days from ${r.anchor.replace('_', ' ')}`} at ${esc(r.time_of_day)}</small></span>
        <button class="btn small" onclick="deleteReminder(${r.id})">Remove</button></div>`).join('')}
      <button class="row" onclick="openReminder()"><span><strong>Add a reminder</strong></span><span class="pill">New</span></button>
    </div>

    <div class="group-label">Your data</div>
    <div class="list">
      <button class="row" onclick="openImport()"><span><strong>Import from another app</strong>
        <small>Apple Health, a Flo export, or CSV</small></span><span class="pill">Import</span></button>
      <button class="row" onclick="exportData()"><span><strong>Export everything</strong>
        <small>Full JSON, nothing withheld</small></span><span class="pill">JSON</span></button>
      <button class="row" onclick="deleteAccount()"><span><strong>Delete my account</strong>
        <small>Every row removed by cascade, not a flag</small></span><span class="pill">Delete</span></button>
      <button class="row" onclick="logout()"><span><strong>Log out</strong></span><span class="pill">Out</span></button>
    </div>
    <p class="fine" style="margin-top:16px">Data lives in a local SQLite file on this machine. No analytics,
    no third-party calls, no cloud sync.</p>`;
}

async function setMode(mode) {
  await api('/api/me', { method: 'PATCH', body: { mode } });
  State.user.mode = mode; toast(`Mode: ${mode}`); renderProfile();
}

async function openReport() {
  try {
    await api('/api/report/preview');
    window.open('/api/report.pdf', '_blank');
  } catch (err) {
    if (err.status === 402) return showPaywall(err.detail);
    toast(err.message);
  }
}

async function openInvite() {
  const cat = await api('/api/partner/scopes');
  openSheet(`<h2>Invite a partner</h2>
    <p class="muted">Pick exactly what they can see. You can change or revoke it any time.</p>
    <div class="chipset" id="scope-picker">${cat.scopes.map((s) => `
      <button class="chip ${s.basic ? 'on' : ''}" data-scope="${s.key}" onclick="this.classList.toggle('on')">
        ${esc(s.label)}${s.basic ? '' : ' ✦'}</button>`).join('')}</div>
    <p class="fine">✦ needs Premium on your account — a free account shares the basics only.</p>
    <button class="btn primary" style="width:100%;margin-top:12px" onclick="createInvite()">Create invite code</button>`);
}

async function createInvite() {
  const scopes = $$('#scope-picker .chip.on').map((c) => c.dataset.scope);
  const out = await api('/api/partner/invite', { method: 'POST', body: { scopes } });
  openSheet(`<h2>Invite code</h2>
    <p class="muted">Share this with your partner. They enter it under “Join with a code”.</p>
    <div style="text-align:center;font-size:30px;font-weight:700;color:var(--plum);margin:22px 0">
      ${esc(out.invite_code)}</div>
    <button class="btn primary" style="width:100%" onclick="closeSheet();renderProfile()">Done</button>`);
}

function openJoin() {
  openSheet(`<h2>Join with a code</h2>
    <input id="join-code" placeholder="Invite code" style="margin-top:12px">
    <button class="btn primary" style="width:100%;margin-top:10px" onclick="submitJoin()">Join</button>`);
}

async function submitJoin() {
  try {
    await api('/api/partner/join', { method: 'POST', body: { code: $('#join-code').value.trim() } });
    closeSheet(); toast('Connected'); renderProfile();
  } catch (err) { toast(err.message); }
}

async function editScopes(linkId) {
  const [cat, links] = await Promise.all([api('/api/partner/scopes'), api('/api/partner/links')]);
  const link = links.owned.find((l) => l.id === linkId);
  openSheet(`<h2>What your partner sees</h2>
    <div class="chipset" id="scope-picker">${cat.scopes.map((s) => `
      <button class="chip ${link.scopes.includes(s.key) ? 'on' : ''}" data-scope="${s.key}"
        onclick="this.classList.toggle('on')">${esc(s.label)}${s.basic ? '' : ' ✦'}</button>`).join('')}</div>
    <button class="btn primary" style="width:100%;margin-top:12px" onclick="saveScopes(${linkId})">Save</button>
    <button class="btn ghost" style="width:100%;margin-top:8px" onclick="revokeLink(${linkId})">Revoke access</button>`);
}

async function saveScopes(linkId) {
  const scopes = $$('#scope-picker .chip.on').map((c) => c.dataset.scope);
  await api(`/api/partner/links/${linkId}/scopes`, { method: 'POST', body: { scopes } });
  closeSheet(); toast('Sharing updated'); renderProfile();
}

async function revokeLink(linkId) {
  await api(`/api/partner/links/${linkId}`, { method: 'DELETE' });
  closeSheet(); toast('Revoked'); renderProfile();
}

async function openPartnerView(linkId) {
  const v = await api(`/api/partner/view/${linkId}`);
  const bits = [];
  if (v.phase) bits.push(`<h3>Day ${v.cycle_day} · ${esc(v.phase)} phase</h3>`);
  if (v.next_period) bits.push(`<p class="muted">Period expected around ${fmtDay(v.next_period)}
    (${fmtDay(v.next_period_low)}–${fmtDay(v.next_period_high)}).</p>`);
  if (v.fertile_start) bits.push(`<p class="muted">Fertile window ${fmtDay(v.fertile_start)}–${fmtDay(v.fertile_end)}.</p>`);
  if (v.today_logged) bits.push(`<p class="muted">Logged today: ${v.today_logged.map((e) => esc(e.label)).join(', ') || 'nothing'}.</p>`);
  if (v.pregnancy) bits.push(`<p class="muted">Week ${v.pregnancy.week}, ${v.pregnancy.days_to_due} days to the due date.</p>`);
  openSheet(`<h2>${esc(v.owner_handle)}</h2>
    ${bits.join('')}
    ${(v.tips || []).map((t) => `<div class="card" style="margin-top:10px"><p>${esc(t)}</p></div>`).join('')}
    <p class="fine" style="margin-top:12px">You see only what they chose to share: ${v.scopes.join(', ')}.</p>
    <button class="btn ghost" style="width:100%;margin-top:12px" onclick="closeSheet()">Close</button>`);
}

async function openReminder() {
  const kinds = await api('/api/reminders/kinds');
  openSheet(`<h2>New reminder</h2>
    <select id="rem-kind" style="margin-top:12px">
      ${kinds.kinds.map((k) => `<option value="${k.key}">${esc(k.label)}</option>`).join('')}</select>
    <label class="muted" style="display:block;margin-top:10px">Time<input type="time" id="rem-time" value="09:00"></label>
    <label class="muted" style="display:block;margin-top:10px">Days offset from the event (negative = before)
      <input type="number" id="rem-offset" value="-2"></label>
    <button class="btn primary" style="width:100%;margin-top:12px" onclick="createReminder()">Add</button>`);
}

async function createReminder() {
  await api('/api/reminders', {
    method: 'POST',
    body: { kind: $('#rem-kind').value, time_of_day: $('#rem-time').value, offset_days: Number($('#rem-offset').value) },
  });
  closeSheet(); toast('Reminder added'); renderProfile();
}

async function deleteReminder(id) {
  await api(`/api/reminders/${id}`, { method: 'DELETE' });
  toast('Removed'); renderProfile();
}

async function exportData() {
  const data = await api('/api/me/export');
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = 'cycliq-export.json'; a.click();
  URL.revokeObjectURL(url);
  toast('Exported');
}

async function deleteAccount() {
  if (!confirm('Delete this account and every row of data in it? This cannot be undone.')) return;
  await api('/api/me', { method: 'DELETE' });
  location.reload();
}

async function logout() {
  await api('/api/auth/logout', { method: 'POST' });
  location.reload();
}
