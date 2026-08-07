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
