# Underrail Respec Next.js Frontend

This is the newer frontend for the local Python save-editing API.

## Run

From Git Bash or a terminal:

```bash
cd /c/Git/underrail_edit
python underrail_webapp.py 8765
```

In a second terminal:

```bash
cd /c/Git/underrail_edit/frontend
npm install
npm run dev
```

Open:

http://127.0.0.1:3000

Or on Windows run:

```text
C:\Git\underrail_edit\run_underrail_next_ui.cmd
```

## Notes

- The Python backend remains the only writer for save files.
- The Next.js UI calls `http://127.0.0.1:8765` by default.
- Set `NEXT_PUBLIC_UNDERAIL_API` if the backend uses a different URL.
- Mouse-over help is shown in a persistent right-side info panel, not just native browser `title` popups.
