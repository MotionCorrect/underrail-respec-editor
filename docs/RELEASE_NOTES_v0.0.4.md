# Release notes: v0.0.4

This beta hotfix clarifies that the project is no longer only a respec editor and adds an explicit UI lockout for runtime mod controls while Underrail is running.

## Highlights

- Renamed README framing to **Underrail Respec & Runtime Mod Tool**.
- README now clearly documents the two separate workflows:
  - clone-first save respec editing
  - guarded runtime mod patching
- Runtime Mods tab now checks whether `underrail.exe` is running:
  - on UI load
  - every few seconds while the UI is open
  - after runtime scan
  - immediately before dry-run, patch, or rollback
- Runtime mod controls show a locked warning and disable patch controls while the game is running.
- Backend exposes `/api/runtime/status` for the UI lock state.

## Safety

This extends the existing v0.0.3 safety model. Runtime patch/rollback was already blocked in the backend and C# patcher while `underrail.exe` is running; v0.0.4 makes that safety state visible and proactive in the UI.

## Verification

Local verification performed before publishing:

```text
python -m unittest -v tests/test_underrail_webapp.py tests/test_next_frontend.py
23 tests passed

cd frontend && npm run build
Next.js build succeeded
```

## Copyright / attribution

Same as v0.0.3: this release does not include Underrail game files, patched game assemblies, Steam DLLs, game assets, screenshots, or Diverclaim/UnderrailMods source code. Diverclaim/UnderrailMods remains credited as external reference material only.
