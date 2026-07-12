@echo off
setlocal
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0audit.ps1" %*
exit /b %ERRORLEVEL%
