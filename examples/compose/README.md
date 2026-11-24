# 手元 Docker Compose でループを回す

過去問をローカルの compose で動かし、`discover` から `pack` までを SSH なしで通すための見本です。中身は汎用の web / app / db / bench で、特定の年度の問題ではありません。競技ホストの Ansible inventory は変えません。

ファイル名は `isucon.example.toml` です。手元の `isucon.toml` は gitignore されるので、見本は別名で置いてあります。`project_dir` はこのファイルからの相対パスです。`local_dir`（`./work`）は、コマンドを起動したディレクトリからの相対パスです。

## 起動

```bash
# キットのルートで
isuctl provision --config examples/compose/isucon.example.toml
isuctl discover --config examples/compose/isucon.example.toml
isuctl sync-down --config examples/compose/isucon.example.toml
# work/ を編集してコミットしてから
isuctl deploy --config examples/compose/isucon.example.toml --branch HEAD
isuctl check --config examples/compose/isucon.example.toml
isuctl bootstrap --config examples/compose/isucon.example.toml
isuctl bench --config examples/compose/isucon.example.toml
isuctl pull --config examples/compose/isucon.example.toml
isuctl analyze && isuctl pack
isuctl bench-note
isuctl rollback --config examples/compose/isucon.example.toml --ref HEAD~1
```

`past-problem/` は骨格です。過去問の compose に差し替えるときは、`service` 名とログのパス、`source_dest`（Dockerfile の `COPY` 元）をその問題に合わせます。Go のバイナリはイメージのビルド時に焼かれるので、コンテナの中のソースを直してもプロセスは変わりません。`deploy` が ref を build context に置いて `docker compose build` と `up -d --wait` します。未コミットの変更はイメージに入りません。

web / db コンテナを作り直すと、`bootstrap` がコピーしたログ設定は消えます。測る前にもう一度 `bootstrap` します。

## macOS の Docker Desktop

Docker Desktop のポート転送は、macOS の somaxconn（おおよそ 128）を超える同時接続で RST を返します。公開ポート（この見本では `127.0.0.1:18080`）に対してホストから `go run` したベンチは、その上限でスコアが落ちます。ベンチは compose ネットワークの内側で走らせます。`bench` は profile `bench` の service で、通常の `up` では起動しません。`isuctl bench` が次を実行します。

```text
docker compose --profile bench run --rm --no-deps bench ./bench -target http://web
```

過去問のベンチバイナリは `past-problem/bench/` に置き、`bench_command` をその引数に合わせます。スコアの記録は今まで通り `isuctl bench-note` です。`isuctl bench` はスコアを解釈しません。

## コマンドと docker compose

| isuctl | docker compose |
| --- | --- |
| discover | 各 service で `exec`（アプリディレクトリ、nginx / Apache / MySQL / PostgreSQL） |
| sync-down | `cp service:<remote_app_dir>/.` → `local_dir` |
| deploy | `git archive` を `source_dest` へ、`build`、`up -d --wait` |
| check | `ps --format json`。web は `nginx -t` または `apachectl -t`。HTTP はネットワーク内 |
| provision | `up -d --build --wait` |
| rollback | 手元を `--ref` に reset してから deploy |
| bootstrap | nginx / Apache の LTSV を `cp` して reload。MySQL は cnf を `cp` して `restart`。PostgreSQL は `psql` で `ALTER SYSTEM SET log_min_duration_statement` と `pg_reload_conf()`。`pg_stat_statements` は `shared_preload_libraries` に入っているときだけ `CREATE EXTENSION` |
| snapshot | コンテナ内で tar し、`cp` で `out/snapshots/` へ |
| pull | ファイルは `cp`。`slow_log_via = "stderr"` のときは `logs --no-color` |
| bench | `--profile <bench_profile> run --rm --no-deps <bench_service> <bench_command>` |
| ensure-access | 何もしない（SSH の鍵配布はしない） |
| analyze / pack / bench-note | 手元のファイルだけ |

Apache の LTSV は `request_time` をマイクロ秒で出します。`bootstrap` が対象ホストの `access_time_unit` を `us` にし、`pull` が秒に直してから alp に渡します。MySQL に寄せるときは db ホストを次のようにします。

```toml
[[hosts]]
name = "db1"
host = "db"
role = ["db"]
transport = "compose"
service = "db"
db_kind = "mysql"
slow_log = "/var/log/mysql/mysql-slow.log"
slow_log_via = "file"
```

Apache のときは web ホストの `access_log` を `/var/log/apache2/access.log`（httpd なら `/var/log/httpd/access_log`）にします。
