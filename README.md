# Compose Keeper

[English](README.en.md) · [日本語](README.ja.md)

A small manager for a fixed set of Compose projects: sequential image checks,
pre-update data backup, health verification and automatic rollback. Includes a
Japanese / English web UI, manual start/stop, backup status and confirmed restore.

## Try it

On Linux with Python 3.11+, Podman, podman-compose, python3-yaml, rsync and tzdata:

```sh
python3 examples/quickstart/run.py
```

The sample uses **two persistent directories**. Open the UI at
`http://localhost:18090/`; the launcher prints the login-key file location.
The demo web is on ports 18091 and 18092. Generated data stays in `runtime/`.
See the [quickstart](examples/quickstart/README.md) for the backup/edit/restore exercise.

## Repository layout

```text
keeper.py                 Stable entry point
app/                      Application implementation
  keeper.py
  web/                    UI and translations
config/                   Standard and custom-script configuration examples
deploy/                   systemd service definition
scripts/
  default.py              Standard operation dispatcher
  standard/               stop / backup / start / restore wrappers
  custom/                 Editable examples for all four actions
examples/quickstart/       Runnable generic Compose project
runtime/                  Generated local data (ignored by Git)
docs/                     Configuration, backup and script references
tests/                    Automated tests
```

## Install as a service

Place this repository in `/opt/compose-keeper`, then:

```sh
sudo apt-get install podman podman-compose python3 python3-yaml rsync tzdata
sudo cp /opt/compose-keeper/config/keeper.example.json /etc/compose-keeper.json
# Edit project directories, data_paths, backup_path and probe URLs.
sudo install -m 600 /dev/null /etc/compose-keeper.env
python3 -c 'import secrets; print("KEEPER_ACCESS_KEY=" + secrets.token_urlsafe(24))' | sudo tee /etc/compose-keeper.env > /dev/null
sudo cp /opt/compose-keeper/deploy/compose-keeper.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now compose-keeper
```

Open `http://your-host:8080/`. Use the shared key in `/etc/compose-keeper.env`.
Run on the same host/user as the managed Podman projects. Rootful Podman is tested.
Keep the management interface on a trusted network. This is shared-key authentication,
not WebAuthn or a multi-user permission system.

## Persistent data and backups

Multiple directories **and files** are supported:

```json
"data_paths": ["/srv/app/database", "/srv/app/uploads", "/srv/app/settings.ini"]
```

The project stops before copying. The standard operation preserves numeric UID/GID,
modes, mtime, ACLs, xattrs, symlinks and hardlinks using rsync. One snapshot is retained.
The UI shows availability, date, logical size, file count and destination.
**Restore** overwrites the configured data paths and starts the saved image IDs after
confirmation. It never pulls a newer image. See [backup behavior](docs/backups.md).

Manual stop prevents scheduled updates until Start succeeds. Update time and timezone
are editable in the UI and survive restarts. Child containers can be expanded/collapsed.
All reported port mappings are displayed.

## Reference

- [Standard configuration](config/keeper.example.json)
- [All four custom script assignments](config/keeper.custom-scripts.example.json)
- [Lifecycle scripts](docs/scripts.md)
- [Detailed configuration](docs/configuration.en.md)
- [Backups and restore](docs/backups.md)

## Tests

```sh
sudo apt-get install acl attr
python3 -m unittest discover -s tests -v
```

Ownership tests require a disposable root environment. The test suite uses temporary
paths. [MIT license](LICENSE); commercial use permitted. No paid subscription required.
