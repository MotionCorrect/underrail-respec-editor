# Underrail Respec Next.js Frontend

This is the newer frontend for the local Python save-editing API.

## Run

From Git Bash or a terminal:

```bash
cd /c/Git/underrail-respec-editor
python -m underrail_respec_editor.web_app 8765
```

In a second terminal:

```bash
cd /c/Git/underrail-respec-editor/frontend
npm install
npm run dev
```

Open:

http://127.0.0.1:3000

Or on Windows run:

```text
scripts\scripts/run_underrail_next_ui.cmd
```

## Notes

- The Python backend remains the only writer for save files.
- The Next.js UI calls `http://127.0.0.1:8765` by default.
- Set `NEXT_PUBLIC_UNDERAIL_API` if the backend uses a different URL.
- Mouse-over help is shown in a persistent right-side info panel, not just native browser `title` popups.


## Static / GitHub Pages mode

The Next.js app is also exported as a static site. In hosted GitHub Pages mode it cannot run the local Python writer API, so save patching, runtime patching, save-browser paths, and full BinaryFormatter parsing remain local-app features only.

The hosted page includes a browser-only upload analyzer:

- choose a `global.dat`
- choose a save folder in Chromium-compatible browsers
- choose a `.zip` containing `global.dat`

Uploaded files stay in the browser. The static analyzer decompresses the save payload when the browser supports `DecompressionStream`, then scans for bundled item catalog paths to provide a quick inventory-weight/category estimate. It is deliberately labeled heuristic; use the local Python app for exact stack decoding and all write-capable workflows.
