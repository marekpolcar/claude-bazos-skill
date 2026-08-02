# claude-bazos-skill

Sdílitelný [Claude Code](https://claude.com/claude-code) plugin, který z hromady
fotek udělá živé inzeráty na bazos.cz. Dvě dovednosti, které na sebe navazují:

- **bazos-priprava-inzeratu** připraví prodejní složky: identifikuje věc z fotek
  nebo podle názvu, očistí fotky (EXIF/GPS pryč, zmenšení, JPEG), udělá cenový
  průzkum s odkazy na srovnatelné inzeráty a napíše text inzerátu. Nic
  nepublikuje.
- **bazos-sprava-inzeratu** připravené složky publikuje, upravuje a maže. Řídí
  opravdový prohlížeč (Playwright), takže projde i JavaScriptovým nahráváním
  fotek. Po smazání se zeptá, jestli se věc prodala a za kolik, a zapíše to
  zpátky do složky. Příští ocenění podobné věci už tuhle historii zná.

Typický průběh: řekneš "chci prodat tyhle knížky" a ukážeš složku fotek.
Skill připraví `prodej/<x>/` složky s cenami a texty, ty je zkontroluješ a
potvrdíš odvozená pole, pak řekneš "vlož to na bazoš" a druhý skill je
publikuje. Ceny se nikdy nevymýšlí: každý návrh cituje zdroje (srovnatelné
inzeráty, nová cena, vlastní prodejní historie) a čeká na tvoje potvrzení.

## Bezpečnost a soukromí

- **Preview a potvrzení jako default.** Nic se nezveřejní ani nesmaže potichu.
- **Fotky bez metadat.** Před publikací se z fotek odstraní EXIF včetně GPS
  (domácí fotky nesou polohu). Fotka, u které se to nepovede, do inzerátu
  nejde.
- **Žádná osobní data v repu.** Session a stav žijí v `~/.bazos-inzerce/`,
  nikdy v pluginu. Hlídá to test, který skenuje fixtures na telefony a e-maily.

## Instalace

Přes `marekpolcar` marketplace:

```
/plugin marketplace add marekpolcar/claude-plugins
/plugin install claude-bazos-skill@marekpolcar
```

Runtime závislosti (mimo Claude Code); Homebrew Python je PEP 668, proto venv:

```bash
python3 -m venv ~/.bazos-inzerce/venv
~/.bazos-inzerce/venv/bin/python3 -m pip install -r requirements.txt
~/.bazos-inzerce/venv/bin/python3 -m playwright install chromium
```

## První spuštění

Bazoš „přihlášení" = ověřené zařízení v cookies (platí ~1 rok), ne účet.

1. Pokud ještě nemáš ověřené zařízení: v běžném prohlížeči přidej inzerát a
   proveď **SMS ověření** (možná i jednorázová platba 1 Kč z účtu, viz
   `podminky.php`).
2. Při prvním příkazu skill vytáhne cookies z Chrome. macOS Keychain se zeptá,
   klikni **Allow** (ne *Always Allow*, to by dalo trvalý přístup ke všem
   cookies). Session se uloží do `~/.bazos-inzerce/state.json` (0600).
3. Pokud extrakce selže (jiný prohlížeč / ne-mac), skill otevře **jednorázový
   headed login**.

Příprava inzerátů (první skill) nepotřebuje session ani přihlášení: fotky a
kontrola složek běží čistě offline, cenový průzkum čte veřejný web bez
přihlášení.

## Podpora platforem

Vyvíjeno a testováno na macOS. Jinde by mělo běžet (Python i Playwright jsou
multiplatformní), ale s dvěma rozdíly:

- **Windows:** vytažení cookies z Chromu nefunguje. Chrome od verze 127
  (červenec 2024) šifruje cookies vazbou na aplikaci a browser_cookie3 je
  neumí dešifrovat. První spuštění tedy skončí u jednorázového headed
  loginu; session pak žije v `~/.bazos-inzerce/state.json` a Chrome už
  není potřeba.
- **HEIC fotky (iPhone):** konvertují se přes `sips`, což je jen macOS.
  Jinde se HEIC fotka vyřadí místo konverze; JPEG/PNG/WebP fungují všude.

Na Linuxu by extrakce cookies přes keyring fungovat měla, ale netestoval
jsem to.

## Vývoj / testy

```bash
claude --plugin-dir ~/marekpolcar/claude-bazos-skill   # /reload-plugins po změně
~/.bazos-inzerce/venv/bin/python3 -m pytest                 # offline suite (green)
~/.bazos-inzerce/venv/bin/python3 -m pytest -m live         # live (nutná ověřená session)
```

`pytest` je jen dev závislost (ne pro běh skillů). Offline testy (parsery,
schéma, fotky, šablona, scrub-hygiena) nepotřebují nic živého; testy značené
`live` řídí opravdový web pod interceptačním harnessem (každý zápis je
odchycen, nic se neodešle).

`~/.bazos-inzerce/` je živá session. Zvaž `tmutil addexclusion
~/.bazos-inzerce` (ať neteče do Time Machine).

## Údržba (když se web změní)

1. `bazos.py canary --sekce <s>` pojmenuje, co se v insert formu rozešlo.
2. Driver testy běží proti **živé** stránce a jsou self-updating: `pytest -m
   live` ukáže, co se rozbilo (selektory, honeypot, files[]). Oprav a spusť
   znovu.
3. Jen když se rozbily **čisté parsery**, znovu naber fixtures:
   `capture_fixtures.py`, pak `scrub_fixtures.py`, pak
   `pytest tests/test_fixture_hygiene.py`.
4. Formát `prodej/<x>/inzerat.md` je popsaný v `references/inzerat-sablona.md`
   a přibitý round-trip testem k parseru.

## Sdílení bez úniku dat

Zkopíruj složku, žádná osobní data s ní necestují (raw captures a session žijí
v `~/.bazos-inzerce/`). Ověřuje to `tests/test_fixture_hygiene.py`: skenuje
fixtures na telefony/e-maily a padne na čemkoli mimo fake identitu.

## Licence

MIT, viz [`LICENSE`](LICENSE).
