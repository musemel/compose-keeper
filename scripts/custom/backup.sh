#!/bin/sh
set -eu
SCRIPT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
# Add site-specific commands here. A nonzero exit aborts this step.
python3 "$SCRIPT_ROOT/default.py" backup
# Add site-specific post-step commands here.
