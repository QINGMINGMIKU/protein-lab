@echo off
chcp 65001 >nul
title Protein Lab
cd /d "%~dp0"
echo.
echo   =====================================
echo     Protein Lab - Protein Lab Manager
echo   =====================================
echo.
echo   Starting... browser will open shortly
echo   Close this window to stop the server
echo.
if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python app.py
) else (
    python app.py
)
pause
