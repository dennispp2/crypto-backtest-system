@echo off
setlocal
set "APP_DIR=%~dp0"
set "PYTHON=%APP_DIR%..\.venv\Scripts\python.exe"
set "BUILD_TEMP=%TEMP%\CryptoForwardMonitorBuild"
if not exist "%PYTHON%" (
  echo Python environment not found: %PYTHON%
  pause
  exit /b 1
)
"%PYTHON%" -m pip install -r "%APP_DIR%requirements.txt"
if errorlevel 1 exit /b 1
"%PYTHON%" -m PyInstaller --noconfirm --clean --onefile --windowed --name CryptoForwardMonitor --collect-all customtkinter --exclude-module numpy --manifest "%APP_DIR%app.manifest" --add-data "%APP_DIR%assets\bitcoin_app_icon.png;assets" --icon "%APP_DIR%assets\CryptoForwardMonitor.ico" --distpath "%APP_DIR%dist" --workpath "%BUILD_TEMP%" --specpath "%BUILD_TEMP%" "%APP_DIR%app.py"
if errorlevel 1 exit /b 1
if not exist "%APP_DIR%dist\config.json" copy "%APP_DIR%config.json" "%APP_DIR%dist\config.json" >nul
copy /Y "%APP_DIR%assets\CryptoForwardMonitor.ico" "%APP_DIR%dist\CryptoForwardMonitor.ico" >nul
echo Built: %APP_DIR%dist\CryptoForwardMonitor.exe
exit /b 0
