@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PY=C:\Users\ASUS\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if not exist "%PY%" set "PY=python"

echo ==========================================
echo   Morning Brief - WeChat push test
echo ==========================================
echo.
echo Paste your ServerChan SendKey when asked.
echo It will NOT be displayed or saved.
echo.

"%PY%" test_push.py

echo.
echo Press any key to close.
pause >nul
