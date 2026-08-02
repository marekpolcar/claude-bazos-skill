# Ad schema - bazos-sprava-inzeratu

The input contract is a **schema**, not a file (DESIGN §5). An ad is a plain
Python dict; `scripts/ad_schema.py` defines the field set and the validation
gate. This document is the human/maintainer reference.

The folder-file shape of an ad is defined once, in
[`references/inzerat-sablona.md`](inzerat-sablona.md) - round-trip tested
against `parse_folder`.

## Fields

| Field          | Required | Source                                | Notes |
|----------------|----------|---------------------------------------|-------|
| `nadpis`       | yes      | folder / conversation                 | ad title; form field `nadpis` |
| `popis`        | yes      | folder body / conversation            | ad text; form field `popis` |
| `cena`         | see rule | folder / conversation                 | integer Kč; **never fabricated** |
| `sekce`        | yes      | category resolver                     | subdomain, e.g. `knihy` |
| `category`     | yes      | category resolver (live `<select>`)   | option `value`, e.g. `34` |
| `lokalita`     | yes      | folder / conversation                 | PSČ for the form (`lokalita_full` kept for preview) |
| `jmeno`        | yes      | **session** (`auth.get_identity`)     | form field `jmeno` |
| `telefon`      | yes      | **session** (`auth.get_identity`)     | maps to form field `telefoni` |
| `email`        | yes      | **session** (`auth.get_identity`)     | maps to form field `maili` |
| `photos`       | yes      | folder image files                    | list of paths, 1..20, JPEG or convertible |
| `cenavyber`    | optional | folder / conversation                 | e.g. `Dohodou`, `V textu`, `Zdarma` |
| `heslobazar`   | optional | generated + saved back (parse_inzerat)| ad-management password |
| `kategorie_hint` | optional | folder `- **Kategorie:**` line      | seeds the category resolver; non-schema hint |

Non-schema extras carried alongside for other stages: `lokalita_full`,
`published_url` (dedupe/renewal anchor).

A sold ad additionally carries `- **Prodáno:** <cena> Kč (<datum>[, za N dní])`
(written by `bazos.py prodano` after a confirmed delete) - the prep skill's
price research reads these lines as its own-sold-history source. The line is
deliberately not a schema field: a sold folder is history, not an ad input.

## Validation rules (`validate(ad) -> list[str]`, empty = valid)

- Every required field present and non-empty.
- **`cena`**: required **unless** `cenavyber` is `dohodou` / `v textu` / `zdarma`
  (case-insensitive). When present it must be a positive integer.
- **`photos`**: `1 <= len <= 20`; each path must exist; each must be JPEG
  (`.jpg`/`.jpeg`) **or convertible** (`.png`/`.heic`/`.heif`/`.webp`). A
  convertible format is **not** an error - the driver converts it to JPEG before
  upload (`photos_needing_conversion(ad)`); only an unsupported/unconvertible
  format fails validation. bazos accepts `.jpeg` only, max 20, auto-resized to
  1200×1200 (napoveda.php, verified 2026-07-03).

## Resolution order (model-driven, DESIGN §5)

1. **Explicit conversation input** - pasted text, a pointed-at file/folder/URL.
2. **A `prodej/<x>/` folder** if present → `parse_inzerat.parse_folder`.
3. **Derivation** - read photos, neighbouring files, optional web-lookup to
   *draft* a field. Anything derived is wrapped `{"value": X, "_derived": True}`
   and surfaces in the preview as **"odvozeno - potvrď"** (`derived_fields(ad)`).

Derived flags **persist in the folder**: an `- **Odvozeno:** cena, nadpis` meta
line in `inzerat.md` (written by bazos-priprava-inzeratu) makes `parse_folder`
wrap those fields, so a later publish session still sees them as unconfirmed -
`submit_blockers` refuses `--submit` until the user confirms. Confirming a
field = removing its name from the line (empty line → delete it). `kategorie`
on that line is an alias for `kategorie_hint`. Canonical template:
`references/inzerat-sablona.md`.

`jmeno` / `telefon` / `email` always come from the verified session
(`auth.get_identity`), never from an ad folder - a submitted `telefoni` that
differs from the verified phone risks re-triggering SMS verification.

## Never-fabricate rule

`cena` and `stav`/condition are never invented. `--yes` (batch insert) **refuses**
to run while any ad still has unconfirmed derived fields, and never applies to
`smazat`.
