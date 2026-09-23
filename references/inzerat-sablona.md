# inzerat.md - kanonická šablona

Jediný zdroj pravdy pro formát `prodej/<x>/inzerat.md`. Píše ho
**bazos-priprava-inzeratu**, čte ho `parse_inzerat.parse_folder`, publikuje z něj
**bazos-sprava-inzeratu**. Round-trip test `tests/test_sablona.py` parsuje
kanonický příklad níže - změna šablony bez zelené na parseru neprojde.

## Kanonický příklad

```markdown
# Inzerát: Zpívánky 1 (Albi Kouzelné čtení)

- **Nadpis (Bazoš):** Albi Kouzelné čtení - Zpívánky 1, mluvicí kniha
- **Cena:** 90 Kč
- **Kategorie:** Knihy (dětské) / Děti
- **Lokalita:** Brno-Žebětín, 641 00
- **Fotky:** foto-1.jpg (přední strana), foto-2.jpg (hřbet)
- **Odvozeno:** cena

## Text inzerátu (k vložení)

Albi Kouzelné čtení - Zpívánky 1, interaktivní mluvicí kniha.

Stav: použitá, patrné opotřebení. Kniha je kompletní a plně funkční.

Osobní předání po předchozí domluvě, zaslání možné, poštovné hradí kupující.
```

## Řádky metadat

- **Nadpis (Bazoš)** - titulek inzerátu, tak jak půjde do formuláře.
- **Cena** - celé číslo v Kč. Nikdy se nevymýšlí: buď je podložená průzkumem
  (pak patří do `Odvozeno`, dokud ji uživatel nepotvrdí), nebo ji řekl uživatel,
  nebo řádek zůstane prázdný a skill se zeptá.
- **Kategorie** - nápověda pro category resolver (`sekce / rubrika`), ne finální
  hodnota; tu čte sprava živě z webu.
- **Typ** - jen v sekci Reality, a tam povinný: `Prodej` nebo `Pronájem`
  (přesně label z formuláře). Do `Kategorie` se typ nepíše - formulář ho má
  jako samostatný `<select name="type">` a bez tohoto řádku `bazos.py vlozit`
  odmítne preview. Mimo Reality řádek vynech.
- **Lokalita** - `obec, PSČ`; parser si bere PSČ, celá hodnota zůstává pro preview.
- **Fotky** - jména souborů ve složce v pořadí zveřejnění (první = titulní),
  volitelně s popiskem v závorce. Draft bez fotek („from-name" režim) sem píše
  `(čeká na fotky - TODO)`: parser pak nenajde žádný obrázek a `bazos.py
  zkontrolovat` hlásí `missing_photos: true` místo matoucí chyby.
- **Odvozeno** - čárkami oddělený seznam polí, která model odvodil a uživatel
  je ještě nepotvrdil (např. `cena, nadpis`; `kategorie` je alias pro
  `kategorie_hint`). Parser tato pole obalí derived wrapperem: preview je značí
  „odvozeno - potvrď" a `--submit` je odmítne. Potvrzené pole se ze seznamu
  smaže; prázdný seznam = smazat celý řádek.

## Řádky, které se doplňují později (do draftu nepatří)

- **Heslobazar** - heslo pro správu inzerátu; generuje a zapisuje sprava při
  prvním publikování.
- **Publikováno** - URL + datum; zapisuje sprava po úspěšném vložení.
- **Prodáno** - `<cena> Kč (<datum>[, za N dní])`; zapisuje `bazos.py prodano`
  po smazání prodaného inzerátu. Historické Prodáno řádky sousedních složek
  jsou zdroj pro cenový průzkum.

Kontaktní pole (`jmeno`, `telefon`, `email`) do složky **nikdy** nepatří -
přicházejí z ověřené session až při publikaci.

## Co do složky patří vedle inzerat.md

- Fotky - JPEG po průchodu `bazos.py fotky` (EXIF/GPS pryč, max hrana 1200 px),
  max 20. Vyřazené fotky mají příponu `.vyrazeno` a do inzerátu nikdy nejdou.
- `pruzkum.md` - cenový průzkum s citacemi (URL + cena srovnatelných inzerátů,
  nová cena, vlastní prodejní historie). Záměrně mimo inzerat.md: parser ho
  nečte a číst nemá.
