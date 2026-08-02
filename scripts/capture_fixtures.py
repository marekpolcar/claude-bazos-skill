"""Authed GET capture of parser fixtures (raw -> ~/.bazos-inzerce/captures/).

GET ONLY — this tool never issues a POST, so it cannot mutate anything on
bazos. It uses the same browser_cookie3 -> requests technique the discovery
scripts proved; ``auth.py`` formalizes it for the driver. Raw captures land
OUTSIDE the repo; run ``scrub_fixtures.py`` afterwards to produce PII-free
fixtures under ``tests/fixtures/``.

The authed insert form and moje-inzeraty are auth-gated: without a verified
``bid``+``bkod`` session they return the SMS gate. Run this only when Chrome
holds a verified bazos session (Keychain will prompt — click **Allow**).

Usage:
    "$HOME/.bazos-inzerce/venv/bin/python3" scripts/capture_fixtures.py
"""

import os
import sys

CAPTURES_DIR = os.path.expanduser("~/.bazos-inzerce/captures")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# (filename, url, authed?) — authed=False deliberately omits cookies (anon gate).
TARGETS = [
    ("homepage.html", "https://www.bazos.cz/", True),
    ("insert_form.html", "https://knihy.bazos.cz/pridat-inzerat.php", True),
    ("moje_inzeraty_authed.html", "https://www.bazos.cz/moje-inzeraty.php", True),
    ("moje_inzeraty_anon.html", "https://www.bazos.cz/moje-inzeraty.php", False),
    ("sms_gate.html", "https://knihy.bazos.cz/pridat-inzerat.php", False),
]


def _authed_session():
    import browser_cookie3 as bc3
    import requests
    cj = bc3.chrome(domain_name="bazos")
    s = requests.Session()
    s.headers["User-Agent"] = UA
    for c in cj:
        if "bazos" in c.domain:
            s.cookies.set(c.name, c.value, domain=c.domain, path=c.path)
    return s


def _anon_session():
    import requests
    s = requests.Session()
    s.headers["User-Agent"] = UA
    return s


def capture(out_dir=CAPTURES_DIR):
    os.makedirs(out_dir, mode=0o700, exist_ok=True)
    authed = _authed_session()
    anon = _anon_session()
    for name, url, need_auth in TARGETS:
        sess = authed if need_auth else anon
        r = sess.get(url, timeout=25, allow_redirects=True)  # GET only
        path = os.path.join(out_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(r.text)
        flag = "authed" if need_auth else "anon"
        gate = "formovereni" in r.text.lower()
        print(f"{name:28} {flag:6} status={r.status_code} bytes={len(r.text)} "
              f"gate={'YES' if gate else 'no'} -> {path}")
        if need_auth and gate:
            print(f"  WARNING: {name} came back as the SMS gate — session not "
                  f"verified? The authed fixtures need a verified bid+bkod.",
                  file=sys.stderr)
    print("\nRaw captures written outside the repo. Next: scrub_fixtures.py, "
          "then run test_fixture_hygiene.py before committing.")


if __name__ == "__main__":
    capture()
