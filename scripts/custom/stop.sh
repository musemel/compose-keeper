#!/bin/sh
set -eu
SCRIPT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
# Add site-specific commands here. A nonzero exit aborts this step.
# For a logical DB dump, export it here BEFORE stopping the DB.
python3 "$SCRIPT_ROOT/default.py" stop
# Add site-specific post-step commands here.
