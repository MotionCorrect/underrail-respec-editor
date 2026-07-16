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

## Recommended verification workflow

1. Make a small controlled in-game change.
2. Save as a new save.
3. Diff the decompressed payloads.
4. Add/update a regression fixture or test.
5. Keep source-save writes clone-first.
