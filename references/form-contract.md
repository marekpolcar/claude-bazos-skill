# Insert form contract - bazos-sprava-inzeratu (maintainer reference)

From authed discovery (2026-07-03). The **conformance canary**
(`scripts/conformance.py`) and the live driver tests reconfirm this against
reality; treat the synthetic `tests/fixtures/insert_form.html` as encoding it,
not proving it.

## Insert form

- Page: `https://<sekce>.bazos.cz/pridat-inzerat.php` (auth-gated - anon returns
  the SMS gate `formovereni`).
- Form: `name="formpridani"`, `method=post`, `action=/insert.php`,
  `enctype=multipart/form-data`. **No CSRF token, no CAPTCHA.**

### Schema field → form field

| Schema key   | Form field     | Widget    | Notes |
|--------------|----------------|-----------|-------|
| `category`   | `category`     | `<select>`| option `value` (live-resolved) |
| `nadpis`     | `nadpis`       | input     | read live `maxlength`, don't hardcode |
| `popis`      | `popis`        | textarea  | |
| `cena`       | `cena`         | input     | integer as string |
| `cenavyber`  | `cenavyber`    | `<select>`| Dohodou / V textu / Zdarma / ... |
| `lokalita`   | `lokalita`     | input     | PSČ |
| `jmeno`      | `jmeno`        | input     | from session; prefilled - warn on mismatch |
| `telefon`    | **`telefoni`** | input     | note the rename |
| `email`      | **`maili`**    | input     | note the rename |
| `heslobazar` | `heslobazar`   | input     | ad-management password |

### Never touch

- Honeypot `sfdsfrtret` (static value `afdggfd`) - a driver that submits a
  stale/edited honeypot is a likely account flag. Driver asserts it unmodified.
- Hidden `vkm` (value `m`) - leave as-is.

### Photos (Dropzone.js)  - calibrated live 2026-07-03

- The upload widget is Dropzone's injected **`input.dz-hidden-input`** (unnamed,
  `accept=image/*`, multiple, visually hidden) - **not** a named `souborp[]`
  field. The driver `set_input_files` on `input.dz-hidden-input`.
- Each file POSTs to `/upload.php`, which returns **`200 text/html`** with a JSON
  **array of the stored filename(s)**, e.g. `["d_19f23....jpg"]`. Dropzone's success
  callback then injects one hidden `<input name="files[]" value="d_....jpg">` per
  file into `formpridani`; those are what the submit carries. **Driver waits until
  `files[]` count (non-empty) == number of photos** (poll, retry once on miss,
  then report - §9). The harness `upload_ok` mirrors this array shape.
- bazos accepts `.jpeg` only, auto-resizes. Non-JPEG inputs (HEIC/PNG/WebP) are
  converted (`sips`/Pillow) before upload, never passed through.

## Submit / success

- Submit posts to `/insert.php`. On a verified device the ad goes live
  immediately (no email activation).
- **Success is NOT a redirect to `/inzerat/<id>/`** (calibrated Task 9). bazoš
  stays on `insert.php` and shows **"Inzerát byl vložen/změněn (aktivní bude do
  10 minut)"** plus a topování upsell and your ad list. The driver confirms via
  that marker and reads the new ad's id from the listed anchors by matching the
  submitted `nadpis`. On-page error text is reported, never swallowed as success.
- **The real submit runs headed** (cheap anti-bot insurance). Tests run headless
  under the interception harness (`/insert.php` faked, never sent).

## Manage page (edit + delete)  - calibrated live 2026-07-03

`https://<sekce>.bazos.cz/smazat/<id>.php` is a **combined manage page** (title
"Vymazání/Úprava"), not a plain delete-confirm. For your own ads while logged in,
its `heslobazar` field is **pre-filled**. It carries two `<input name="administrace">`
submits - **"Upravit"** and **"Vymazat"** - both POSTing to **`/deletei2.php`**.

### Edit

- There is **no GET edit URL**: `/upravit/<id>.php` returns **404**.
- Click `administrace="Upravit"` → `deletei2.php` returns the same **`formpridani`**
  (→`/insert.php`) pre-filled with current values, plus a hidden **`idad=<id>`**.
  Saving with `idad` present **updates** the ad; without it the submit would
  **create a duplicate** (and bazoš auto-deletes the older). The driver refuses to
  save unless `idad` matches the target ad.
- Same field names as insert. Save = click the `Odeslat` submit → `/insert.php`.

### Delete  - calibrated live 2026-07-03 (real delete)

- Click `administrace="Vymazat"` → POST `/deletei2.php`, which **deletes
  immediately - there is no second confirmation step**. The result page shows
  **"Inzerát byl vymazán z našeho bazaru."** and lists your remaining ads as `<a>`
  manage links (never buttons). The driver confirms via that marker, else via
  absence from `moje-inzeraty`; it clicks no "confirm" control (the sibling ads'
  "Smazat/Upravit/Topovat" links contain "smaz" and would be a mis-click hazard).
- The pre-filled `heslobazar` is **not** re-checked for the owner's logged-in
  session (a wrong pre-fill still deleted). Never batched; always attended.
