@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
set "KB_SOURCE=%~dp0"
if not defined PERSONAL_KB_HOME set "PERSONAL_KB_HOME=%LOCALAPPDATA%\PersonalKB"
set "UV_PYTHON_INSTALL_DIR=%PERSONAL_KB_HOME%\python"
set "UV_CACHE_DIR=%PERSONAL_KB_HOME%\cache\uv"
set "UV_PYTHON_DOWNLOADS=automatic"
set "UV_MANAGED_PYTHON=1"
set "PYTHONNOUSERSITE=1"
set "PYTHONHOME="
set "PYTHONPATH="
set "VIRTUAL_ENV="
set "KB_UV=%KB_SOURCE%installer\vendor\windows-x64\uv.exe"
if not exist "%KB_UV%" (
  echo ERROR: Missing required file: "%KB_UV%"
  echo This copy cannot start because its Windows launcher component is missing.
  echo Use the complete source checkout or source ZIP from codex/local-installer-preview.
  echo Keep install.cmd together with the installer folder after extracting or cloning.
  echo If the file disappeared after extraction, check your security software's quarantine history.
  echo Press any key to close this failed attempt. This does not resume installation.
  pause
  exit /b 1
)
if not exist "%KB_SOURCE%installer\bootstrap.py" (
  echo ERROR: Missing required file: "%KB_SOURCE%installer\bootstrap.py"
  echo Keep install.cmd together with the complete installer folder.
  pause
  exit /b 1
)
echo Preparing Personal KB. This window is outside WorkBuddy; leave it open until the browser appears.
"%KB_UV%" --no-config run --python 3.11.15 --no-project "%KB_SOURCE%installer\bootstrap.py" %*
set "KB_RESULT=%ERRORLEVEL%"
if not "%KB_RESULT%"=="0" (
  echo Installation or startup failed with exit code %KB_RESULT%. Read the error above.
  echo Press any key to close this failed attempt, then reopen install.cmd after fixing the issue.
  pause
)
exit /b %KB_RESULT%
