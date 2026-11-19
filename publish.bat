@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PY=C:\Users\ASUS\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if not exist "%PY%" set "PY=python"

echo ==========================================
echo   Morning Brief - Upload to GitHub
echo ==========================================
echo.
echo Paste your GitHub token when asked.
echo The token will NOT be displayed or saved.
echo.

"%PY%" publish_github.py --repo morning-brief

echo.
echo ==========================================
echo   Finished. Press any key to close.
echo ==========================================
pause >nul
