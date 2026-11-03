# Runnable quickstart / そのまま動くサンプル

Requirements: Linux, Python 3.11+, Podman, podman-compose, python3-yaml, rsync, tzdata.

```sh
# Run from the repository root. Use the same user as your Podman installation.
python3 examples/quickstart/run.py
```

- Management UI: `http://localhost:18090/` (bound to loopback).
- Sample web: `http://localhost:18091/` and `http://localhost:18092/`.
- Login key location is printed by the launcher; it is not committed.
- Runtime data lives under `runtime/quickstart/` and is ignored by Git.
- The two persistent paths are `web/data/site/` and `web/data/config/`.
- Backup lives separately at `backups/web/`; manager state is in `state/`.

Click **Back up now**, edit `runtime/quickstart/web/data/site/index.html`, and click
**Restore**. The project stops, both directories and the saved image are restored,
then the project starts again. Restore overwrites current data; inspect the confirmation
dialog first. Try changing `data/config/default.conf` as a second path.

日本語: 上記コマンドでWebサンプルと管理UIが起動します。表示されたキーファイルの内容でログインしてください。
「今すぐバックアップ」→HTMLや設定を編集→「リストア」で、2箇所の永続データを元に戻せます。
稼働中の他のサービスやDBは使いません。既存のファイルは再実行しても上書きしません。

`--prepare-only` starts just the demo stack and writes its config, for adding it to
an existing Keeper instance. `--runtime /absolute/path` changes the generated data location.
Stop the sample with `podman compose --project-name keeper-quickstart -f runtime/quickstart/web/compose.yaml stop`.
