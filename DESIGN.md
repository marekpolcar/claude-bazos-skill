# bazos-inzerce - design / spec

**Date:** 2026-07-03
**Status:** approved design, pre-implementation (rev 2: local mock replaced by
live-page route-interception harness after plan review - see §10)
**Author:** Marek Polcar (with Claude)

A shareable Claude Code skill that inserts, edits, and deletes classified ads on
**bazos.cz** on behalf of the current user, driving a real browser (Playwright)
so it survives the site's JavaScript upload flow and light anti-bot measures.

---

## 1. Goals & non-goals

**Goals**
- Three operations: **vložit** (insert), **upravit** (edit), **smazat** (delete).
- **Shareable**: zero personal data in the repo. Every user brings their own bazos
  session; the ad content is input, not baked in.
- **Long-term maintainable**: minimize the "fix it every week" surface. The site's
  authoritative facts (category options, form fields) are read **live at runtime**
  rather than hardcoded, so bazos relabels/reorders without breaking us.
- **Model-driven input**: the model gathers ad fields from whatever context exists
  (folder, pasted text, files, web lookup) and **asks the user for anything missing
  or ambiguous** - it never fabricates price or condition.

**Non-goals (v1)**
- No general "post to N portals" (Sbazar/FB) - bazos only.
- No account registration / SMS-verification automation - the user verifies once,
  by hand, in a real browser (device stays verified ~1 year in cookies).
- No headless-at-scale spam. This is a personal-selling tool; respect ToS and pace.

## 2. Constraints & context (verified during discovery)

- Bazoš has **no official public posting API** (only Reality, agency-only, paid).
  Direct API automation is against ToS and blockable → we drive the real web UI.
- **"Login" = a verified-device cookie**, not an account. Key cookies: `bid`
  (device id, secure) + `bkod` (auth key), plus `bjmeno/bmail/btelefon`. Valid
  ~1 year. Confirmed: with these cookies, `moje-inzeraty.php` renders the verified
  user server-side, **no SMS / no CAPTCHA**.
- **No email activation** of a new ad on a verified device - it goes live on submit.
- Insert form (`<sekce>.bazos.cz/pridat-inzerat.php` → POST `/insert.php`):
  fields `category, nadpis, popis, cena, cenavyber, lokalita, jmeno, telefoni,
  maili, heslobazar`; hidden `vkm=m`, static honeypot `sfdsfrtret=afdggfd`.
  **No CSRF/session token, no CAPTCHA.**
- **Photos upload via Dropzone.js** → async POST `/upload.php`, returned ids wired
  into hidden `files[]`, then the main form posts. This JS orchestration is the #1
  reason we use a real browser rather than a raw `requests` POST.
- Delete: stable URL `https://<sekce>.bazos.cz/smazat/<id>.php` (+ confirm).

## 3. Architecture

Self-contained skill folder, no `~/laif` references:

```
bazos-inzerce/
  SKILL.md               # when-to-use + how the model orchestrates the scripts
  DESIGN.md              # this document
  README.md              # install / share instructions for other users
  requirements.txt       # playwright, browser_cookie3
  scripts/
    auth.py              # hybrid auth → Playwright storage_state + identity from cookies
    parse_inzerat.py     # parse a prodej/<x>/-style folder → ad dict (one input source)
    category.py          # live category resolver: list sections + section's <select> options
    moje.py              # moje-inzeraty listing: title→id targeting, pre-insert dedupe
    bazos.py             # Playwright driver: vlozit() / upravit() / smazat()
    conformance.py       # live bazos vs recorded contract - drift canary
    capture_fixtures.py  # authed GET capture of parser fixtures (raw → ~/.bazos-inzerce/)
    scrub_fixtures.py    # deterministic PII scrub (fake identity) before fixtures enter the repo
  tests/
    conftest.py          # interception harness: non-GET guard + write interceptors
    fixtures/            # scrubbed parser fixtures (markup-verbatim, PII-free)
  references/
    ad-schema.md         # canonical ad field schema (required/optional, validation rules)
    category-resolver.md # documented live-discovery procedure (NOT a hardcoded map)
    form-contract.md     # documented form field names, for maintainers
```

The scripts are thin, single-purpose, and independently runnable. The **model**
(via SKILL.md) is the orchestrator: gather input → resolve category → preview →
confirm → act.

State lives in the user's home, outside the repo:
`~/.bazos-inzerce/profile/` (Playwright persistent profile) and
`~/.bazos-inzerce/state.json` (cached storage_state).

## 4. Auth - hybrid (`auth.py`)

1. **Extract**: try `browser_cookie3.chrome(domain_name="bazos")`. If it yields a
   `bid`+`bkod` pair, build a Playwright `storage_state` from those cookies and
   **validate** by loading `moje-inzeraty.php` and checking the verified-user
   signal (own phone rendered, no SMS prompt).
2. **Fallback login**: if extraction is unavailable (non-mac / other browser / ABE)
   or the session is invalid, launch a **headed** Playwright with the persistent
   profile `~/.bazos-inzerce/profile`, open bazos, and let the user log in +
   SMS-verify **once**. Detect success, persist the profile.
3. **Reuse**: cache the working `storage_state`; subsequent runs are non-interactive
   until it expires, then fall back to (2).

No secrets in the repo. `~/.bazos-inzerce/` is user-local.

## 5. Input - schema + agentic gathering

The contract is a **schema**, not a file. `references/ad-schema.md` defines:

- **Required**: `nadpis`, `popis` (body), `cena`, section+category (see §6),
  `lokalita` (PSČ/město), `jmeno`, `telefon`, `email`, **≥1 photo**.
- **Optional**: `cenavyber` (dohodou / v textu / ...), `heslobazar` (ad-management
  password - auto-generated and saved back next to the source if absent).

**Resolution order (model-driven):**
1. Explicit conversation input (pasted text, a pointed-at file/folder/URL).
2. A `prodej/<x>/`-style folder if present → `parse_inzerat.py` (parses
   `- **Key:** value` lines + the `## Text inzerátu` body; photos = image files).
3. Derivation: read photos, read neighboring files, optionally web-lookup product
   facts to *draft* the text.

**Validation gate (hard):** before preview, all required fields must be present and
≥1 photo must resolve to a real file. Anything missing or ambiguous → the model
**asks the user** (AskUserQuestion) for exactly that piece.

**Never fabricate**: `cena` and `stav`/condition are never invented. Any field the
model *derived* (e.g. condition guessed from photos) is flagged in the preview as
"odvozeno - potvrď".

## 6. Category resolver - live, model-chosen (`category.py`)

Two levels, both read live so they don't rot:

1. **Sekce (subdomain)**: fetch the live section list from the bazos homepage nav
   (`*.bazos.cz` links). The model picks the best semantic match to the item.
2. **Rubrika (`<select name="category">`)**: load the chosen section's
   `pridat-inzerat.php`, extract the real `<option>` set (value + visible label) at
   runtime. The model picks by label.

**Confirmation/ambiguity**: the preview shows `Sekce → Rubrika` + confidence. Low
confidence or multiple plausible sections (e.g. a children's book → `knihy` vs
`deti`) → ask the user; remember the choice for that item.

`references/category-resolver.md` documents this **procedure** (plus an optional
short-lived cache for speed). It is deliberately **not** a hardcoded category map.

## 7. Operations (`bazos.py`)

All three run through the authed Playwright context.

- **`vlozit(ad, preview=True)`** - navigate to `<sekce>.bazos.cz/pridat-inzerat.php`,
  fill fields, drag photos into Dropzone (browser handles `/upload.php` + `files[]`),
  then: `preview` → screenshot + field summary, stop; on confirm → submit and
  verify the ad is live (capture the resulting ad URL/id).
- **`smazat(id, sekce)`** - navigate to `smazat/<id>.php`, confirm deletion, verify
  it's gone from `moje-inzeraty.php`.
- **`upravit(id, sekce, changes)`** - open the ad's edit page from
  `moje-inzeraty.php`. This flow is **mapped during implementation** by inspecting
  the "Upravit" affordance on one of the user's own live ads (read-only inspection
  first, no mutation), then implemented against the discovered form.

## 8. Safety model

- **Preview → confirm by default.** The model fills, shows the preview (fields +
  photos + resolved category + any "odvozeno" flags), and submits only on explicit
  user go. `--yes` opts out for trusted batch runs.
- Outward-facing publish/delete is never done silently; deletes always confirm the
  target ad's title first.
- Honor ToS/ban reality: human-like pacing, sane volumes, real-browser fingerprint.

## 9. Error handling

- Auth invalid/expired → fall back to headed login (§4.2), never proceed unauthed.
- Missing/ambiguous input → ask, don't guess (§5).
- Category options not found (site change) → surface the raw page + ask the user to
  pick, rather than failing silently.
- Photo upload failure (Dropzone) → detect via absence of `files[]`, retry once,
  then report.
- Submit that doesn't yield a live ad → report the on-page error text, don't claim
  success.

## 10. Test harness - live pages, intercepted writes (+ conformance canary)

*(rev 2 - supersedes the original local-mock design: the mock's cost grew during
plan review - capture + PII scrub of whole pages, JS/CSS asset capture with origin
rewriting, edit-page templating - while its submit-side behavior was invented by us
anyway. Testing against the live page gives higher fidelity for a fraction of the
work, with categorically stronger write-safety.)*

The driver is developed and tested against the **live site, read-only, via
Playwright route interception** (`tests/conftest.py`):

1. **Non-GET guard.** Every test context installs a global route that **aborts all
   non-GET requests** and records them. GETs pass through to live bazos (authed,
   human-paced). No mutating request can escape during development - a categorical
   guarantee, not env-var discipline.
2. **Write interceptors on top of the guard.** Explicit per-test routes fulfill the
   flow's POSTs with faked responses: `/upload.php` → fake file id (in the exact
   response format recorded during discovery - the one contract we must mimic; if
   it's wrong, the site's own JS leaves `files[]` empty and tests fail visibly),
   `/insert.php` → capture the full payload for assertions + synthetic success page,
   same pattern for the delete confirm and edit save.

The driver thus sees the **real current page with its real JS and real Dropzone** -
no captured assets, no fixture rot; when bazos changes markup, the tests break
against reality immediately. Committed fixtures shrink to a handful of scrubbed
HTML files for pure parsers (category options, moje-inzeraty).

**`scripts/conformance.py` stays as the drift canary**: fetches live pages and
asserts the structural contract (required field names, `<select name="category">`,
honeypot name+value, URL shapes). Cheap (two GETs, no browser) - run before any
batch session; names exactly what changed.

**What green tests do NOT prove:** the faked POST responses mean fill/click/payload
correctness is proven, but server-side acceptance (anti-bot, `insert.php`
validation, honeypot handling, the real success redirect) is not. **One gated real
end-to-end publish (Task 9) remains mandatory** as the final proof, and is the
designated place to correct success-detection against reality.

**Test layers, fastest→slowest:**
- **Unit** (no network): schema/validation, folder parsing, category parsers, auth
  helpers, canary contract - against scrubbed HTML/folder fixtures.
- **Integration** (live pages, harness-guarded, writes intercepted): the full driver
  `vlozit/smazat/upravit` preview+act paths. Requires a verified session; serial,
  human-paced.
- **Conformance canary** (live, read-only): structural contract check; run before
  batch sessions to catch drift.
- **Acceptance** (live, gated): one real Albi book published on the user's explicit
  go (Task 9).

## 11. Distribution

Self-contained folder. Other users: copy into their `~/.claude/skills/`, run
`pip install -r requirements.txt` + `playwright install chromium`, first run does the
one-time login. No personal data travels with the skill. Marek uses it from `~/laif`
but the skill itself is path-independent.
