@echo off
setlocal
set "ROOT=%~dp0.."
cd /d "%ROOT%"
set "PYTHONPATH=%ROOT%\src;%PYTHONPATH%"
python -m underrail_respec_editor.web_app 8765
pause
