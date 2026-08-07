# cycliq

Cycle, fertility and pregnancy tracking. Local-first: your data lives in a
SQLite file on your own machine, not a cloud account.

See [docs/migrating-from-flo.md](docs/migrating-from-flo.md) for the full
feature list and a setup/migration guide.

## Requirements

- Python 3.13
- No API keys, no accounts, no external services required to run it

## Run it

```bash
git clone <this-repo-url>
cd cycliq
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python src/server.py
```

Open **http://127.0.0.1:8103**.

## Use it on your phone

cycliq is a mobile-first installable PWA — this is the primary, intended way
to use it day to day.

1. Start the server so it's reachable on your WiFi network, not just this
   computer:

   ```bash
   CYCLIQ_HOST=0.0.0.0 .venv/bin/python src/server.py
   ```

   It prints the exact address to use, e.g. `On your phone (same WiFi):
   http://192.168.1.163:8103`. (The default without `CYCLIQ_HOST` stays
   `127.0.0.1`-only, so running it the plain way never exposes anything to
   the network by accident.)

2. On the phone — **same WiFi as this computer** — open that address in
   Safari (iPhone) or Chrome (Android).
3. Tap **Share → Add to Home Screen** (Safari) or the browser's install
   prompt (Chrome). It now opens full-screen with its own icon, like any
   other app — no browser address bar, works offline for the app shell.
4. The computer needs to be on and the server running for the phone to reach
   it — there's no cloud component. If the server stops, the phone shows a
   simple offline screen until it's running again.

Your computer's IP address can change when it reconnects to WiFi, so if the
phone stops connecting after a while, just re-run step 1 and check the
printed address again.

## Run the tests

```bash
.venv/bin/python -m pytest tests/ -q
```

## Optional: the Health Assistant's AI backends

The in-app Health Assistant works out of the box using a deterministic,
library-grounded fallback — no setup needed. Two optional upgrades:

- **Ollama** (local, private): install it, pull a model (e.g.
  `ollama pull llama3.1`), and run it — cycliq auto-detects it at
  `http://127.0.0.1:11434`. Nothing leaves your machine.
- **Anthropic API** (cloud, optional): set `ANTHROPIC_API_KEY` in your
  environment before starting the server. Only aggregate cycle info (day,
  phase, cycle length) is ever sent — never raw logs or notes.

## Where your data lives

`~/.cycliq/cycliq.db` — a single local SQLite file, mode 0600. Delete it to
start fresh. Export/delete are also available in-app under **You**.
