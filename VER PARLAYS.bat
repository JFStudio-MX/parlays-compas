@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Buscando partidos, calificando lo de ayer y armando candados, joyitas y parlays...
echo.
python -X utf8 parlays.py --no-abrir %*
echo.
python -X utf8 servidor.py
