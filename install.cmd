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
  echo Installation archive is incomplete. Extract the whole ZIP, then double-click install.cmd.
  pause
  exit /b 1
)
echo Preparing Personal KB. This window is outside WorkBuddy; leave it open until the browser appears.
"%KB_UV%" --no-config run --python 3.11.15 --no-project "%KB_SOURCE%installer\bootstrap.py" %*
set "KB_RESULT=%ERRORLEVEL%"
if not "%KB_RESULT%"=="0" (
  echo Reopen install.cmd to resume after fixing the issue above.
  pause
)
exit /b %KB_RESULT%
