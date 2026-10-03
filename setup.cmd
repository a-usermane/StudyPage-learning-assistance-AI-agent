@echo off
setlocal
cd /d "%~dp0"
set "TEMP=%CD%\.cache\tmp"
set "TMP=%TEMP%"
set "PIP_CACHE_DIR=%CD%\.cache\pip"
set "npm_config_cache=%CD%\.cache\npm"
if not exist "%TEMP%" mkdir "%TEMP%"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" scripts\setup_env.py
) else if exist "%USERPROFILE%\anaconda3\python.exe" (
  "%USERPROFILE%\anaconda3\python.exe" scripts\setup_env.py
) else (
  py -3 scripts\setup_env.py
)
if errorlevel 1 (
  echo Setup failed. Read the error above and run setup.cmd again.
  if not "%STUDY_NO_PAUSE%"=="1" pause
  exit /b 1
)
echo Ready. Run start.cmd to open the application.
if not "%STUDY_NO_PAUSE%"=="1" pause
