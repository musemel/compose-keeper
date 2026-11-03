# Changelog

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
