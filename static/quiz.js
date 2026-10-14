/* cycliq — quizzes: the free daily question on Today, and Premium lesson quizzes.
   Answers are checked on the server; the page never has them until a question is answered. */

/* ── daily question ───────────────────────────────────────────── */

async function renderDailyQuiz() {
  const host = $('#daily-quiz');
  if (!host) return;
  let q;
  try { q = await api('/api/quiz/daily'); } catch { host.innerHTML = ''; return; }

  const streak = q.streak > 0
    ? `<span class="pill">${q.streak}-day streak</span>` : '';
  const options = q.options.map((label, i) => {
    let cls = 'quiz-opt';
    if (q.answered) cls += i === q.correct_index ? ' correct' : '';
    return `<button class="${cls}" ${q.answered ? 'disabled' : `onclick="answerDaily(${i})"`}>${esc(label)}</button>`;
  }).join('');

  const result = q.answered ? `<p class="quiz-result ${q.correct ? 'ok' : 'no'}" role="status">
      <strong>${q.correct ? 'Correct.' : 'Not quite.'}</strong> ${esc(q.explanation)}</p>` : '';

  host.innerHTML = `<div class="card" style="margin-top:14px">
    <div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
      <span class="kicker" style="margin:0">Question of the day</span>${streak}
    </div>
    <h3 style="margin:8px 0 12px">${esc(q.question)}</h3>
    <div class="quiz-opts">${options}</div>${result}
  </div>`;
}

async function answerDaily(choice) {
  try {
    const out = await api('/api/quiz/daily/answer', { method: 'POST', body: { choice } });
    toast(out.correct ? 'Correct' : 'Not quite');
  } catch (err) { toast(err.message); }
  await renderDailyQuiz();
}

/* ── lesson quizzes (Premium) ─────────────────────────────────── */

const LessonQuiz = { course: null, slug: null, questions: [], picks: [] };

async function openLessonQuiz(courseId, slug) {
  try {
    const data = await api(`/api/quiz/lessons/${courseId}/${slug}`);
    Object.assign(LessonQuiz, { course: courseId, slug, questions: data.questions, picks: data.questions.map(() => null) });
    renderLessonQuiz(data.best);
  } catch (err) {
    if (err.status === 402) return showPaywall(err.detail);
    toast(err.message);
  }
}

function renderLessonQuiz(best) {
  const body = LessonQuiz.questions.map((q, qi) => `
    <h3 style="margin:20px 0 0;font-size:17px">${qi + 1}. ${esc(q.question)}</h3>
    <div class="quiz-opts" style="margin-top:10px">${q.options.map((label, oi) => `
      <button class="quiz-opt ${LessonQuiz.picks[qi] === oi ? 'picked' : ''}" aria-pressed="${LessonQuiz.picks[qi] === oi}"
        onclick="pickLessonAnswer(${qi},${oi})">${esc(label)}</button>`).join('')}
    </div>`).join('');
  const ready = LessonQuiz.picks.every((p) => p !== null);
  openSheet(`<h2>Check your understanding</h2>
    <p class="muted">${LessonQuiz.questions.length} questions${best ? ` · your best: ${best.score} of ${best.total}` : ''}</p>
    ${body}
    <button class="btn primary" style="width:100%;margin-top:18px" ${ready ? '' : 'disabled'} onclick="submitLessonQuiz()">Check answers</button>
    <button class="btn ghost" style="width:100%;margin-top:8px" onclick="openCourse('${LessonQuiz.course}')">Back to course</button>`);
}

function pickLessonAnswer(qi, oi) {
  LessonQuiz.picks[qi] = oi;
  const sheet = $('.sheet-panel');
  const top = sheet ? sheet.scrollTop : 0;
  renderLessonQuiz(null);
  const again = $('.sheet-panel');
  if (again) again.scrollTop = top;
}

async function submitLessonQuiz() {
  try {
    const out = await api(`/api/quiz/lessons/${LessonQuiz.course}/${LessonQuiz.slug}`, { method: 'POST', body: { answers: LessonQuiz.picks } });
    const rows = out.results.map((r, i) => `
      <div class="card" style="margin-top:10px">
        <span class="kicker" style="color:${r.correct ? 'var(--fertile-ink)' : 'var(--danger)'}">${r.correct ? 'Correct' : 'Not quite'}</span>
        <h3 style="margin:4px 0">${esc(LessonQuiz.questions[i].question)}</h3>
        <p>${r.correct ? '' : `Answer: ${esc(LessonQuiz.questions[i].options[r.correct_index])}. `}${esc(r.explanation)}</p>
      </div>`).join('');
    openSheet(`<h2>${out.score} of ${out.total} correct</h2>
      <p class="muted">${out.passed ? 'Passed. This lesson is marked complete.' : 'Not passed yet. Read the lesson again and retry any time.'}</p>
      ${rows}
      <button class="btn primary" style="width:100%;margin-top:16px" onclick="openCourse('${LessonQuiz.course}')">Back to course</button>
      ${out.passed ? '' : `<button class="btn" style="width:100%;margin-top:8px" onclick="openLessonQuiz('${LessonQuiz.course}','${LessonQuiz.slug}')">Try again</button>`}`);
  } catch (err) { toast(err.message); }
}
