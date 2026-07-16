# Contributing

Thanks for helping improve Underrail Respec Editor.

## Development setup

```bash
python -m unittest -v tests/test_underrail_webapp.py tests/test_next_frontend.py
cd frontend
npm ci
npm run build
```

## Pull request checklist

- Keep save editing clone-first and local-only.
- Add or update tests for parser/writer/validation changes.
- Do not commit personal save folders, local environment files, logs, generated screenshots, `.next`, or `node_modules`.
- Avoid hard-coded user names or machine-specific paths. Use `C:\Users\<USER>\...` in docs/examples.
- Document beta limitations clearly when adding partially mapped save features.

## Reverse engineering notes

Prefer small controlled save diffs and regression fixtures. If adding support for new save fields, include:

- what changed in-game
- before/after fixture or documented offset evidence
- safety checks that refuse to guess when records do not match expected structure

## Reference credit

If you add reverse-engineering detail based on community notes, prior agent work, posts, or supplied saves, update `docs/ACKNOWLEDGMENTS.md` and `docs/REVERSE_ENGINEERING.md` so the source of the head start is visible.
