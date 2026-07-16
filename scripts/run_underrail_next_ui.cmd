@echo off
setlocal
set "ROOT=%~dp0.."
cd /d "%ROOT%"
set "PYTHONPATH=%ROOT%\src;%PYTHONPATH%"
start "Underrail Respec Python API" cmd /k python -m underrail_respec_editor.web_app 8765
cd /d "%ROOT%\frontend"
npm install
npm run dev
