@echo off
setlocal
set "APP_DIR=%~dp0"
set "PYTHONW=%APP_DIR%..\.venv\Scripts\pythonw.exe"
if not exist "%PYTHONW%" (
  echo Python environment not found: %PYTHONW%
  pause
  exit /b 1
)
start "Crypto Forward Monitor" /D "%APP_DIR%" "%PYTHONW%" "%APP_DIR%app.py"
exit /b 0
