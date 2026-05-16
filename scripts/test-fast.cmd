@echo off
setlocal
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0test-fast.ps1" %*
exit /b %ERRORLEVEL%
