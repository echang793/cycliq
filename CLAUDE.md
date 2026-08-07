# cycliq

## Purpose

Women's health tracking: cycle, fertility, pregnancy. A functional clone of the
feature set of Flo, including its paid tier, built as an original
implementation — no Flo branding, copy, assets or content is reproduced
anywhere. The article library is written from scratch, each piece citing the
public clinical guidance it was checked against.

## Stack

Python 3.13, FastAPI, stdlib `sqlite3` (no ORM), reportlab for the PDF, and a
vanilla-JS installable PWA. No build step for the frontend.

## Commands

```bash
.venv/bin/python src/server.py            # http://127.0.0.1:8103
CYCLIQ_HOST=0.0.0.0 .venv/bin/python src/server.py   # + reachable on WiFi, for phone use
.venv/bin/python -m pytest tests/ -q      # full suite
```

Venv is Python 3.13. Ports 8100/8101/8102 belong to dinkiq/spikeiq/pongiq.
`CYCLIQ_HOST`/`CYCLIQ_PORT` are read only in `server.py`'s `__main__` block —
default stays `127.0.0.1` so nothing is reachable off-machine unless someone
explicitly opts in. This app is mobile-first by design (see README's "Use it
on your phone"); the LAN bind is the primary intended way to actually use it
day to day, not an edge case.

## Free vs Premium

The split mirrors the app being cloned, and `billing.PREMIUM_FEATURES` is the
single source of truth for the paywall copy.

| Free | Premium |
|------|---------|
| Period + ovulation predictions | Cycle patterns, trends, symptom predictions |
| 90+ trackable symptoms and events | Symptom Checker (PCOS, endo, perimenopause) |
| Custom reminders | Unlimited Health Assistant |
| Secret Chats community | Full article + course library |
| Anonymous Mode | Six-month report PDF |
| Basic Partner Mode (phase + period dates) | Detailed pregnancy tracking, full Partner Mode |

## Architecture

Each feature module owns its own `APIRouter`; `server.py` only wires them
together and serves the PWA. `deps.py` holds the two dependencies every module
shares: `current_user` and `require_premium(feature)`.

Data flow for the core loop:

`period_events` → `cycle` (derive cycles, phases) → `predict` (window, ovulation,
confidence) → `insights` / `patterns` / `ttc` / `report`.

`daily_logs` is one row per (day, category, code) and is the input to
`patterns`, `ttc` charting and the report.

## Invariants

- **Predict a window, never a day.** Only ~14% of people with 28-day cycles
  ovulate on day 14 (mode day 16, range 11–20). Every prediction carries an
  interval and a confidence, and `predict._note` explains where the number came
  from. Do not add a UI that shows a bare ovulation date.
- **Luteal length is measured, not assumed.** 14 days is only the fallback.
  `predict.estimate_luteal` derives it per user from BBT thermal shift or a
  positive LH test, clamped to 10–16.
- **Implausible gaps are not cycles.** `cycle.derive_cycles` drops intervals
  outside 15–90 days — those are double-logged periods and gaps in logging, and
  letting them into the statistics poisons every later prediction.
- **Irregularity is MAD *or* spread.** MAD alone misses bimodal cycles
  (23, 48, 25, 52, 22 has a tiny MAD and is plainly irregular), so
  `predict.is_irregular` also checks shortest-to-longest.
- **Patterns have minimum-sample gates.** `MIN_CYCLES`, `MIN_TOTAL_LOGS`,
  `MIN_PHASE_LOGS` and `LIFT_THRESHOLD` in `patterns.py` exist so two data
  points never become a claim. Lift is against the user's *own* baseline.
- **Screeners never diagnose.** `checker.py` returns a match band, never a
  probability of disease. PCOS and perimenopause have gates that cap a "strong"
  band when the defining feature (irregular ovulation / persistent cycle-length
  change) is absent. Results are stored only on explicit consent.
- **Partner Mode is assembled from scopes, not filtered after.**
  `partner.partner_view` builds the payload key by key from
  `effective_scopes()`, which re-caps a free-tier owner to `BASIC_SCOPES` at
  read time — so cancelling a subscription immediately narrows an existing link.
- **The assistant degrades, never fails.** Ollama → Anthropic → deterministic
  retrieval. Only aggregates (cycle day, phase, cycle length) are ever sent to
  the cloud tier, and that tier is off unless `ANTHROPIC_API_KEY` is set.
- **Every premium route returns 402 with an upsell body**, never 403 and never a
  blank page. `tests/test_gating.py` enumerates them; add new premium routes to
  that list.
- **The service worker never caches `/api/`.** Cycle data must not sit in a
  cache the user cannot clear from inside the app.

## Importing from other apps

`importer.py` is the façade (detect → parse → preview → apply); the parsers live
in `import_apple.py` (HealthKit XML/zip) and `import_sniff.py` (unknown-schema
JSON and CSV), on the shared types in `import_staging.py`.

- **Apple Health is the good path** and the one to point people at. Flo has no
  export button: you request a copy through in-app support and get a
  password-protected JSON by email, usually within a month. Never accept an
  archive password — the user decrypts it themselves.
- **Flo's schema is undocumented**, so `import_sniff` classifies by key and
  value name and *reports what it could not place*. A guess that announces
  itself is useful; a silent one is not. Never quietly drop an unrecognised
  field — it belongs in `Staged.skipped` so the preview shows it.
- **Preview before write, always.** `_PENDING` holds parsed results in memory
  only, so a rejected import leaves nothing on disk.
- **Import is idempotent.** Both target tables upsert on their natural key, so
  re-importing the same export adds nothing. `test_importer` asserts this.
- When adding a mapping, add it to the right table and let
  `test_every_mapped_code_exists_in_the_catalog` check it against
  `symptoms.CATALOG` — a typo'd code would otherwise be silently discarded by
  `Staged.log`.
- Health exports are hundreds of MB; the Apple parser streams with `iterparse`.
  Do not clear non-`Record` elements in that loop — `MetadataEntry` children end
  before their parent, and clearing one wipes the attributes the Record handler
  is about to read (this silently lost `HKMenstrualCycleStart`).

## Privacy

Local SQLite at `~/.cycliq/cycliq.db`, mode 0600. No analytics, no telemetry, no
third-party calls. Handles are generated pseudonyms and are never derived from
the email — the community feed cannot be linked back to an identity by reading a
name. Anonymous Mode creates an account with no identifying field at all.
`DELETE /api/me` is a hard delete: every health table cascades on `user_id`.

## Gotchas

- A PostToolUse hook runs `ruff check --fix` and DELETES imports it thinks are
  unused — add imports in the same edit as the code that uses them, and verify
  by importing the module, not just `py_compile`.
- `db.connect()` caches one connection per thread *per path*; tests point
  `CYCLIQ_DB` at a tmp file and call `db.close()` between cases.
- `content.search` is token-based, not substring — a question like "why do I get
  cramps on my period?" has to reach the cramps article, because that retrieval
  is what grounds the assistant's rules tier.
- Single-choice log categories (flow, discharge) replace the day's existing
  value rather than stacking; `symptoms.log_entry` handles that by category kind.
- **Frontend "today"/date-from-object conversion must never go through
  `toISOString()`.** It round-trips through UTC: on `new Date()` (the current
  moment) that rolls the date forward for anyone west of UTC in the evening;
  on a locally-built midnight date (`new Date(y, m, d)`, e.g. every calendar
  grid cell) it rolls the date *backward* for anyone east of UTC, every single
  day. `static/app.js`'s `iso()` reads local Y/M/D directly instead — found
  2026-08-06 when the log-period sheet defaulted to tomorrow. Timestamps that
  need to preserve an *instant* (contraction start times, session tokens) are
  the one case where `toISOString()` is correct — don't "fix" those.
- **Static assets need `Cache-Control: no-cache` and the service worker must
  fetch with `{cache: 'reload'}`, or a shipped fix can silently never reach an
  already-open tab.** `StaticFiles` ships `Last-Modified` with no
  `Cache-Control`, so browsers apply heuristic freshness and can serve stale
  JS without a network round trip at all — and the SW's own network-first
  `fetch()` is subject to that same disk cache unless told not to trust it.
  Bump `CACHE` in `static/sw.js` on any shell-file change. Found debugging the
  date fix above: two ordinary reloads didn't pick it up.
- `content._idf` weights search matches by rarity — a flat per-tier score lets
  "period" (in most titles, this being a menstrual-cycle library) always beat
  a specific symptom that only appears in one article's body. If you add
  articles, a very common word can still dominate; check with
  `content.search()` directly rather than assuming a new article will surface.
