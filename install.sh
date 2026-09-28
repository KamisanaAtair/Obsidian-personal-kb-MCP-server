#!/bin/sh
set -eu
KB_SOURCE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
KB_SYSTEM=$(uname -s)
KB_MACHINE=$(uname -m)
case "$KB_SYSTEM/$KB_MACHINE" in
  Darwin/arm64)
    KB_PLATFORM=macos-arm64
    KB_OS_MAJOR=$(sw_vers -productVersion | cut -d. -f1)
    if [ "$KB_OS_MAJOR" -lt 14 ]; then
      echo "This preview requires macOS 14 or later." >&2
      exit 1
    fi
    ;;
  *) echo "This installation preview does not support $KB_SYSTEM/$KB_MACHINE." >&2; exit 1 ;;
esac
if [ -z "${PERSONAL_KB_HOME:-}" ]; then
  if [ "$KB_SYSTEM" = Darwin ]; then
    PERSONAL_KB_HOME="$HOME/Library/Application Support/PersonalKB"
  else
    PERSONAL_KB_HOME="${XDG_DATA_HOME:-$HOME/.local/share}/PersonalKB"
  fi
fi
export PERSONAL_KB_HOME
UV_PYTHON_INSTALL_DIR="$PERSONAL_KB_HOME/python"
UV_CACHE_DIR="$PERSONAL_KB_HOME/cache/uv"
UV_PYTHON_DOWNLOADS=automatic
UV_MANAGED_PYTHON=1
PYTHONNOUSERSITE=1
export UV_PYTHON_INSTALL_DIR UV_CACHE_DIR UV_PYTHON_DOWNLOADS UV_MANAGED_PYTHON PYTHONNOUSERSITE
unset PYTHONHOME PYTHONPATH VIRTUAL_ENV
KB_UV="$KB_SOURCE/installer/vendor/$KB_PLATFORM/uv"
if [ ! -f "$KB_UV" ]; then
  echo "Installation archive is incomplete. Extract the whole ZIP before running the installer." >&2
  exit 1
fi
chmod u+x "$KB_UV"
echo "Preparing Personal KB. Leave this window open until the browser appears."
if "$KB_UV" --no-config run --python 3.11.15 --no-project "$KB_SOURCE/installer/bootstrap.py" "$@"; then
  exit 0
else
  KB_RESULT=$?
  echo "Reopen the installer to resume after fixing the issue above." >&2
  if [ -t 0 ]; then
    printf 'Press Enter to close... '
    read -r KB_UNUSED || true
  fi
  exit "$KB_RESULT"
fi
