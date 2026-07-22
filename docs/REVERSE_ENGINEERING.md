# Reverse engineering notes

These notes summarize the save-format assumptions used by v0.0.1. They are intentionally conservative so future contributors can verify or correct them.

## Save container

Observed `global.dat` shape:

```text
24-byte header + gzip-compressed payload
```

The 24-byte header is preserved verbatim. The payload is decompressed, edited, recompressed, and written into a cloned save folder only.

## Attributes

The seven base attributes are found by length-prefixed name anchors in the decompressed payload. For each attribute name, the base and modified values are stored as little-endian int32 values shortly before the name.

Editing policy:

- edit the base value
- shift the modified value by the same delta
- reject unsafe out-of-range values

## Skills

The 24 skills are found in character-sheet order by repeated skill-class markers in the decompressed payload.

Editing policy:

- edit allocated points
- shift effective value by the same delta
- validate skill budget and level cap where possible

## Feats

Feat slot replacement is only partially mapped. v0.0.1 reads detected feat ids and validates the user-visible feat list against wiki-derived prerequisite rules. Adding or deleting feat slots is intentionally unsupported.

Known caveats:

- some internal feat ids are inferred from wiki names
- verified exceptions live in `src/underrail_respec_editor/data/feat_ids.json`
- the Next.js UI does not yet expose every legacy feat-replacement control

## Runtime mods vs save edits

Diverclaim/UnderrailMods documents runtime IL/assembly hook points for quality-of-life changes such as fast-forward, item-weight scaling, trader acceptance changes, forced restock, and throwing hit chance cap changes. Those are different from this project's `global.dat` clone-first save edits.

Current policy:

- keep runtime assembly patching separate from clone-first save editing
- expose reviewed community mod metadata for attribution and UI context
- require an explicit expert workflow with game binary backups, game-version matching, patch preview, and rollback before applying any runtime mod

Current runtime patcher status: stable click-to-patch mods are `item_weight`, `force_restock`, `traders_buy_all`, and `throwing_chance_cap` for the tested local Steam build `21973456`. The patcher uses semantic scanners rather than raw RVAs alone: property names for weight, signature/shape checks for restock and barter methods, and constant-cluster matching for throwing cap. `fastforward` remains experimental because its byte-level patch and rollback succeeded but live launch smoke testing failed.

See `docs/UNDERAIL_MODS_REVIEW.md`, `docs/RUNTIME_MOD_PATCHING.md`, and `src/underrail_respec_editor/data/community_mods.json`.

## Recommended verification workflow

1. Make a small controlled in-game change.
2. Save as a new save.
3. Diff the decompressed payloads.
4. Add/update a regression fixture or test.
5. Keep source-save writes clone-first.
