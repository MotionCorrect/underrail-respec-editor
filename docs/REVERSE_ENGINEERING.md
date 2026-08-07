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

## Game computation rules

The editor now carries a small, normalized computation-rules catalog at `src/underrail_respec_editor/data/game_rules.json`. It is not a vendored copy of any third-party builder source; it is an original JSON summary of useful game mechanics cross-checked against public references and save fixtures.

Reference sources:

- Underrail Wiki remains the preferred source for public names, descriptions, tooltip text, and prerequisite wording.
- `cannedbean29/UnderrailBuilderRemake` (https://github.com/cannedbean29/UnderrailBuilderRemake) was identified as the GitHub Pages source behind cannedbean29's Underrail builder and reviewed as a compact, computable reference for build-planner logic. The reviewed snapshot did not include a license file, so this project links and attributes it but does not copy or vendor its JavaScript source wholesale.

Useful computation facts incorporated in normalized form:

- Skill cap: `10 + 5 * level`.
- Attribute budget preview: `40 + floor(level / 4)`.
- Skill budget preview: `120 + 40 * (level - 1)`.
- Attribute-to-skill mapping for all 7 base abilities and 24 skills.
- Skill synergy percentages, e.g. `Lockpicking` receives 10% from `Mechanics` and 10% from `Traps`; `Hacking` receives 10% from `Electronics`; psi schools have 10% cross-synergies.
- Effective-skill preview formula:
  - attribute modifier is modeled as float32 `1 + (effective_attribute - 4) * 0.085` above attribute 4, or `1 + (effective_attribute - 4) * 0.1` at/below 4;
  - allocated points are multiplied by that modifier and floored;
  - synergy contributions are individually floored and capped so base component + synergies do not exceed the level skill cap;
  - flat bonuses and percent multipliers are represented as preview inputs but are not yet exhaustively reconstructed from save/equipment state.
- Derived-stat formula summaries for Health, psi pool/regen/reserve/slots, Movement Points, Initiative, Fortitude, Resolve, Detection, Trap Detection, and Carry Weight.
- Inventory item instance parsing: the player inventory container is serialized as class `IC`; `IC:I:Count` and `IC:I:<slot>` entries point at item records (`NEII`, `AI3`, `BII1`, `QSII`, `CII`, etc.). Item records expose `II:S` stack count, `II:DP` definition-provider path (`LIDP:P` or nested `IIDP:D`), and optional component quality `CII:QL`. Exact vanilla item weight is not stored in the instance record; join the parsed path against game/wiki item definition data, then calculate `stack * single_weight` and `% of known total`.

Current integration policy:

- Use `game_rules.json` for UI/API preview, audit, and future validation scaffolding.
- `analyze_target()` exposes `game_rules` and per-skill `rules_preview` data showing the computed effective value, loaded effective value, and unexplained delta.
- The save writer still preserves the loaded effective-minus-allocated delta when editing skills. It does not recompute every bonus source during writes, because feats, equipment, tattoos, temporary effects, specializations, and other modifiers are not fully proven from the save format yet.
- Full feat predicates, specialization effects, and equipment modifiers should only become hard validation/write logic after being independently normalized from wiki text, save fixtures, and controlled in-game tests.

## Feats

Feat slot replacement is only partially mapped. v0.0.1 reads detected feat ids and validates the user-visible feat list against wiki-derived prerequisite rules. Adding or deleting feat slots is intentionally unsupported.

Known caveats:

- some internal feat ids are inferred from wiki names
- verified exceptions live in `src/underrail_respec_editor/data/feat_ids.json`
- the Next.js UI does not yet expose every legacy feat-replacement control

## Faction relations and quest flags

Community references reviewed:

- Steam guide `2290895994`, "Befriend the Faceless in endgame (Edit save)" documents the practical workflow for unpacking `global.dat`, searching quest/faction-trigger names such as `global_facelessKilled`, `loc_rcshop_deadfaceless`, and `loc_railCrossing_removedFacelessForFree`, changing the serialized value after the trigger name, then repacking the save.
- Underrail Wiki `Befriend_the_Faceless` documents the high-level attitude model: access/friendliness depends on prior choices, `3+` attitude points gives the best ally result, `2-1` is friendly/limited, `0` is neutral, and less than that or certain Tchortist choices turns Faceless hostile after mindreading. It also notes Tchortist armor can make Faceless attack even when other conditions are satisfied.
- Steam discussion `458604254471272947` and `458604254471540191` corroborate the player-visible outcomes: ally/friendly grants lore/shop/supplies; checkpoint refusal without immediate attack can still be considered a hostile/failed result; helping Rail Crossing/Foundry/Core City Faceless are key positive events.
- Reddit threads `i3etov` and `ewm8yp` corroborate that players try to edit Faceless relationship after discovering late-game hostility; they discuss the `>10` Faceless-kill threshold, negative relationship penalties, and the difficulty of seeing values in unpacked `global.dat` without a structured parser.
- GOG forum thread `faceless_spoilers_dont_look_unless_youre_in_the_deep_caverns` corroborates that talking to Tchortists / ordering of Deep Caverns interactions can turn the Faceless hostile despite earlier positive actions.
- The Styg forum URLs in the Steam guide returned HTTP 403 from this environment, so their content was not directly verified here.

These references are Faceless-specific, not Camp Hathor-specific, but they confirm the important save-editing pattern: faction outcomes are represented by searchable serialized trigger/faction structures in the decompressed `global.dat` payload, and final hostility can depend on both direct relation state and quest/global trigger variables.

Observed faction-relation table shape in decompressed `global.dat`:

```text
01 <id-len> <faction-id> <id-len> <faction-id> <display-len> <display-name> ...
<target-id-len> <target-faction-id> <int32 relation-code> ff ff ff ff
```

Known player relation codes are currently inferred from paired saves, not official docs:

- `0`: likely hostile / shoot-on-sight
- `1`: neutral or limited
- `2`: friendly / non-hostile
- `3`: self/allied
- `4`: special/scripted

Camp Hathor case study:

- `SortingNightmare`: `campHathor -> player` is code `2` (`Friendly / non-hostile`).
- Latest July 23 autosave: `campHathor -> player` is code `0` (`Likely hostile`) at unpacked-payload offset `472041`.
- Latest July 23 autosave also changed `rathoundPack -> player` from `3` to `0` compared with `SortingNightmare`.

Current policy: faction relation parsing/comparison is read-only in the main UI. Any write experiment must be backup-first and clone-only.

### Area / kill marker decoding

The app now performs a read-only scan of readable serialized script keys in unpacked `global.dat` so faction-hostility inspection can show possible area-cleared / group-killed evidence alongside direct relation codes.

Observed serialized string shape for many flags:

```text
06 <record-id:int32> <string-len:byte> <ascii-key> <value/ref bytes...>
```

The byte immediately after the key is exposed as `value_byte`. For booleans it often appears as `0`/`1`; for counters or enums it may be a small byte or the first byte of a wider value. This is inspection-only.

Prefix meanings are inferred from examples and community save-editing practice:

- `loc_`: location/local script state, e.g. `loc_cvw47_allHathoriansKilled` and `loc_mushroomCoveBase_killedAllBugs`
- `frag_`: quest fragment / scripted encounter state, e.g. `frag_dun_wasteWater_killedBoss`
- `npc_`: NPC dialogue/lifecycle state, e.g. `npc_elwood_dead`
- `ch_`: Camp Hathor quest/dialogue state, e.g. `ch_killRathoundKingCompleted`
- `powSrc_`: power source / switchable object state
- `xpbl_`: Expedition DLC / Black Sea state, e.g. `xpbl_ojyc_mutiesKilled`
- `gms_`: GMS compound state, e.g. `gms_l3_allRaidersDead`
- `bulkDiscovery_`: map discovery marker
- `Event_`: timed/random event state

Initial area-id mapping is deliberately small and evidence-backed:

- `cvw41`-`cvw53`: Isaac's River, from the Underrail Wiki `Isaac's River` page. `cvw47` is therefore a map tile/location id, not random text.
- `dun_wasteWater`: Wastewater Processing Plant / mutant refuge, based on repeated save keys such as `frag_dun_wasteWater_*`.
- `mushroomCoveBase`: Mushroom Cove base, based on `loc_mushroomCoveBase_killedAllBugs`.
- `gms_l3`: GMS compound level 3, based on `gms_l3_raidersKilled` and `gms_l3_allRaidersDead`.
- `xpbl_ojyc`: Black Sea / Expedition OJYC content, inferred from `xpbl_ojyc_mutiesKilled` and related markers.
- `fls`: Foundry / Rathound King questline, inferred from `fls_ratkingKilled`.

Marker-to-faction mapping is currently a heuristic overlay, not an authoritative game database. It combines exact marker-name rules, area-level hints, and token fallbacks. Examples:

- `loc_cvw47_allHathoriansKilled` -> `campHathor` / Hathorians, because the marker explicitly names Hathorians and `cvw47` belongs to Isaac's River.
- `frag_dun_wasteWater_killedBoss` -> `dun_wasteWater` and likely mutie-related factions, because the save has `dun_wasteWater`, `dun_wasteWater_cameras`, `dun_wasteWater_slaves`, and mutant/refuge keys nearby.
- `gms_l3_raidersKilled` / `gms_l3_allRaidersDead` -> `gms_intruders` / `gms_intruders2`, because the faction table names GMS intruder groups where the marker names raiders.
- `ch_killRathoundKing*` and `fls_ratkingKilled` -> `rathoundKing` / `rathoundPack`.
- `xpbl_ojyc_mutiesKilled` -> `blackLake_muties` as a low-confidence Expedition mutie-family hint until OJYC map ids are verified.

The July 23 Camp Hathor/Isaac's River recovery saves show why this matters: even if `campHathor -> player` is restored to friendly, a key such as `loc_cvw47_allHathoriansKilled` can still represent local evidence that scripts may use to recompute hostility or keep a local group dead/hostile. If only specific map NPCs remain hostile, inspect chunk/local actor state next.

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
