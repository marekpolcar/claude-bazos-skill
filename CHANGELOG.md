# Changelog

## 1.0.0 (2026-07-06)

- first public release.
- skill `bazos-priprava-inzeratu`: photos or an item name in, a priced
  `prodej/<x>/` folder out: identification, photo cleanup (EXIF/GPS strip,
  orientation fix, downscale, JPEG conversion), cited price research,
  drafted `inzerat.md`.
- skill `bazos-sprava-inzeratu`: publishes, edits and deletes those folders
  through a real browser (Playwright): preview-confirm before every write,
  live category resolution, sold-outcome write-back with days-to-sell,
  interception-harness test suite.
- runtime state lives in `~/.bazos-inzerce/`, never in the repo.
