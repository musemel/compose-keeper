# Compose Keeper

[English](README.en.md) · [日本語](README.ja.md)

固定した複数のComposeを順番に更新する小さな管理ツールです。
更新前バックアップ、ヘルスチェック、失敗時の自動ロールバックに対応します。
日英Web UIから起動・停止、バックアップ状態の確認、手動バックアップ・リストアができます。

## まず試す

LinuxでPython 3.11以降、Podman、podman-compose、python3-yaml、rsync、tzdataを用意し、リポジトリのルートで実行します。

```sh
python3 examples/quickstart/run.py
```

管理UIは `http://localhost:18090/`、サンプルWebは18091・18092番ポートです。
表示されたキーファイルの内容でログインします。生成データはGit管理外の `runtime/` に置きます。
[サンプルの手順](examples/quickstart/README.md)では、2つの永続化ディレクトリを保存・編集・復元できます。

## フォルダ構成

```text
keeper.py                 起動用の入口
app/                      アプリ本体
  keeper.py
  web/                    Web UIと翻訳
config/                   標準・カスタムスクリプトの設定例
deploy/                   systemdサービス定義
scripts/
  default.py              標準処理の呼び出し口
  standard/               停止・保存・起動・復元の標準スクリプト
  custom/                 4種類すべてのカスタム例
examples/quickstart/       そのまま起動できる汎用Compose例
runtime/                  生成したデータ（Git管理外）
docs/                     設定・バックアップ・スクリプトの説明
tests/                    自動テスト
```

## サービスとして導入

このリポジトリを `/opt/compose-keeper` に配置し、次のように導入します。

```sh
sudo apt-get install podman podman-compose python3 python3-yaml rsync tzdata
sudo cp /opt/compose-keeper/config/keeper.example.json /etc/compose-keeper.json
# 対象フォルダ・data_paths・backup_path・確認URLを編集
sudo install -m 600 /dev/null /etc/compose-keeper.env
python3 -c 'import secrets; print("KEEPER_ACCESS_KEY=" + secrets.token_urlsafe(24))' | sudo tee /etc/compose-keeper.env > /dev/null
sudo cp /opt/compose-keeper/deploy/compose-keeper.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now compose-keeper
```

`http://ホスト:8080/` を開き、`/etc/compose-keeper.env` の共通キーでログインします。
管理対象と同じLinuxホスト・同じPodmanユーザーで実行してください。実機検証はrootful Podmanで行っています。
管理画面は信頼できるネットワークで利用します。認証は単一の共通キー方式です。

## 永続データ・バックアップ

**複数のディレクトリと単一ファイルを混在して指定できます。**

```json
"data_paths": ["/srv/app/database", "/srv/app/uploads", "/srv/app/settings.ini"]
```

Compose全体を停止してからコピーし、数値UID/GID・権限・mtime・ACL・拡張属性・リンクを保持します。
バックアップは対象ごとに1つです。画面に保存日時・論理サイズ・ファイル数・保存先・復元可否を表示します。
「今すぐバックアップ」は元が稼働中なら保存後に再起動し、停止中なら停止を維持します。
「リストア」は確認画面の対象データを上書きし、保存済みイメージで起動・確認します。
詳細は[バックアップと復元](docs/backups.md)をご覧ください。

手動停止中の対象は定期更新でも起動しません。更新時刻とタイムゾーンはUIから保存できます。
配下コンテナは折りたたみ式で、複数のポート割り当ても表示します。

## 設定・スクリプト

- [標準設定例](config/keeper.example.json)
- [4種類すべてを指定した設定例](config/keeper.custom-scripts.example.json)
- [停止・バックアップ・起動・復元スクリプト](docs/scripts.md)
- [詳細設定](docs/configuration.ja.md)

`scripts` を省略すれば組み込みの標準処理を使います。
カスタム版は標準と同じ処理を呼び出す動くひな型なので、前後へ必要なコマンドを追加できます。

## テスト

```sh
sudo apt-get install acl attr
python3 -m unittest discover -s tests -v
```

UID/GID等のテストは隔離したroot環境で実行します。[MITライセンス](LICENSE)で商用利用できます。
