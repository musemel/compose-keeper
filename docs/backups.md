# Backups and restore / バックアップと復元

`data_paths` accepts multiple independent directories and files. Every listed path
is copied after the whole Compose project has stopped. Paths must not overlap;
the backup and state directories must be outside them.

```json
"data_paths": ["/srv/myapp/database", "/srv/myapp/uploads", "/srv/myapp/settings.ini"]
```

The UI shows the backup directory, creation time, logical data size, file count,
number of configured paths and whether the backup is usable. The standard backup
contains numbered copies (`0/`, `1/`, etc.), `manifest.json` for path mapping and
`snapshot.json` for saved image IDs, timestamp and restore information. There is
one snapshot per project. A completed new copy replaces the previous snapshot.

**Back up now** stops the project, creates a snapshot, then starts it only if it was
running before. A stopped project stays stopped. A failed backup never restores a
stale snapshot over live data.

**Restore** shows the snapshot time and affected paths before confirmation. It
stops the project, overwrites those data paths, starts the saved image IDs without
pulling newer images, and verifies health and the configured HTTP endpoint.
Files created after the backup inside the restored directories are removed.
The backup itself is kept. The original Compose files and external databases are
not restored unless they are explicitly included in your data or custom scripts.

The backend requires the selected snapshot ID and explicit confirmation. It
checks project/path mapping, saved service image IDs, image availability, file
count and logical size. These checks do not replace a cryptographic content check.
Keep a separate off-host backup if you need protection against disk loss.

An interrupted restore retains its journal and error information and can be
retried using recovery. A changed/missing snapshot blocks recovery rather than
restoring unrelated data. Existing legacy backups without `snapshot.json` are
shown, but manual restore is disabled because their original images are unknown.
Create a fresh backup to enable manual restore.

Custom backup and restore commands are paired. Keeper stores the matching restore
command with the snapshot; changing the current command does not reinterpret an
older backup. Keep the original command file available. See [scripts](scripts.md).

日本語: `data_paths` は複数のディレクトリ・ファイルに対応します。各パスは重複させず、保存先をその中へ置かないでください。
「今すぐバックアップ」は全体停止後に保存し、元が稼働中なら再起動、元が停止中なら停止を維持します。
「リストア」は確認画面の対象パスを上書きし、保存したイメージで起動・確認します。保存後に追加された対象内ファイルも削除されます。
バックアップは1つだけで、更新前のデータ・イメージの組を戻します。復元時にもバックアップは残ります。
コピーの不完全・パス不一致・イメージ不足・古いスナップショット指定では復元しません。
旧形式は元のイメージが分からないため手動復元を無効にし、新しいバックアップの作成を案内します。
中断時は記録を残して復旧を再試行できます。チェックはファイル数とサイズ等で、内容全体の暗号学的な検証ではありません。
