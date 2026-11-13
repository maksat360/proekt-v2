@echo off
chcp 65001 >nul
cd /d "%~dp0"
python server.py --host 0.0.0.0
pause
