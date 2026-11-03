#!/bin/sh
set -eu
SCRIPT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
# Add site-specific commands here. A nonzero exit aborts this step.
# The project is stopped. Restore data before starting any containers.
python3 "$SCRIPT_ROOT/default.py" restore
# Add site-specific post-step commands here.
