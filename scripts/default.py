#!/usr/bin/env python3
"""Optional standard hook: python3 /opt/compose-keeper/scripts/default.py ACTION."""
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from keeper import Keeper

keeper = Keeper(os.environ['KEEPER_CONFIG'])
tx = keeper.read(Path(os.environ['KEEPER_TRANSACTION']), {})
project = tx['config']
action = sys.argv[1]
if action == 'stop':
    keeper.compose(project, ['stop'])
elif action == 'backup':
    keeper.backup(project)
elif action == 'restore':
    keeper.restore(project)
elif action == 'start':
    keeper.compose(project, ['up', '-d', '--no-build', '--force-recreate'], Path(os.environ['KEEPER_IMAGE_OVERRIDE']))
else:
    raise SystemExit('Expected stop, backup, restore, or start')
