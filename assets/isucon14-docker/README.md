# ISUCON14 Docker dogfood（Cloud Agent / laptop）

公式 [isucon/isucon14](https://github.com/isucon/isucon14) の `development/compose-python.yml` をベースに、**`isuctl` が SSH できる薄い contest ターゲット**を足した構成です。AMI 完全再現ではありません。

## なにが立つか

| サービス | 役割 |
|---|---|
| nginx / webapp / db / matcher | ISUCON14 Python 開発 compose |
| contest-ssh (`localhost:2222`) | `isucon` ユーザー + webapp / nginx ログをマウント。`isuctl` の SSH 先 |

## 前提

- Docker（Cloud Agent では fuse-overlayfs 推奨）
- `pnpm`（初回フロントエンドビルド）
- （任意）Go 1.23+（短時間ベンチ）

## 起動

```bash
./scripts/dogfood-docker-up.sh
./scripts/dogfood-docker-loop.sh
```

`up` は `/opt/isucon14` に clone、frontend build、compose 起動、`~/.ssh/config` に `Host isucon-dogfood`、必要なら `isucon.toml` を書きます。

## 既知の差分（AMI との違い）

- TLS なし（`:8080` HTTP）
- systemd なし（deploy の restart は効かない／限定的）
- 決済モックは `host.docker.internal:12345`。ベンチはスコア未達になりやすいが、アクセスログは出る
- 公式 `Dockerfile.python` の `default-mysql-client-core=1.1.0` ピンは壊れているため、このディレクトリの Dockerfile を使う

## ダッシュボード判断

このループで `out/pack.md` +（任意）pprotein を見て、足りなければ最小 HTML、足りていれば自作ダッシュボード見送り、を決める。
