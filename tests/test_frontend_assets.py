"""The frontend must stay self-contained: no third-party requests, fonts served
locally, and the PWA colors consistent with the stylesheet."""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"
EXTERNAL = re.compile(r"""(?:src|href|url\()\s*=?\s*["']?(https?:)?//(?!localhost|127\.0\.0\.1)""", re.I)


def test_no_third_party_requests_in_frontend():
    offenders = []
    for path in STATIC.rglob("*"):
        if path.suffix not in {".html", ".css", ".js"}:
            continue
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if EXTERNAL.search(line) and "w3.org" not in line:
                offenders.append(f"{path.name}:{number}: {line.strip()[:80]}")
    assert offenders == [], offenders


def test_bundled_fonts_exist_and_are_served(client):
    for name in ("bricolage-grotesque-latin.woff2", "hanken-grotesk-latin.woff2"):
        assert (STATIC / "fonts" / name).stat().st_size > 10_000
        res = client.get(f"/static/fonts/{name}")
        assert res.status_code == 200
        assert res.content[:4] == b"wOF2"


def test_stylesheet_declares_local_font_faces():
    css = (STATIC / "style.css").read_text()
    assert "/static/fonts/bricolage-grotesque-latin.woff2" in css
    assert "/static/fonts/hanken-grotesk-latin.woff2" in css


def test_service_worker_precaches_the_fonts():
    sw = (STATIC / "sw.js").read_text()
    assert "hanken-grotesk-latin.woff2" in sw and "bricolage-grotesque-latin.woff2" in sw


def test_manifest_colors_match_the_design_tokens(client):
    css = (STATIC / "style.css").read_text()
    manifest = client.get("/manifest.json").json()
    plum = re.search(r"--plum:\s*(#[0-9A-Fa-f]{6})", css).group(1).lower()
    bg = re.search(r"--bg:\s*(#[0-9A-Fa-f]{6})", css).group(1).lower()
    assert manifest["theme_color"].lower() == plum
    assert manifest["background_color"].lower() == bg
