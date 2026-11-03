#!/usr/bin/env python3
"""Stable command-line entry point; implementation lives in app/keeper.py."""
import sys
from app import keeper as implementation

if __name__ == '__main__':
    implementation.main()
else:
    # Preserve the public import and test patch points used by hook scripts.
    sys.modules[__name__] = implementation
