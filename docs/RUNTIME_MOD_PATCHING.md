# Runtime Mods: click-to-patch guide and technical notes

This document describes the Underrail runtime mod patcher included with the local respec editor.

The short version for players:

1. Close Underrail.
2. Open the local UI.
3. Go to `Runtime mods - expert live patch tab`.
4. Click `Scan install`.
5. Select the stable mods you want.
6. Click `Dry-run selected`.
7. If the dry-run reports exactly the expected targets, click `Backup and patch selected`.
8. Launch Underrail.
9. If anything is wrong, close Underrail and click rollback using the backup path shown by the UI.

Do not patch or roll back while Underrail is running.

## What is included

Stable click-to-patch mods for the tested Steam build:

| Mod | Status | Live-test result | Current default |
| --- | --- | --- | --- |
| `traders_buy_all` | stable | Working. Traders buy categories/quantities they normally refuse. | enabled by selection |
| `force_restock` | stable | Working. Close and reopen barter to refresh restock behavior. | enabled by selection |
| `item_weight` | stable | Working after increasing multiplier. | `0.1` |
| `throwing_chance_cap` | stable but less useful | Patches the throwing hit chance cap constants. | `0.99` cap |
| `fastforward` | experimental only | Byte-level patch/rollback worked, but live launch smoke testing failed on build `21973456`. Do not include in the stable patch set yet. | disabled |

## What is not included

This repository does not include or redistribute:

- Underrail game files
- patched `underrail.exe` files
- DLLs from the game install
- third-party mod source code from Diverclaim/UnderrailMods
- copyrighted art, audio, scripts, or other game assets

The runtime patcher uses local code written in this repository plus Mono.Cecil to edit the user's already-installed local game assembly. Public modding notes are credited and summarized, but not vendored.

## Safety model

Runtime patching is separate from save editing.

Save editing:

- modifies cloned save folders only
- leaves the source save untouched
- edits `global.dat` in the clone

Runtime modding:

- modifies the installed game assembly `underrail.exe`
- requires Underrail to be closed
- creates a game-assembly backup before every real write
- creates a latest-save backup before every real write
- supports rollback to the exact backup file

Backups created by a real runtime patch:

```text
<Underrail install>\underrail_respec_backups\underrail.exe.<timestamp>.bak
<repo>\runtime_safety_backups\latest-save-before-runtime-patch\<timestamp>-<SaveName>
```

Dry-run behavior:

- no file writes
- no save backup
- no assembly backup
- validates target discovery only

Rollback behavior:

- copies the selected backup over the live assembly
- creates a pre-rollback backup first, so even rollback is reversible

## Verified recovery behavior

A full all-mod recovery test was run against a temporary copy of the original assembly, not the live game file.

Original test assembly hash:

```text
c76248ff1082ce852fbcec25349cd2e15a80696bcee3f1b7e1d74bb19daa8a7c
```

Dry-run all mods:

```text
DRY-RUN: would patch mods [throwing_chance_cap,item_weight,force_restock,traders_buy_all,fastforward]
```

Hash after dry-run was unchanged:

```text
c76248ff1082ce852fbcec25349cd2e15a80696bcee3f1b7e1d74bb19daa8a7c
```

Actual patch all mods on the temporary assembly changed:

```text
throwing_chance_cap: 3 IL changes
item_weight: 4 IL changes
force_restock: 1 IL change
traders_buy_all: 3 IL changes
fastforward: 1 IL change
```

Patched temporary assembly hash:

```text
21f58d43da770574113bf7fa18cd8eccf4f6062a28bcf22166584153baf21936
```

The patcher-created backup matched the original hash exactly, and rollback restored the temporary assembly back to the original hash exactly.

This proves byte-level recovery works. It does not prove every IL patch is runtime-safe. Fastforward is the example: it patched and rolled back correctly, but failed launch smoke testing, so it remains experimental.

## Tested local game version

Validated install:

```text
Steam app id: 250520
Steam build id: 21973456
Assembly: underrail.exe
Original SHA256: c76248ff1082ce852fbcec25349cd2e15a80696bcee3f1b7e1d74bb19daa8a7c
```

Obfuscated method names can change when Underrail updates. The patcher therefore uses semantic scanners rather than blindly trusting one old obfuscated name.

## Targeting strategy

The design goal is strict enough to avoid false positives, but flexible enough to survive routine obfuscation/name changes.

Each mod has two kinds of anchors:

1. Stable semantic anchors
   - property names such as `Weight` and `SingleItemWeight`
   - method signatures such as a merchant restock method taking a boolean
   - constant clusters such as repeated throwing `0.9` cap constants near related combat constants
   - UI/barter behavior shape

2. Build-specific observations
   - current obfuscated type/method names
   - RVAs
   - exact target counts

The build-specific names help diagnose the current build but should not be the only reason to patch. If a future build changes names but preserves the semantic shape, the scanner should still be adaptable.

## Current adapted targets

### `throwing_chance_cap`

Purpose: change the hard cap for throwing hit chance.

Current target on build `21973456`:

```text
System.Double[] euf::a(efk,System.Int32,System.Double,System.Double)
RVA before live patch: 4012808
```

Scanner requirements:

- method has a body
- not a constructor
- return type is `System.Double[]`
- at least four parameters
- at least three `ldc.r8 0.9` constants
- nearby `0.15`, `0.4`, `0.6`, and `0.8` constants

False positive avoided:

```text
System.Void as3::.cctor()
```

It had a similar constant cluster but was a static constructor / data initializer, not the throwing calculation.

Patch behavior:

- replace three `0.9` constants with selected cap
- default cap: `0.99`

### `item_weight`

Purpose: reduce item weight without editing saves.

Current targets on build `21973456`:

```text
coh.Weight getter
coh.SingleItemWeight getter
```

Observed method names before patch:

```text
System.Double coh::f()
System.Double coh::l()
```

Scanner requirements:

- type has properties named `Weight` and `SingleItemWeight`
- both getters return `System.Double`
- both getters have bodies
- exactly two getter targets are found

Patch behavior:

- insert `ldc.r8 <multiplier>` + `mul` before each return
- affects both stacked-item total weight and single-item weight
- current default multiplier: `0.1`

Live finding:

- `0.001` was too aggressive and made weight appear effectively zero
- `0.1` is the safer default for continued testing

### `force_restock`

Purpose: make merchants restock when barter is reopened.

Current target on build `21973456`:

```text
System.Void dvp::aqc(System.Boolean)
```

Scanner requirements:

- exactly one method with the current restock signature is found
- method has one boolean parameter

Patch behavior:

- at method entry, set the boolean argument to `true`

Live finding:

- working behavior is close/reopen barter to restock
- there is no new button or UI in-game

### `traders_buy_all`

Purpose: make traders accept all item types/quantities.

Current targets on build `21973456`:

```text
System.Boolean b6o::aeg(coh)
System.Void b6o::e()
System.Boolean b6o::c()
```

Scanner requirements:

- current barter type found
- exactly three barter restriction/listing targets found
- boolean restriction methods and one void listing method match expected shapes

Patch behavior:

- short-circuit restriction/listing behavior so traders buy everything

Live finding:

- confirmed working in-game

### `fastforward`

Purpose: increase game speed while a hotkey is held.

Current target on build `21973456`:

```text
System.Void e6d::.ctor(Microsoft.Xna.Framework.GameTime,Microsoft.Xna.Framework.Input.MouseState,Microsoft.Xna.Framework.Input.KeyboardState)
```

Implemented experiment:

- inject `UnderrailRespecRuntimeMods.ApplyFastforward(GameTime)`
- route the input wrapper's `GameTime` assignment through the helper
- return original `GameTime` normally
- return a new `GameTime` with elapsed ticks multiplied by `10` while virtual key `192` / tilde is held

Status:

- dry-run passed
- byte-level patch/rollback passed
- live launch smoke test failed
- not part of the stable default patch set

Future work:

- debug the injected helper's runtime compatibility
- inspect game logs or attach a debugger during startup failure
- consider a smaller patch point that modifies elapsed time before construction rather than injecting a new helper type
- the C# patcher refuses `fastforward` unless `--experimental` is supplied, and the normal UI disables its checkbox

## Non-technical troubleshooting

If the game does not start after patching:

1. Do not panic.
2. Close any remaining Underrail process.
3. Open the Runtime Mods tab.
4. Use rollback with the most recent `underrail.exe.<timestamp>.bak` shown by the patch result.
5. Launch again.
6. Re-apply one stable mod at a time.

If a patch button says it cannot find a target:

- the game may have updated
- the assembly may already be patched
- the scanner may need a new version-specific adaptation
- do not force the patch manually

If item weight is too low or too high:

- close Underrail
- roll back to the prior backup
- patch again with a different weight multiplier
- lower multiplier = lighter items
- higher multiplier = closer to vanilla weight

Useful defaults:

```text
0.1   = 10% normal item weight
0.25  = 25% normal item weight
0.5   = 50% normal item weight
1.0   = vanilla item weight
```

## Developer verification commands

```bash
dotnet build -c Release runtime-patcher/runtime-patcher.csproj
python -m unittest -v tests/test_underrail_webapp.py tests/test_next_frontend.py
cd frontend && npm run build
```

Runtime dry-run example:

```bash
dotnet run -c Release --project runtime-patcher/runtime-patcher.csproj -- \
  patch --game-dir "H:\SteamLibrary\steamapps\common\Underrail" \
  --mods item_weight,force_restock,traders_buy_all \
  --weight-multiplier 0.1 \
  --dry-run
```

Stable live patch example:

```bash
dotnet run -c Release --project runtime-patcher/runtime-patcher.csproj -- \
  patch --game-dir "H:\SteamLibrary\steamapps\common\Underrail" \
  --mods item_weight,force_restock,traders_buy_all \
  --weight-multiplier 0.1
```

Do not include `fastforward` in a stable live patch until the launch failure is fixed.

Experimental fastforward dry-run for developers only:

```bash
dotnet run -c Release --project runtime-patcher/runtime-patcher.csproj -- \
  patch --game-dir "H:\SteamLibrary\steamapps\common\Underrail" \
  --mods fastforward \
  --experimental \
  --dry-run
```
