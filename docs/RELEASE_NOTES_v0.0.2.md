# Underrail Respec Editor v0.0.2 Beta

This beta adds a Windows portable build.

## Added

- Portable Windows folder zip built with PyInstaller.
- Bundled static Next.js UI served by the Python backend.
- Same-origin API mode, so portable users do not need Node.js or a frontend rebuild.
- Browser auto-open when launching the packaged executable.

## Changed

- Source tree organized into `src/`, `tests/`, `scripts/`, `docs/`, and `data/fixtures/`.
- CI runs on pushes to `main` and manual dispatch only; pull requests do not trigger CI/CD.

## Still beta

- Use backups and verify cloned saves in-game.
- Attribute and skill editing remains the best-tested path.
- Feat replacement is still partially mapped and not fully exposed in the Next.js UI.
- Unspent point counters are not fully mapped.

## Portable usage

1. Download `underrail-respec-editor-v0.0.2-windows-portable.zip`.
2. Extract the folder anywhere writable.
3. Run `underrail-respec-editor.exe`.
4. Your browser should open `http://127.0.0.1:8765`.
5. Close the terminal window to stop the local server.
