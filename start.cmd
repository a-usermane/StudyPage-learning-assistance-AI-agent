@echo off
setlocal
cd /d "%~dp0"
set "TEMP=%CD%\.cache\tmp"
set "TMP=%TEMP%"
set "PIP_CACHE_DIR=%CD%\.cache\pip"
set "npm_config_cache=%CD%\.cache\npm"
if not exist "%TEMP%" mkdir "%TEMP%"
if not exist ".venv\Scripts\python.exe" (
  echo Environment missing. Run setup.cmd first.
  if not "%STUDY_NO_PAUSE%"=="1" pause
  exit /b 1
)
".venv\Scripts\python.exe" scripts\launch.py %*
if errorlevel 1 (
  echo Startup failed. Read the error above.
  if not "%STUDY_NO_PAUSE%"=="1" pause
  exit /b 1
)
