# Underrail Respec Editor

Open-source local save editor for **Underrail** focused on safe character respecs rather than unrestricted cheating.

The tool reads an Underrail save folder or `global.dat`, lets you visually reallocate base attributes and skill points, validates selected feat prerequisites, and writes changes only to a cloned save folder.

> Status: **beta / v0.0.1**. Use backups. Verify cloned saves in-game before continuing a long playthrough.

## Goals

- Make Underrail character respecs less painful.
- Avoid direct cheating by default: preserve point budgets and validate feat requirements.
- Keep all save operations local; no hosted service and no telemetry.
- Provide an approachable UI with wiki-derived mouse-over help for base attributes, skills, and feats.

## Current beta limitations

Release `0.0.1` is intentionally conservative.

- Attribute and skill editing is the best-tested path.
- Save writing is clone-first: source save folders are not modified.
- Unspent point counters are not fully mapped. The UI uses target budgets; if your character has unused points, set the budget explicitly.
- Feat prerequisite validation is wiki-crawled and broad, but not perfect for every special/restricted/quest feat.
- Feat replacement support exists in the legacy Python UI/backend, but the newer Next.js frontend does not yet expose the raw feat-id replacement editor.
- Adding or deleting feat slots is not supported.
- Internal feat ids are partly inferred from wiki names; verified exceptions are overridden where known.
- This is Windows-focused because Underrail saves live under the Windows user Documents folder by default.
- The sample fixture saves are included for regression testing only.

## Repository layout

```text
.
├── src/underrail_respec_editor/
│   ├── save_tool.py             # low-level save parser/writer
│   ├── web_app.py               # local Python HTTP API + legacy HTML UI
│   ├── wiki_crawler.py          # MediaWiki crawler for feat rules/tooltips
│   └── data/                    # packaged feat rules, ids, tooltips
├── frontend/                    # Next.js UI
├── tests/                       # Python regression and frontend structure tests
├── data/fixtures/               # sample reference global.dat fixtures
├── scripts/                     # Windows launcher scripts
└── docs/                        # release notes and reverse-engineering docs
```

## Acknowledgments and references

This project had a head start from earlier reverse-engineering/reference work, including prior Fable 5 mapping notes and the supplied paired reference saves. Public wiki data is used for feat prerequisite and tooltip generation.

See:

- `docs/ACKNOWLEDGMENTS.md`
- `docs/REVERSE_ENGINEERING.md`

## Quick start for users

Prerequisites:

- Windows
- Python 3.11+ recommended
- Node.js 20+ recommended
- Underrail installed with local saves

Run both the backend and frontend from a source checkout:

```bash
scripts/run_underrail_next_ui.cmd
```

Manual backend/frontend startup:

```bash
set PYTHONPATH=%CD%\src
python -m underrail_respec_editor.web_app 8765
```

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open:

```text
http://127.0.0.1:3000
```

The legacy single-file HTML UI remains available at:

```text
http://127.0.0.1:8765
```

## Usage workflow

1. Close Underrail, or at minimum do not save while editing.
2. Open the Next.js UI at `http://127.0.0.1:3000`.
3. Click `List saves`, or paste a save folder / `global.dat` path.
4. Load the save.
5. Reallocate base attributes and skills.
6. Hover attributes, skills, and feats to read wiki help in the right-side info panel.
7. Validate the build.
8. Enter a new cloned save name.
9. Create the cloned save.
10. Load the cloned save in-game and verify before continuing.

Default save path shape:

```text
C:\Users\<USER>\Documents\My Games\Underrail\Saves\<SaveName>
```

## Safety model

- The source save folder is never written in-place.
- The app clones the entire save folder first.
- The clone's `global.dat` is edited.
- A timestamped backup of `global.dat` is created inside the clone.
- Validation blocks negative values, unsafe ranges, skill caps, point-budget violations, and known feat prerequisite breakage unless explicitly bypassed where supported.

## Development

Run backend tests:

```bash
python -m unittest -v tests/test_underrail_webapp.py tests/test_next_frontend.py
```

Build frontend:

```bash
cd frontend
npm ci
npm run build
```

Build Python package:

```bash
python -m pip install --upgrade build
python -m build
```

Run the wiki crawler:

```bash
set PYTHONPATH=%CD%\src
python -m underrail_respec_editor.wiki_crawler
```

The crawler uses the public Stygian Software MediaWiki API and regenerates JSON under `src/underrail_respec_editor/data/`.

## CI/CD

GitHub Actions workflows are included:

- `ci.yml`: Python tests and Next.js build on pushes to `main` and manual `workflow_dispatch` only. Pull requests intentionally do **not** trigger CI/CD.
- `release.yml`: creates a release artifact zip when a `v*` tag is pushed.

## Packaging / release

For release `0.0.1`, packaging is intentionally simple: a source zip with Python backend, Next.js frontend, docs, tests, and fixture data.

Create a release locally:

```bash
git tag v0.0.1
git push origin v0.0.1
```

The GitHub release workflow uploads an `underrail-respec-editor-v0.0.1.zip` artifact plus Python wheel/sdist artifacts.

## License

MIT. See `LICENSE`.

## Attribution / legal notes

- This project is an independent community tool and is not affiliated with Stygian Software.
- Underrail is owned by Stygian Software.
- Wiki-derived prerequisite and tooltip text comes from the public Underrail wiki; regenerate it with `python -m underrail_respec_editor.wiki_crawler` when needed.
