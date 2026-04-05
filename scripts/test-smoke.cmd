@echo off
setlocal
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0test-smoke.ps1" %*
exit /b %ERRORLEVEL%