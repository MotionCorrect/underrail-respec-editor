# Acknowledgments and reference material

This project did not start from a blank slate. The v0.0.1 beta includes credit for the head-start material used during reverse engineering and validation.

## Head-start reverse engineering

- Early mapping and notes from the prior Fable 5 exploration helped identify the first useful `global.dat` locations and shaped the initial hypothesis for attribute, skill, and feat records.
- Two supplied reference saves were used as regression fixtures for controlled comparison and verification:
  - `data/fixtures/jetski_global.dat`
  - `data/fixtures/assault_global.dat`
- Earlier chat/post context around the respec goal defined the safety model: reallocate attributes/skills, validate feat prerequisites, avoid direct cheating by default, and write clone-first saves only.

## Public reference sources

- Underrail wiki pages from Stygian Software's public MediaWiki instance were used for feat prerequisite rules and tooltip/help text.
- The crawler is in `src/underrail_respec_editor/wiki_crawler.py` and writes JSON data under `src/underrail_respec_editor/data/`.

## Legal / attribution note

This repository is an independent community tool. It is not affiliated with Stygian Software. Underrail and related game assets remain property of their respective owners.
