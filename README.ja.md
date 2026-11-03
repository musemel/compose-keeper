# Compose Keeper

[English](README.en.md) · [日本語](README.ja.md)

固定した複数のComposeフォルダを、毎日指定時刻に順番に更新する小さな管理ツールです。Podman + podman-composeに対応。共通アクセスキーでログインするWeb UIから手動実行・状態・ログ・失敗情報を確認できます。

## 動作

1. 設定順に各プロジェクトの稼働イメージIDを記録し、サービス順に `podman pull`。
2. イメージIDに変更がある場合のみ、停止 → 停止確認 → バックアップ。
3. 新イメージIDでComposeを再作成して起動。
4. 全サービスの稼働・イメージID・定義済みコンテナヘルスチェックを確認。HTTP確認はプロジェクトごとに任意で追加できます。指定回数連続して正常なら更新完了。
5. 制限時間を超えた場合、更新失敗情報とコンテナログを保存し、停止 → データ復元 → 旧イメージで再作成 → 起動確認。
6. プロセス中断時は次回起動時にトランザクション記録から復旧。復旧にも失敗した対象は更新せず、UIに復旧再試行ボタンを表示。

バックアップは対象ごとに1つです。コピー完了まで古いバックアップを保持し、成功後に入れ替えます。世代管理はしません。旧イメージを自動削除しません。

## ホストへの導入（Debian / Ubuntu）

Python 3.11以降、Podman、podman-compose、PyYAML、rsync、タイムゾーンデータを使用します。管理対象と同じLinuxホスト・同じPodmanユーザーで動かしてください。

```sh
apt-get install podman podman-compose python3 python3-yaml rsync tzdata
# このフォルダを /opt/compose-keeper に配置
cp /opt/compose-keeper/config.example.json /etc/compose-keeper.json
# /etc/compose-keeper.json の対象フォルダ・パス・URL・時刻を編集
umask 077
printf 'KEEPER_ACCESS_KEY=%s\n' "$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')" > /etc/compose-keeper.env
cp /opt/compose-keeper/compose-keeper.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now compose-keeper
```

アクセス先は `http://ホスト:8080/`。キーは `/etc/compose-keeper.env` 内にあります。認証は共通の秘密キー方式で、WebAuthnのパスキーではありません。セッションは12時間で失効し、サービス再起動でも失効します。HTTPSのリバースプロキシを使う場合は `secure_cookie: true` にします。

管理ツールはホスト上で動作させるのが標準です。管理対象のComposeに自身を含めないでください。rootless Podmanでは対象ユーザーのuser serviceとして実行し、実行ユーザーがデータの所有権を保存・復元できるようにしてください。

## 設定

`config.example.json` の `projects` に対象を追加します。変更後は管理サービスを再起動します。

| 設定 | 意味 |
| --- | --- |
| `schedule` / `timezone` | 毎日の開始時刻とタイムゾーン。起動時に当日の時刻を過ぎていれば未実行分を実行 |
| `id` | 管理上の一意なID |
| `project_name` | 既存Composeのプロジェクト名と合わせる。未指定ならid |
| `directory` / `compose_files` | Composeフォルダとファイル一覧 |
| `data_paths` | 停止中にコピーする永続データの絶対パス。ファイル・フォルダに対応 |
| `backup_path` | このプロジェクト専用バックアップフォルダ。他のファイルを置かない |
| `healthcheck` | イメージ・Composeで定義されたHEALTHCHECKの結果を待つ（既定true） |
| `web.enabled` / `web.url` | HTTP確認の有効・無効とURL。管理プロセスから到達できるURL |
| `web.status_codes` | 許可する最終HTTPステータス。既定 `[200]`、リダイレクト先まで確認 |
| `health_timeout` | 起動後に正常判定を待つ秒数。既定180 |
| `health_interval` / `healthy_samples` | 確認間隔と連続成功回数。既定5秒・3回 |
| `command_timeout` | 各外部コマンドの上限秒数。既定900 |
| `scripts` | 停止・バックアップ・起動・復元処理の差し替え |

現在のバージョンは、イメージ参照（タグ）と実際に稼働しているイメージIDで表示します。固定タグの新しいバージョン番号を自動探索する機能はありません。同じタグのイメージ差し替えを検出します。

最終更新確認時刻は確認開始時および正常完了時に記録し、最終更新時刻は更新・起動確認が成功したときのみ記録します。更新エラーは成功後も最後のエラーとして保持します。

## スクリプトの指定

省略した処理には組み込みの標準処理を使います。`scripts/default.py` に同じ標準動作を呼ぶエントリーポイントも用意しています。

```json
"scripts": {
  "stop": ["python3", "/opt/compose-keeper/scripts/default.py", "stop"],
  "backup": ["/bin/sh", "/srv/scripts/my-backup.sh"],
  "start": ["python3", "/opt/compose-keeper/scripts/default.py", "start"],
  "restore": ["/bin/sh", "/srv/scripts/my-restore.sh"]
}
```

コマンドは配列指定で、ホスト上で実行します。シェル構文を使う場合は上例のようにスクリプトファイルへ記述します。終了コード0が成功、それ以外・タイムアウトが失敗です。バックアップと復元は必ず対で指定します。

渡される環境変数:

- `KEEPER_PROJECT`: 対象ID
- `KEEPER_COMPOSE_DIR`: Composeフォルダ（作業ディレクトリもここ）
- `KEEPER_DATA_PATHS`: 永続データパスのJSON配列
- `KEEPER_BACKUP_DIR`: バックアップ先
- `KEEPER_IMAGE_OVERRIDE`: 今回起動すべきイメージIDを指定したCompose overrideファイル
- `KEEPER_TRANSACTION`: 旧・新イメージと処理段階を記録したJSON
- `KEEPER_CONFIG`: 設定ファイルの絶対パス
- `KEEPER_ROLLBACK`: 通常更新なら0、復旧時なら1

**カスタム起動スクリプトは必ず `KEEPER_IMAGE_OVERRIDE` を最後の `-f` として使用してください。** これを無視すると旧イメージへの復旧ができません。起動後に実際のイメージIDが検証されます。停止スクリプトは関連サービスを全て停止してください。バックアップ前・復元前にコンテナの停止を検証します。

バックアップ失敗時は新イメージを起動せず、旧イメージを再起動します。このとき過去のバックアップは復元しません。

## 対応範囲

- 初回時点でComposeサービスが全て稼働している構成を対象とします。初回デプロイ、buildサービス、完了して終了するマイグレーションサービス、無効なprofileサービスは対象外です。
- Linuxの標準コピーは `rsync -aHAXS --numeric-ids` を使用します。内容・パーミッション・mtime・数値UID/GID・シンボリックリンク・ACL・拡張属性・同一data_path内のハードリンクを保存します。スパースファイルはスパースとしてコピーします。メタデータ保持に失敗してrsyncが非ゼロ終了した場合は更新を中止します。
- バックアップ先のファイルシステムもACL・拡張属性等に対応している必要があります。作成時刻・ctime・atimeの完全保持、異なるdata_paths間のハードリンク同一性、ファイルシステム固有の属性は保証しません。特殊なストレージは独自スクリプトを指定してください。
- 永続データの場所は明示指定します。named volumeを使う場合は実際のマウント元を指定するか、バックアップ・復元スクリプトを指定してください。指定外データや外部DBは復元されません。
- 更新時はCompose全体を停止します。同じ永続データを他のプロジェクト・外部プロセスが書き換えない構成にしてください。
- HTTP確認を無効にし、HEALTHCHECKもない場合は、コンテナが継続稼働することだけで判定します。
- ロールバック後も同じ確認を行います。外部ネットワーク障害などで旧版も確認できない場合は `復元失敗` として停止判断を残します。旧版が起動している場合もあります。
- 手動更新と定期更新は排他です。全プロジェクトを設定順に直列処理します。
- データの直接コピーはDB等を停止して整合性を保ちます。停止時間はデータ量に依存します。

## テスト

```sh
python3 -m unittest -v test_keeper.py test_http.py test_metadata.py test_control.py test_settings.py
```

メタデータ試験には `acl` パッケージも必要です。UID/GIDの変更を検証するため、隔離したLinux環境でrootとして実行してください。

## 起動・停止とコンテナ一覧（0.2.0）

Web UIの起動・停止ボタンでCompose全体を操作できます。更新処理と排他で実行し、起動時は既存コンテナまたは記録済みのイメージIDを使います。最新イメージの取得やデータのバックアップ・復元は行いません。起動後は通常のヘルスチェックとHTTP確認を行います。

手動停止した対象は停止状態を永続記録し、起動が成功するまで定期・手動の更新確認をスキップします。更新途中の復旧が必要な対象は、復旧完了まで起動・停止もブロックします。

配下のコンテナは約10秒ごとに再取得し、名前・サービス名・イメージ・稼働状態・ヘルス状態・公開ポートを表示します。右上の言語選択で日本語・英語を切り替えられ、選択はブラウザ内に保存します。生の実行ログやプロジェクト名は翻訳しません。

管理サービス再起動時にPodmanの監視プロセスを巻き込まないsystemd設定を同梱しています。アップグレード時はサービス定義も更新してください。終了時はKeeperが実行中のコマンドだけを終了し、更新中断時は次回起動時に記録から復旧します。手動起動も既存イメージIDでコンテナを再作成します。


## 更新時刻・折りたたみ

更新時刻とタイムゾーンはWeb UIから保存できます。`state_dir/settings.json` に保存され、再起動後も維持されます。保存済みの値は初期設定ファイルより優先します。過ぎた時刻を保存した場合は翌日から、未来の時刻は当日から適用し、保存直後の意図しない更新を防ぎます。

配下コンテナは初期状態では閉じています。見出しから展開でき、定期再取得でも開閉状態を維持します。複数ポートと、同じコンテナポートへの複数の割り当ても全件表示します。
