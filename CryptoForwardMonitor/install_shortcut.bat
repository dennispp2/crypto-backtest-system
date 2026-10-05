@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_shortcut.ps1"
if errorlevel 1 (
  echo Shortcut installation failed.
  pause
  exit /b 1
)
exit /b 0
