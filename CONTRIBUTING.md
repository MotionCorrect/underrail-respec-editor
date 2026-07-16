# Contributing

Thanks for helping improve Underrail Respec Editor.

## Development setup

```bash
python -m unittest -v test_underrail_webapp.py test_next_frontend.py
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
