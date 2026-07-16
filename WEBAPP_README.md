# Underrail Visual Respec Editor

Local browser UI for the verified Underrail `global.dat` attribute/skill editor.

## Start

Preferred Next.js UI:

Double-click:

```text
C:\Git\underrail_edit\run_underrail_next_ui.cmd
```

Then open:

```text
http://127.0.0.1:3000
```

Or run manually in two terminals:

```bash
cd /c/Git/underrail_edit
python underrail_webapp.py 8765
```

```bash
cd /c/Git/underrail_edit/frontend
npm install
npm run dev
```

Legacy single-file HTML UI is still served by the Python backend at:

```text
http://127.0.0.1:8765
```

The Next.js UI is preferred because it has the persistent wiki info panel for
mouse-over details and a more Underrail-like layout.

## Workflow

1. Close Underrail or at least do not save while editing.
2. Click `List saves`, or paste a save folder/global.dat path such as
   `C:\Users\<USER>\Documents\My Games\Underrail\Saves\SaveName`
   or a `global.dat` inside a save folder.
   - The save picker can sort alphabetically, newest modified first, or oldest
     modified first. Modified time is based on the newest top-level file in the
     save folder, not just the Windows folder timestamp.
3. Set the character level.
4. Edit feats if desired, then confirm the selected feats to protect.
   - The feat editor uses the community string-replacement method described in
     the Underrail forum / Steam guide: replace the feat id string inside the
     unpacked `global.dat`, then repack.
   - This app does that locally against the cloned save only.
   - Choose a known feat from the dropdown or type a raw feat id.
5. Use the plus/minus controls for attributes and skills.
6. Watch the remaining point counters and validation panel.
   - Optional: enable `Ignore point budget` to bypass
     the attribute/skill budget check. Negative values, attribute range, skill
     cap, and feat prerequisite checks still apply.
7. Enter a new save folder name, for example `JetSki-Respec`.
8. Click `Create cloned respec save`.
9. Load the new save folder in-game.

## Safety behavior

- The source save folder is not modified.
- The app clones the whole save folder first.
- Only the clone's `global.dat` is edited.
- The underlying save writer still creates a timestamped `global.dat.<stamp>.bak` inside the clone.
- The already-verified 7 attributes and 24 skills are edited directly.
- Feat editing is supported as replacement of existing feat id records. Adding
  extra feat slots or deleting feat slots is not supported yet.
- Selected feats are also used for prerequisite warnings/errors.
- Feat prerequisites for the screenshot-known feats are cross-referenced against
  the Stygian Software wiki where available. `crawl_underrail_feats.py` crawls
  `Category:Feats` from the wiki and writes `feat_rules.json` plus
 `feat_ids.json`, and `wiki_tooltips.json`. Current crawl covers 220 feats,
 24 skills, and 7 base attributes. Example: Concussive Shots requires
 Crossbows 30, not Guns 30.

## Refresh wiki feat rules

Run:

```bash
cd /c/Git/underrail_edit
python crawl_underrail_feats.py
python -m unittest -v test_underrail_webapp.py
```

The crawler is stdlib-only and uses the official MediaWiki API. It parses the
rendered Requirements list for every page in `Category:Feats`, feat description
text from each feat infobox, and the in-game-style quote text for each skill and
base attribute page.

## Mouse-over help

The UI attaches wiki-derived mouse-over text to:

- Base attribute rows
- Skill rows
- Feat editor rows/dropdown options where the browser exposes option titles
- Feat validation checkboxes

Hover over a row/feat to read the wiki description while deciding what to
modify.

Note: requirement validation is much more complete than feat id editing. Many
internal feat ids are guessed from the wiki title; verified save ids override a
few known exceptions such as `Psi Empathy -> pe` and the current supplied-save
record for Marksman. Use the raw id field if a dropdown id is wrong.

## Unused points

The app displays remaining points as:

- attributes: `40 + floor(level / 4) - current_attribute_total`
- skills: `120 + 40 * (level - 1) - current_skill_total`

This matches the provided screenshots:

- JetSki level 12: 1 remaining attribute point, 40 remaining skill points
- Assault level 6: 0 remaining by the supplied values

If a future character has a different budget because of version/mod/story oddities, manually adjust the budget boxes before writing.
