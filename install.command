#!/bin/sh
# Finder entry point; all work is delegated to the quoted portable launcher.
KB_SOURCE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 1
exec /bin/sh "$KB_SOURCE/install.sh" "$@"
