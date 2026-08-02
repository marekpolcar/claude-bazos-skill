---
name: bazos-sprava-inzeratu
description: >-
  Use whenever the user wants to insert, edit, or delete a bazos.cz classified
  ad. Triggers include "vlož inzerát na bazoš", "publikuj to na bazoši",
  "smaž/uprav inzerát", "změň cenu inzerátu", or pointing at a `prodej/<x>/`
  folder that already has an inzerat.md. NOT for preparing the folder (photo
  cleanup, price research, ad text) - that is bazos-priprava-inzeratu. Drives
  a real browser (Playwright); reads categories live; previews before every
  publish/delete.
---

# bazos-sprava-inzeratu

Insert / edit / delete bazos.cz ads on the user's behalf. **Preview → confirm by
default**; never fabricate `cena` or condition; read categories live.

## Invocation

CWD is the user's project and bare `python` does not exist here. Resolve the
plugin root once, then run everything through the skill venv:

```
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-${CLAUDE_SKILL_DIR}/../..}"
"$HOME/.bazos-inzerce/venv/bin/python3" "$PLUGIN_ROOT/scripts/bazos.py" <cmd> ...
```

Every command prints JSON. Reference (under `$PLUGIN_ROOT`):
`references/ad-schema.md`, `references/inzerat-sablona.md`,
`references/category-resolver.md`, `references/form-contract.md`.

## Every session

0. **Preflight** - `bazos.py preflight`. If `ok:false`, show the hint and stop
   (missing deps/chromium block; a missing session resolves itself on first real
   command via Keychain **Allow** or a one-time headed login).

## Insert one ad

1. **Gather** per `ad-schema.md` resolution order: (1) conversation, (2) a
   `prodej/<x>/` folder (the CLI parses it), (3) derivation - anything derived is
   flagged "odvozeno - potvrď" and must be confirmed. A folder of raw photos
   without an `inzerat.md` is not ready: hand it to **bazos-priprava-inzeratu**
   first - this skill publishes prepared folders, it does not research or draft
   them. Cheap offline pre-check: `bazos.py zkontrolovat <folder>` (reports
   `problems`, `derived`, `missing_photos` without touching the browser).
   Derived flags persist in the folder's `Odvozeno:` line - confirming a field
   with the user means deleting its name from that line (empty line → delete
   the line). Contact fields (`jmeno/telefon/email`) come from the session, not
   the folder - the CLI fills them from `identity` automatically.
2. **Resolve category** (seed with the folder's `kategorie_hint`):
   `bazos.py sections` → pick the sekce; `bazos.py categories --sekce <s>` →
   pick the option `value` by label. Ambiguous (e.g. children's book → `knihy`
   vs `deti`)? **Ask** (AskUserQuestion), remember the choice.
3. **Canary** (cheap, before publishing): `bazos.py canary --sekce <s>`. If
   `conforms:false`, surface the violations and stop - the form drifted.
4. **Preview**: `bazos.py vlozit <folder> --sekce <s> --category <value>
   [--cenavyber <cv>]`. If it returns `problems`, that's the validation gate -
   `AskUserQuestion` for exactly what's missing, then retry. On success open the
   `screenshot`, show `fields` + resolved category + any "odvozeno" flags.
5. **Publish on explicit go**: rerun with `--submit`. Before publishing, the CLI
   **self-guards** (returns `refused` without posting) if the ad has unconfirmed
   derived fields, already has a `published_url`, or a same-title ad is already
   live (`fetch_moje_inzeraty` dedupe - bazoš would auto-delete the older). On
   success it records the live URL back into the folder (`save_published`). Still
   resolve/confirm any "odvozeno" fields with the user *before* `--submit` - the
   guard refuses them, it doesn't confirm them for you.

## Batch (the real multi-book job)

Iterate the folders. Each `--submit` already self-guards (skip-if-published +
dedupe + derived refusal, above), but still add randomized **60-180 s** pacing
between submits (mandatory - the CLI does not pace for you). `--submit` is
insert-only and **never** applies to `smazat` (deletes are always attended).

## Delete / edit

- **Delete**: `bazos.py moje` → find the ad (title→id). `bazos.py smazat <id>
  --sekce <s>` previews (screenshot the confirm page); confirm the **title** with
  the user, then `--confirm` (pass `--heslo` if the page asks). Deletes are
  **always attended** - never batched, `--yes` never applies.
- **Sold outcome (after every confirmed delete)**: ask "prodáno? za kolik?"
  (AskUserQuestion: prodáno za X Kč / neprodáno, jen stáhnout). If sold, find
  the ad's `prodej/<x>/` folder - the one whose `Publikováno:` line contains
  the deleted ad's id - and record it:
  `bazos.py prodano <folder> --cena <X>`. It appends the sold record incl.
  days-to-sell, which future price research reads. No folder found → note the
  outcome in the conversation and move on (never guess a folder).
- **Edit**: `bazos.py upravit <id> --sekce <s> --set cena=111` previews the
  staged change; `--save` on explicit go.

## Fallbacks (§9)

- Category gate/options error (`GateError`) → the session isn't verified; ask the
  user to (re)verify, don't guess.
- Photo upload miss → the driver retries once, then reports; surface it.
- Submit that doesn't yield a live ad → report the on-page error, never claim
  success.
