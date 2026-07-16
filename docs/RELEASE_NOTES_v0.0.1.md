# Underrail Respec Editor v0.0.1 Beta

This is the first public beta release.

## What works

- Local save loading from an Underrail save folder or `global.dat`.
- Attribute and skill reallocation with budget validation.
- Wiki-backed feat prerequisite validation.
- Persistent mouse-over help in the Next.js UI for attributes, skills, and feats.
- Clone-first save writing; original save folders are not modified.

## Beta limitations

- Use backups and verify cloned saves in-game.
- Unspent point counters are not fully mapped.
- The Next.js UI does not yet expose all feat replacement controls from the legacy HTML UI.
- Adding/deleting feat slots is unsupported.
- Some internal feat ids are inferred and may require correction.

## Install/run

Download the source zip, then run:

```bash
python -m underrail_respec_editor.web_app 8765
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:3000`.
