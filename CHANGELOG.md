# Changelog

## 0.4.0

- Show backup availability, creation time, logical size, file count and storage path.
- Manual backup and confirmed restore of saved data and exact image IDs, with interrupted-operation recovery.
- Validate project paths, snapshot identity, file count and size before restoring.
- Separate application, configuration, deployment, scripts, tests and documentation folders.
- Standard and custom examples for all four lifecycle actions.
- Runnable generic quickstart with two persistent directories and two HTTP bindings.

## 0.3.0

- Set daily update time and timezone in the web UI, with persisted settings.
- Collapsible child-container lists that preserve their open state during refresh.

## 0.2.0

- Start and stop Compose projects from the web UI, sharing the updater's operation lock.
- Preserve manual stop intent across restarts and skip scheduled updates while stopped.
- Show child-container names, service names, images, health, state and ports.
- Japanese / English UI with a persistent browser language preference.
- Keep Podman's detached monitor processes alive across manager restarts; cancel active commands explicitly on shutdown.

## 0.1.0

- Sequential scheduled Compose image updates with data backup and automatic rollback.
- Optional HTTP verification, native HEALTHCHECK support and retained error logs.
- Custom lifecycle scripts, shared-key authentication and interrupted-update recovery.
