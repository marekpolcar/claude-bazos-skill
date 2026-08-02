# Category resolver - live procedure (NOT a hardcoded map)

Bazoš categories are read **live at runtime** so relabels/reorders don't break
the skill. `scripts/category.py` provides the parsers + fetchers; the **model**
chooses.

## Two levels

1. **Sekce (subdomain).** `fetch_sections(session)` → `parse_sections(homepage)`
   returns `[{"name","subdomain","url"}]` from the homepage nav anchors
   (`<a href="https://knihy.bazos.cz/">Knihy</a>`). Anonymous is fine. The model
   picks the best semantic match to the item.

2. **Rubrika (`<select name="category">`).** `fetch_category_options(session,
   subdomain)` loads the section's `pridat-inzerat.php` and returns
   `[{"value","label"}]`. The model picks by **label**.

## Auth gate - important

The insert form is **auth-gated**. An anonymous GET of `pridat-inzerat.php`
returns only the SMS-verification gate (`formovereni`), with **no category
select**. `fetch_category_options` detects this and raises **`GateError`**
(distinguishable), so the orchestrator can surface it and ask the user to
(re)verify - never mistake it for "this section has no categories" (§9).

## Model procedure

1. Seed with the folder's `kategorie_hint` (e.g. `Knihy (dětské) / Děti`).
2. `fetch_sections` → choose the subdomain (ambiguous, e.g. a children's book
   → `knihy` vs `deti`? → **ask the user**, remember the choice for that item).
3. `fetch_category_options(subdomain)` → choose the option whose `label` best
   matches the hint; low confidence or multiple plausible → **ask**.
4. Put the chosen `value` in `ad["category"]` and the subdomain in `ad["sekce"]`.

The preview shows `Sekce → Rubrika` + confidence. An optional short-lived cache
is fine for speed, but the list is always **re-fetched live** when in doubt.

## Charset

Fetchers decode honoring the response charset (`category._text`), sidestepping
the requests ISO-8859-1 default that would mojibake Czech diacritics when the
server omits a charset.
