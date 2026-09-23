---
name: bazos-priprava-inzeratu
argument-hint: "[<photo-folder>|<item-name>]"
description: >-
  Use whenever the user wants to turn items into ready-to-publish bazos.cz ad
  folders. Triggers include "chci prodat tyhle věci", "připrav inzeráty",
  "naceň tohle", pointing at folders of raw photos, or naming an item they
  want to sell (even with no photos yet). Produces prodej/<x>/ folders with
  cleaned photos, cited price research, and a drafted inzerat.md. NOT for
  publishing, editing, or deleting live ads - that is bazos-sprava-inzeratu.
---

# bazos-priprava-inzeratu

Turn raw photos and/or an item name into `prodej/<x>/` folders that
**bazos-sprava-inzeratu** can publish. Everything inferred is flagged
"odvozeno - potvrď". Nothing is published from here.

## Invocation

CWD is the user's project and bare `python` does not exist here. Resolve the
plugin root once, then run everything through the skill venv:

```
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-${CLAUDE_SKILL_DIR}/../..}"
"$HOME/.bazos-inzerce/venv/bin/python3" "$PLUGIN_ROOT/scripts/bazos.py" <cmd> ...
```

Every command prints JSON. The output contract is
`references/inzerat-sablona.md` (under `$PLUGIN_ROOT`) - follow it exactly;
`tests/test_sablona.py` pins it to the parser.

## Hard rules

- **Never fabricate `cena` or condition.** No usable price sources → leave
  `Cena:` empty and ask the user. Condition: visible wear may be described
  from photos but stays unconfirmed until the user approves the preview;
  hidden defects only ever come from the user - ask once per item ("nějaké
  vady, které na fotkách nevidím?").
- **Never write contact fields** (`jmeno`, `telefon`, `email`) into the folder
  - they are session-owned and injected at publish time.
- **From-name drafts never get web or stock images** (misrepresentation +
  rights). The folder waits for the user's own photos.
- **No publishing/editing/deleting** - that is bazos-sprava-inzeratu's job.
- `bazos.py fotky` overwrites photos in place - the folder must hold copies
  exported for sale, not the only originals. Say so when the user points at a
  folder that looks like a photo archive.

## Input modes

- **From images**: folder(s) of photos → identify visually.
- **From name**: no photos → researched draft; `- **Fotky:** (čeká na fotky -
  TODO)` per the template, so `zkontrolovat` reports `missing_photos: true`
  instead of a failure.
- Mixed batches are fine; use whatever input exists per item.

## Workflow (batch of one or more items)

0. **Batch setup** - ask **lokalita** once per batch (`obec, PSČ`) unless the
   conversation already says it. Collect the item list (folders and/or names).
1. **Identify** - read the photos (or research the name): title, author/brand,
   edition/variant details, visible condition. Anything inferred (title, cena,
   kategorie) goes on the item's `Odvozeno:` line.
2. **Photo prep** - `bazos.py fotky <folder>`: strips EXIF/GPS, fixes
   orientation, downscales to 1200 px long edge, converts to JPEG, in place;
   idempotent; JSON report. **Excluded photos stay excluded** - a photo whose
   metadata could not be stripped is renamed `*.vyrazeno` and never enters the
   ad (home photos carry GPS); tell the user which and why.
3. **Price research** - sources in priority order, every claim cited into
   **`pruzkum.md`** in the item folder (never into inzerat.md - the parser
   must not see it):
   1. **Live bazoš comps** - search bazos.cz for the item; cite 2-3 comparable
      listings as URL + asking price + condition.
   2. **Retail/new price** as the anchor (URL + price).
   3. **Own sold history** - `Prodáno:`/`Cena:` lines from sibling
      `prodej/*/inzerat.md` folders of similar items.
   Suggest `cena` from the comps, write it into inzerat.md, and list `cena` on
   the `Odvozeno:` line. No comps and no anchor → leave `Cena:` empty and ask.
4. **Draft `inzerat.md`** - exactly per `references/inzerat-sablona.md`:
   Nadpis, Cena, Kategorie hint, Typ (Reality only: Prodej / Pronájem),
   Lokalita (from step 0), Fotky in publish
   order (first = cover, use the cleaned .jpg names), Odvozeno line, popis
   (what it is, edition, confirmed/visible condition, předání/zaslání line).
   Never Heslobazar/Publikováno/Prodáno - those come later.
5. **Rename folder** (default ON when the current name is uninformative -
   `IMG_1234`, `kniha2`, `Nová složka`; OFF when it already names the item):
   rename to a short item title. The rename shows in the preview table
   **before** it happens.
6. **Bundle block** (only when the batch has 2+ items): lot price = 80 % of
   the summed asking prices, rounded down to the nearest 50 Kč -
   `lot = int(sum_cen * 0.8) // 50 * 50`. Append a short cross-sell paragraph
   to each item's popis ("Prodávám i další <kusy> - při koupi všeho dohromady
   <lot> Kč, viz moje další inzeráty.") and flag the lot price as odvozeno in
   the preview.
7. **Validate** - `bazos.py zkontrolovat <folder>` per item. Expect
   `valid: true` (or `missing_photos: true` for from-name drafts - that is the
   expected report, not an error). Fix real `problems` and rerun; never hand
   over a folder with problems.
8. **Preview** - one table for the whole batch:

   | položka | cena (zdroje) | kategorie hint | rename | flags |

   where flags = odvozeno fields / `missing_photos` / excluded photos. Ask the
   user to confirm derived fields; each confirmed field is deleted from its
   `Odvozeno:` line (empty line → delete the line). Unconfirmed fields stay
   flagged - bazos-sprava-inzeratu's publish guard refuses them (second gate,
   same rule).

## Handoff

Finished folders → tell the user publication is bazos-sprava-inzeratu's job
("vlož to na bazoš" spustí ji). Do not publish from this skill even if asked
in the same breath - switch skills.
