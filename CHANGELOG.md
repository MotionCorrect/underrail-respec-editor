# Changelog

## v0.0.2 - Beta

### Added

- Windows portable folder zip built with PyInstaller.
- Static-exported Next.js frontend bundled into the Python server.
- Same-origin API mode for packaged/local static UI.
- Portable launcher entrypoint that opens the browser automatically.

### Changed

- CI remains disabled for pull requests; it runs only on pushes to `main` and manual dispatch.
- Release workflow now builds source zip, Python wheel/sdist, and Windows portable zip.

## v0.0.1 - Beta

Initial open-source beta release.

### Added

- Local Python backend for reading and clone-first editing of Underrail `global.dat`.
- Visual Next.js frontend for attribute and skill respecs.
- Legacy single-file HTML UI served by the Python backend.
- Save folder listing sorted by name, newest modified, or oldest modified.
- Wiki-crawled feat prerequisite validation for 220 feats.
- Wiki-derived mouse-over help for 7 base attributes, 24 skills, and 220 feats.
- Clone-first save creation and timestamped backup creation.
- Regression tests using sample fixture saves.
- GitHub Actions CI and tag-based release artifact workflow.

### Known beta limitations

- Feat replacement editing is not fully ported to the Next.js frontend.
- Adding/deleting feat slots is unsupported.
- Internal feat ids are partly inferred and may be wrong for some feats.
- Unspent point counters are not fully mapped.
- Windows-focused workflow.
