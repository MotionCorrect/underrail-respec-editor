# Diverclaim UnderrailMods review and operationalization

Source reviewed: https://github.com/Diverclaim/UnderrailMods

Reviewed commit: `678f3e0ce253057f6f96d2155f3ff83e95e4334e`

## Summary

Diverclaim/UnderrailMods documents five Underrail quality-of-life runtime mods:

- Fastforward: temporarily increase game speed while a hotkey is held.
- Item weight: multiply item weights so carrying capacity is less restrictive.
- Traders buy all: make merchants accept all item kinds and quantities.
- Force restock: force merchant restock behavior.
- Throwing hit chance cap: change the hard cap in throwing hit chance calculations.

This repository uses those public notes as reference material only. It does not vendor Diverclaim's code and does not redistribute any Underrail files. The implementation in this project is an independent Mono.Cecil runtime patcher with scan, dry-run, backup, patch, and rollback controls.

## Architecture lesson incorporated

Underrail modifications are treated as two distinct families:

1. Save respec patches
   - target: save folders and `global.dat`
   - safety model: clone whole save folder, backup edited `global.dat`, preserve unknown bytes
   - normal user scope: yes

2. Runtime IL / assembly patches
   - target: the user's installed `underrail.exe`
   - examples: GameTime, item weight properties, merchant/barter checks, and hit-chance constants
   - safety model: explicit expert tab, game-version scan, dry-run, latest-save backup, game-binary backup, rollback
   - normal user scope: yes, but only through the separate Runtime Mods workflow

## Extracted mod catalog

A concise catalog lives at:

`src/underrail_respec_editor/data/community_mods.json`

The API exposes it through `/api/community-mods`, and analysis responses include it as `community_mods` so the UI can describe each runtime mod without bundling third-party code or assets.

## Latest installed Steam build adaptation

Validated local install:

- Steam app id: `250520`
- Steam build id from `appmanifest_250520.acf`: `21973456`
- Game folder: `H:\SteamLibrary\steamapps\common\Underrail`
- Assembly: `underrail.exe`
- Original assembly SHA256 before patching: `c76248ff1082ce852fbcec25349cd2e15a80696bcee3f1b7e1d74bb19daa8a7c`

Operationalized stable patches for this build:

- `traders_buy_all`: confirmed working in-game.
- `force_restock`: confirmed working in-game; close and reopen barter to refresh restock.
- `item_weight`: confirmed working with multiplier `0.1`; multiplier `0.001` was too close to zero for practical play.
- `throwing_chance_cap`: implemented and reversible; less useful than the merchant/weight patches.

Experimental patch:

- `fastforward`: dry-run and byte-level patch/rollback work, but live launch smoke testing failed on build `21973456`, so it is not part of the stable patch set.

## Precise but adaptable targeting strategy

The patcher should not blindly trust obfuscated names. Names like `coh`, `b6o`, `dvp`, `euf`, and `e6d` are useful diagnostics for build `21973456`, but they are not a long-term compatibility contract.

Targeting uses semantic anchors where possible:

- property names (`Weight`, `SingleItemWeight`)
- method signatures and return types
- count of expected candidates
- constant clusters near related constants
- exclusion of constructors/data initialization
- method body shape

If a future Underrail update changes obfuscated names, the next adaptation should update scanners around the same semantic anchors rather than patching raw RVAs.

## Mod-specific notes

### Throwing hit chance cap

Diverclaim's instruction was to find the throwing chance calculation containing three nearby clamp calls using max `0.9`.

On build `21973456`, a raw constant-cluster search initially found two candidates:

1. `System.Double[] euf::a(efk,System.Int32,System.Double,System.Double)` — true target
2. `System.Void as3::.cctor()` — false-positive static constructor / data initialization

The scanner was tightened to require:

- at least three `ldc.r8 0.9` constants
- nearby `0.15`, `0.4`, `0.6`, and `0.8` constants
- not a constructor
- return type `System.Double[]`
- at least four parameters

With those constraints, the unpatched latest build had exactly one high-confidence target:

```text
System.Double[] euf::a(efk,System.Int32,System.Double,System.Double)
RVA: 4012808
cap constants changed: 3
confidence: 100
```

### Item weight

Semantic targets:

- `coh.Weight` getter
- `coh.SingleItemWeight` getter

Patch behavior:

- insert a multiplier before each return in both getters
- current default: `0.1`
- `0.001` was tested and found too close to zero for normal play

### Force restock

Semantic target:

```text
System.Void dvp::aqc(System.Boolean)
```

Patch behavior:

- set the boolean restock argument to `true` at method entry

Live finding:

- working behavior is to close and reopen the barter window

### Traders buy all

Current adapted targets:

```text
System.Boolean b6o::aeg(coh)
System.Void b6o::e()
System.Boolean b6o::c()
```

Patch behavior:

- short-circuit trader restriction/listing checks

Live finding:

- confirmed working in-game

### Fastforward

Current adapted target:

```text
System.Void e6d::.ctor(Microsoft.Xna.Framework.GameTime,Microsoft.Xna.Framework.Input.MouseState,Microsoft.Xna.Framework.Input.KeyboardState)
```

Experimental implementation:

- inject `UnderrailRespecRuntimeMods.ApplyFastforward(GameTime)`
- return original `GameTime` normally
- return `GameTime` with elapsed ticks multiplied by `10` while virtual key `192` / tilde is held

Status:

- dry-run passed
- all-mod patch/rollback recovered exact original bytes
- live launch smoke test failed
- excluded from stable play patches

## Safety behavior implemented

- dry-run performs no writes
- real patch copies the latest save folder into repo-local ignored `runtime_safety_backups/`
- real patch creates a game assembly backup under `underrail_respec_backups/`
- rollback creates a pre-rollback backup before restoring the selected backup
- rollback was tested and restored the original assembly SHA256 exactly on a temporary test assembly
- live launch testing was used to separate stable patches from the experimental fastforward patch

## Attribution / license note

No license file was present in the reviewed Diverclaim/UnderrailMods snapshot. This project records attribution, source links, a high-level review, and independently implemented patching logic. It does not vendor code from that repository.

This project also does not include Underrail game files, patched `underrail.exe` files, Steam DLLs, game artwork, game audio, or other copyrighted Underrail assets.

For detailed non-technical usage instructions, recovery procedure, and future-version targeting guidance, see `docs/RUNTIME_MOD_PATCHING.md`.
