# Release notes: v0.0.3

This beta release adds an explicit Runtime Mods expert workflow alongside the clone-first save respec editor.

## Highlights

- Added Runtime Mods tab with install scan, dry-run, backup-and-patch, and rollback controls.
- Added independent Mono.Cecil runtime patcher project under `runtime-patcher/`.
- Added stable click-to-patch runtime mods for the tested Steam build `21973456`:
  - `traders_buy_all`
  - `force_restock`
  - `item_weight`
  - `throwing_chance_cap`
- Updated item weight default to `0.1` after live testing showed `0.001` was too close to zero for practical play.
- Added game-running guards before live patch/rollback through both the Python/UI orchestration and the C# CLI patcher.
- Added detailed runtime patching documentation in `docs/RUNTIME_MOD_PATCHING.md`.

## Live findings

Confirmed working in-game:

- Traders buy all: traders accept all tested item categories/quantities.
- Force restock: close and reopen barter to refresh merchant stock.
- Item weight: patched successfully with default multiplier `0.1`.

Experimental / disabled:

- Fastforward: dry-run and byte-level patch/rollback work, but live launch smoke testing failed on build `21973456`. It is visible for technical follow-up but disabled in the normal UI and blocked by the C# patcher unless `--experimental` is explicitly supplied.

## Safety and rollback

Real runtime patch actions create:

```text
<Underrail install>\underrail_respec_backups\underrail.exe.<timestamp>.bak
<repo>\runtime_safety_backups\latest-save-before-runtime-patch\<timestamp>-<SaveName>
```

Dry-run creates no backups and writes no files.

Rollback creates a pre-rollback backup before restoring the selected backup. Byte-level recovery was tested against a temporary assembly copy and restored the original SHA256 exactly.

## Legal / copyright notes

This release does not include or redistribute:

- Underrail game files
- patched `underrail.exe` files
- Steam DLLs
- game artwork/audio/scripts/assets
- Diverclaim/UnderrailMods source code

Diverclaim/UnderrailMods is credited as external reference material. This repository implements its own patcher and records source links plus high-level findings only.

## Verification

Local verification performed before publishing:

```text
python -m unittest -v tests/test_underrail_webapp.py tests/test_next_frontend.py
22 tests passed

dotnet build -c Release runtime-patcher/runtime-patcher.csproj
Build succeeded

cd frontend && npm run build
Next.js build succeeded
```
