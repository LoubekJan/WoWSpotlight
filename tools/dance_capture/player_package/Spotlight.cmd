@echo off
setlocal
rem Use the Windows PowerShell module path even when launched from PowerShell 7.
set "PSModulePath="
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install Spotlight.ps1" %*
set "spotlightExit=%errorlevel%"
if not "%spotlightExit%"=="0" pause
exit /b %spotlightExit%
