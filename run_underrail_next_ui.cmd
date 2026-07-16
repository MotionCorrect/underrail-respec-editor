@echo off
cd /d C:\Git\underrail_edit
start "Underrail Respec Python API" cmd /k python underrail_webapp.py 8765
cd /d C:\Git\underrail_edit\frontend
start "Underrail Respec Next UI" cmd /k npm run dev
start http://127.0.0.1:3000
