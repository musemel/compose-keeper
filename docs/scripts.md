# Lifecycle scripts / スクリプト

Every action has a runnable standard wrapper and a custom wrapper to edit:

| Action | Standard | Custom |
| --- | --- | --- |
| Stop / 停止 | `scripts/standard/stop.sh` | `scripts/custom/stop.sh` |
| Backup / 保存 | `scripts/standard/backup.sh` | `scripts/custom/backup.sh` |
| Start / 起動 | `scripts/standard/start.sh` | `scripts/custom/start.sh` |
| Restore / 復元 | `scripts/standard/restore.sh` | `scripts/custom/restore.sh` |

With no `scripts` settings, Keeper uses the same standard operations internally.
`config/keeper.custom-scripts.example.json` shows all four custom assignments.
Commands are argument arrays, run on the management host in the Compose directory.
A nonzero exit or timeout fails the operation. Keep backup and restore as a pair.

Execution order:

- Update: stop → ensure all containers stopped → backup → start → verify.
- Manual backup: stop → backup → resume only if originally running.
- Manual restore: stop → restore saved data → start saved images → verify.
- Auto rollback: stop → restore pre-update data → start previous images → verify.

Use `KEEPER_IMAGE_OVERRIDE` as the final Compose `-f` file when writing a custom
start command. It pins the exact image IDs and disables pulls. The standard start
wrapper already does this. `KEEPER_ROLLBACK=1` denotes restore/rollback execution.

Other environment variables: `KEEPER_PROJECT`, `KEEPER_COMPOSE_DIR`,
`KEEPER_DATA_PATHS` (JSON array), `KEEPER_BACKUP_DIR`, `KEEPER_TRANSACTION`,
`KEEPER_CONFIG`. Never split `KEEPER_DATA_PATHS` on spaces; parse the JSON array.

`snapshot.json` and `manifest.json` are reserved metadata filenames in the backup
directory. Custom backup scripts must create that directory and store their files
inside it. Keeper records the image IDs and the matching restore command after the
backup succeeds. Keep that restore script available while the backup exists.
Custom scripts must be safe to retry after an interrupted operation.

For logical database dumps, export while the DB is running **before** the stop
command in the custom stop script, and include the dump location in `data_paths`.
The backup step itself runs only after containers have stopped. The standard
operation copies stopped DB files with `rsync -aHAXS --numeric-ids`.

日本語: 停止・バックアップ・起動・復元の4種類すべてに標準版とカスタム版を用意しています。
カスタム版の前後に必要な処理を追記してください。終了コード0のみ成功です。
DBダンプが必要なら、DBが稼働している停止スクリプトの先頭で取得し、ダンプ先も保存対象へ含めます。
復元形式を変更する場合はバックアップ・復元の両方を変更し、保存済みバックアップ用の復元スクリプトを残してください。
