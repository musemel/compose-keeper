# Compose Keeper

[English](README.en.md) · [日本語](README.ja.md)

A small self-hosted updater for a fixed set of Compose projects. It pulls images sequentially, stops changed stacks, backs up their persistent data, starts the new images, and restores the previous images and data when verification fails.

## Features

- Podman / podman-compose support; configurable engine and Compose commands.
- Daily scheduled checks, plus manual checks from a Japanese / English web UI.
- Start and stop each Compose project without pulling new images.
- Live child-container information: name, service, image, running state, health and published ports (refreshed approximately every 10 seconds).
- Optional HTTP probes, image HEALTHCHECK verification and a configurable startup timeout.
- One backup per project, with mode, numeric ownership, mtime, ACLs, xattrs, symlinks and hardlinks preserved using `rsync -aHAXS --numeric-ids`.
- Custom stop, backup, start and restore scripts; standard implementations included.
- Retained update/control errors and logs; interrupted update recovery.
- One shared access key; no user accounts. This is a shared secret, not WebAuthn.

## Install

Run on the same Linux host and under the same Podman user as the managed projects. Python 3.11+ is required. Rootful Podman is tested; rootless Podman requires sufficient permissions to read and restore the configured data and its numeric ownership.

```sh
sudo apt-get install podman podman-compose python3 python3-yaml rsync tzdata
# Extract this repository into /opt/compose-keeper
sudo cp /opt/compose-keeper/config.example.json /etc/compose-keeper.json
# Edit the paths, project names, schedule and probe URLs in that file.
sudo install -m 600 /dev/null /etc/compose-keeper.env
python3 -c 'import secrets; print("KEEPER_ACCESS_KEY=" + secrets.token_urlsafe(24))' | sudo tee /etc/compose-keeper.env > /dev/null
sudo cp /opt/compose-keeper/compose-keeper.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now compose-keeper
```

Open `http://your-host:8080/` and use the key in `/etc/compose-keeper.env`. For HTTPS reverse proxies, set `secure_cookie` to `true`. Keep this management interface on a trusted network. Anyone with the shared key can control the configured projects and read their logs.

## Configuration

See [config.example.json](config.example.json). Add a project to `projects`, then restart the management service. Match `project_name` to the existing Compose project name. Supply all persistent paths explicitly; unnamed or external storage is not discovered automatically.

| Field | Meaning |
| --- | --- |
| `schedule`, `timezone` | Daily local start time (`HH:MM`) and IANA timezone; a missed run is caught up on startup that day |
| `engine_command`, `compose_command` | Command argument arrays; defaults: `podman` and `podman compose` |
| `directory`, `compose_files` | Project directory and Compose file list |
| `data_paths`, `backup_path` | Absolute persistent-data paths and a dedicated backup directory |
| `healthcheck` | Verify the container's HEALTHCHECK when present; default `true` |
| `web.enabled`, `web.url`, `web.status_codes` | Optional HTTP probe and allowed final status codes; default `[200]` |
| `health_timeout`, `health_interval`, `healthy_samples` | Startup verification deadline, interval and consecutive successful samples |
| `command_timeout` | Maximum seconds per command; default 900 |
| `scripts` | Optional `stop`, `backup`, `start`, `restore` command arrays |

**Manual stop is persistent.** Scheduled and manual update checks skip manually stopped projects until Start succeeds. Start recreates containers using their existing image IDs (or the last recorded IDs) and does not pull the registry's latest image. Start/stop and updates share one global operation lock. Start/stop do not create or restore data backups.

The UI language selector works before login and is saved in local browser storage. Dates and static UI labels follow the selected language. Project names and raw command/application logs are displayed as provided.

## Custom scripts

Scripts run on the management host, in the project's directory. Configure argument arrays rather than shell command strings. Exit code zero means success. Configure custom backup and restore together.

```json
"scripts": {
  "stop": ["python3", "/opt/compose-keeper/scripts/default.py", "stop"],
  "backup": ["/bin/sh", "/srv/scripts/backup.sh"],
  "start": ["python3", "/opt/compose-keeper/scripts/default.py", "start"],
  "restore": ["/bin/sh", "/srv/scripts/restore.sh"]
}
```

Environment: `KEEPER_PROJECT`, `KEEPER_COMPOSE_DIR`, `KEEPER_DATA_PATHS` (JSON array), `KEEPER_BACKUP_DIR`, `KEEPER_IMAGE_OVERRIDE`, `KEEPER_TRANSACTION`, `KEEPER_CONFIG`, `KEEPER_ROLLBACK` (`0` or `1`).

Start scripts **must** use `KEEPER_IMAGE_OVERRIDE` as their final Compose `-f` file, including during rollback and manual starts. The running image IDs are checked after startup. Stop scripts must stop every container of the project; Keeper checks this before copying or restoring data. A failed backup aborts deployment and restarts the old images without restoring a stale backup.

## Limits

Only existing Compose projects using registry images are supported. Build services, one-shot migration services and inactive profile services are outside the initial scope. Updates track changes behind the configured image reference; they do not discover newer numbered release tags.

The entire project stops during updates. Back up all persistent paths and avoid writers outside the managed project. Named volumes require their actual host paths or custom backup/restore scripts. The backup filesystem must support the requested metadata. Creation time, ctime, atime, filesystem-specific attributes and hardlink identity across separate `data_paths` are not guaranteed.

During rollback, content is copied with `--ignore-times --delete` so same-size files and files created by the failed release are restored correctly. The old images are retained locally. An unresolved update transaction blocks further updates and manual control until recovery succeeds.

The management service should run outside the projects it controls. Docker Engine compatibility is configurable but has not been verified on a live Docker host.

## Tests

```sh
sudo apt-get install acl attr
python3 -m unittest -v test_keeper.py test_http.py test_metadata.py test_control.py test_settings.py
```

Metadata tests run as root to verify numeric ownership changes. CI runs the suite with root inside a disposable runner.

## License

[MIT](LICENSE). Commercial use is permitted under the license terms. No paid subscription is required. Provided without warranty or a support SLA.

The bundled systemd service preserves detached Podman monitors across management-service restarts. Keeper cancels its active command process groups during shutdown and recovers interrupted update transactions on the next start. Install the bundled service unit when upgrading.


## Schedule and container details

Set the daily update time and IANA timezone in the web UI. Changes are saved in
`state_dir/settings.json` and override the initial config values on restart.
Saving a time that has already passed schedules tomorrow; it does not run an update
immediately. A future time can run later today. Projects are still processed sequentially.

Child containers are collapsed by default. Expand the Containers heading to inspect
them; periodic refreshes preserve the open/closed state. All published ports and all
bindings for each port are shown, including TCP/UDP entries reported by the engine.
