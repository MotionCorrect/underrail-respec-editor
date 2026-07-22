@echo off
setlocal enabledelayedexpansion
set "ROOT=%~dp0.."
cd /d "%ROOT%"

if not exist frontend\node_modules (
  cd /d "%ROOT%\frontend"
  call npm ci || exit /b 1
) else (
  cd /d "%ROOT%\frontend"
)
call npm run build || exit /b 1

cd /d "%ROOT%"
python -m pip install --upgrade pyinstaller || exit /b 1
python -m PyInstaller --noconfirm packaging\underrail-respec-editor.spec || exit /b 1

copy /Y README.md dist\underrail-respec-editor\README.md >nul
copy /Y LICENSE dist\underrail-respec-editor\LICENSE >nul
copy /Y NOTICE.md dist\underrail-respec-editor\NOTICE.md >nul
if not exist dist\underrail-respec-editor\docs mkdir dist\underrail-respec-editor\docs
copy /Y docs\RELEASE_NOTES_v0.0.4.md dist\underrail-respec-editor\docs\RELEASE_NOTES_v0.0.4.md >nul

powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path 'dist/underrail-respec-editor' -DestinationPath 'dist/underrail-respec-editor-v0.0.4-windows-portable.zip' -Force" || exit /b 1

echo Built dist\underrail-respec-editor-v0.0.4-windows-portable.zip
