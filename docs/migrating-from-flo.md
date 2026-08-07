# Moving to cycliq from Flo

*A setup and migration guide.*

cycliq covers the same ground as Flo — cycle predictions, fertility tracking,
pregnancy, symptom logging, a community space, partner sharing, and a Premium
tier — with one structural difference: your data lives in a local file on
your own device, not a cloud account. Nothing here is Flo-branded software;
it's an independent app built to the same feature set, so this guide focuses
on what's the same, what's different, and how to bring your history over.

---

## 1. Create your account

Open the app and choose one of three ways in:

| Option | What it needs | Best for |
|---|---|---|
| **Create an account** | An email and a password (8+ characters) | Most people — lets you recover the account later |
| **Use Anonymous Mode** | Nothing at all | Maximum privacy. You get a generated handle (like `quiet-fern-402`) and a one-time recovery code — **write the code down**, it's the only way back in since there's no email on file |
| **I already have an account** | Email + password, or handle + recovery code | Returning to an existing cycliq account |

There's no "log in with Flo" — the two apps don't talk to each other, which is
exactly why Section 3 exists.

---

## 2. Answer four onboarding questions

1. **What brings you here?** — Track my cycle / Get pregnant / Avoid
   pregnancy / I'm pregnant. This sets your starting mode (you can change it
   later in **You → Mode**).
2. **How old are you?** — used only to pre-fill the perimenopause screener
   later; not stored anywhere else.
3. **When did your last period start?** — you can skip this if you don't
   remember. If you're about to import your Flo history (next section), skip
   it here — the import will fill in your real dates.
4. **Typical cycle length and period length** — two sliders. A reasonable
   starting guess is fine; predictions get sharper from real logged data
   within a cycle or two either way.

You'll land on **Today** with a first prediction already showing.

---

## 3. Bring your history over

This is the part that matters most for a migration, so it gets its own
screen: **You → Import from another app.**

### Flo has no export button

Flo doesn't let you download your data from inside the app. You have to
request it:

1. In Flo: **avatar → Help → Contact us** → ask for a copy of your data
2. Flo emails you two messages — one with a password-protected file, one with
   the password — usually within a month
3. Unlock the archive yourself (cycliq never asks for that password), then
   upload the unlocked file in cycliq's import screen

Because Flo doesn't publish the format of that file, cycliq reads it by
scanning for anything date-shaped and matching field names and values against
its own list of tracked symptoms — it's a best-effort reading, not a
guaranteed one-to-one conversion. **The import screen always shows a preview
of exactly what it found before anything is saved**, including a list of
anything it couldn't confidently place, so you can check it against your own
memory before committing.

### The better route: Apple Health

If you're on iPhone, Flo has already been quietly writing your cycle data to
Apple Health in the background — flow, symptoms, cervical mucus, temperature,
ovulation and pregnancy tests. That export is:

- **Self-serve** — no waiting on an email
- **Documented** — cycliq reads it with a precise, tested mapping instead of
  a best guess

**Steps:**

1. Open the **Health** app → tap your profile photo (top right) → **Export
   All Health Data**
2. Save the resulting `.zip` — you can upload it exactly as downloaded,
   cycliq unzips it itself
3. In cycliq: **You → Import from another app** → choose the file → review
   the preview → **Import**

This route also picks up data from any *other* app that wrote to Apple
Health, not just Flo, if you've used more than one tracker.

### If you have a spreadsheet or CSV

Any CSV with one row per day works, as long as it has a date column (`date`,
`day`, or `start_date`) and other columns whose names or values resemble
things you'd log — "flow", "cramps", "mood", "bbt", and so on. Same
preview-before-import safety applies.

### What the preview screen shows

However you get the file in, you'll see:

- How many periods and how many individual log entries were found
- The date range they cover
- A breakdown of which symptoms/events came through, and how many times each
- Anything that was found but **couldn't** be confidently matched — shown
  explicitly rather than silently dropped
- Your current totals, so you can see exactly what will be added

Nothing is written to your account until you tap **Import**. Uploading the
same file twice is safe — matching entries aren't duplicated.

---

## 4. Everything free, at a glance

| Feature | What it does |
|---|---|
| **Period & ovulation predictions** | Calendar-based prediction with a *window*, not a single date — the app tells you its own confidence and widens the window when your cycles are irregular, rather than pretending to a precision the math doesn't support |
| **100+ trackable symptoms & events** | Flow, mood, physical symptoms, discharge, sex, tests, lifestyle, medication, and free-form notes, organized into a single daily log sheet |
| **Calendar** | Month view showing logged periods, predicted periods, the fertile window, and estimated ovulation day, color-coded |
| **Custom reminders** | Period-coming, period-late, ovulation-coming, fertile-window-opens, plus daily reminders (medication, logging, water) — each with its own time of day |
| **Secret Chats** | An anonymous community, organized by topic (cycle, TTC, pregnancy, PCOS, endometriosis, birth control, mood, perimenopause, sex, general). You post under a generated handle, never your account name or email; contact details get automatically stripped from posts |
| **Anonymous Mode** | A full account with no name or email attached, from signup onward |
| **Basic Partner Mode** | Invite a partner to see your current cycle phase and when your next period is expected — nothing more, until you upgrade |
| **TTC fertility tools** | Fertile-window probability chart and a BBT/mucus/ovulation-test fertility chart — free, not Premium |
| **9 of the 40 library articles** | Cycle basics, birth-control comparison, tracking tips, and privacy — enough to get useful reading without a subscription |

---

## 5. What Premium unlocks

A 7-day free trial is offered once per account (**You → Premium**), after
which it's **$11.49/month or $39.99/year**. No card details are collected by
this app anywhere — starting the trial and choosing a plan are both handled
as local entitlement records.

| Feature | What it does |
|---|---|
| **Cycle patterns** | Finds which of *your own* symptoms cluster in which phase of *your own* cycle — e.g. "you log headaches 3× more often in your luteal phase" — measured against your personal baseline, not a population average. Needs at least two full logged cycles before it will say anything |
| **Cycle trends** | Whether your recent cycles are lengthening, shortening, or holding steady, plus your median length and variability |
| **Symptom predictions** | A 14-day forward look at which symptoms you've historically logged most in each upcoming phase |
| **Symptom Checker** | Three questionnaires — PCOS, endometriosis, perimenopause — that compare your answers (several pre-filled from your own logged cycle data) against the pattern each condition commonly presents with. Results are always framed as "this is not a diagnosis," with a plain explanation and next steps, never a percentage chance of having a condition |
| **Health Assistant** | Unlimited chat, grounded in the app's own article library. Runs on a local model first if one is available on your machine, so your questions never leave your device by default; only falls back to a cloud model if you've explicitly configured one, and even then sends only your cycle day/phase — never raw logs or free-text notes |
| **Full article & course library** | All 40 articles (each citing the public clinical guidance — ACOG, NHS, NICHD, Mayo Clinic — it was checked against) plus 5 multi-lesson video-style courses with progress tracking |
| **Six-month clinician report** | A one-page PDF summarizing your cycle lengths, symptom patterns by phase, and any saved Symptom Checker results — built to make a short appointment more productive |
| **Detailed pregnancy tracking** | Week-by-week development detail, a kick counter, and a contraction timer (labour vs. Braxton Hicks guidance included) |
| **Full Partner Mode** | Choose exactly which of six data categories a partner sees — cycle phase, period dates, fertile window, symptoms, mood, pregnancy progress — each toggled independently |

Free-tier screens for these show a locked preview card with a one-tap trial
button rather than a blank page, so you always know what you're missing and
never hit a dead end.

---

## 6. The other modes

Switch anytime under **You → Mode**:

- **Cycle tracking** (default) — the Today ring shows day-of-cycle, phase,
  and days until your next predicted period
- **Trying to conceive** — Today shows your fertile window and a day-by-day
  conception-probability chart instead
- **Pregnant** — Today shows week, trimester, and days to your due date; set
  it up with either your last period date or a due date from a scan

---

## 7. Your data, in your control

- Everything is stored in a single local file on this device — no cloud
  sync, no analytics, no third-party calls
- **You → Export everything** downloads a complete JSON copy of every table
  tied to your account, any time
- **You → Delete my account** is a real, immediate, complete deletion — every
  row cascades and removes, not a deactivation flag
- If you used Anonymous Mode, your recovery code is the *only* way back into
  the account — there's no "forgot password" email to fall back on

---

## FAQ

**My predictions look vague at first — is that a bug?**
No — it's deliberate. With one logged period, or none, the app tells you so
plainly and gives a wide window rather than a falsely precise date. Accuracy
improves noticeably after two full cycles, and keeps tightening for several
more.

**Why does the fertile window show a range instead of one day?**
Because the biology doesn't support single-day precision: in one well-known
study, only about 14% of people with a 28-day cycle actually ovulated on day
14. The app would rather show an honest window than a confident-looking wrong
answer.

**Some of my Flo data didn't come through.**
Check the import preview's "skipped" list — it names exactly what wasn't
recognized. If you exported from Apple Health instead of requesting Flo's own
file, that's usually the fix, since the Health export uses a documented
format cycliq maps precisely rather than guesses at.

**Can I import more than once?**
Yes. Re-uploading the same file changes nothing (it matches on date and
type), and uploading a *newer* export just adds whatever's new since your
last import.
