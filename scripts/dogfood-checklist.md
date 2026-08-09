# ISUCON14 ドックフーディング チェックリスト

実 ISUCON14 AMI に対する `isuctl` の手動 E2E 確認。各ステップをチェックする。

## 1. インスタンス起動

- [ ] Region: `ap-northeast-1`
- [ ] AMI: ISUCON14 公式（`ami-0e334c50145a3ee41`）または [matsuu/aws-isucon](https://github.com/matsuu/aws-isucon) の ISUCON14 イメージ
- [ ] インスタンスタイプ: **非バースト**（`c5.large` / `c6i.large` 以上）。`t3.*` は CPU クレジット枯渇で初期実装でも CODE=32（マッチング失敗）になりやすい
- [ ] セキュリティグループで自分の IP から SSH (22) を許可
- [ ] 公開 IP / DNS を `HOST` として控える

## 2. 設定初期化 + SSH アクセス

```bash
isuctl init-config --host HOST --key ~/.ssh/YOUR_KEY
isuctl ensure-access   # ubuntu の authorized_keys → isucon へコピー（AMI 既定）
```

- [ ] `isucon.toml` に `app1` ホストがある
- [ ] `ensure-access` 後に `isucon@HOST` へ入れる

## 3. discover → sync-down → snapshot → bootstrap

```bash
isuctl discover
isuctl sync-down
isuctl snapshot
isuctl bootstrap
```

- [ ] `discover` が roles / `remote_app_dir` を更新した
- [ ] `sync-down` が `./work`（または設定した `local_dir`）を埋めた
- [ ] `snapshot` がリモートに記録された
- [ ] `bootstrap` が nginx LTSV + MySQL slow を適用した

## 4. ダミー編集 → deploy

- [ ] `local_dir` 下を軽く変更（例: コメント追加）
- [ ] `isuctl deploy` が成功（sync-down の ready マーカーが必要）

```bash
isuctl deploy
```

## 5. Bench → pull → analyze → pack

競技ホスト上（同一ボックス AMI）:

```bash
# 任意: 初期実装のマッチング遅延を緩める
# sed -i 's/ISUCON_MATCHING_INTERVAL=.*/ISUCON_MATCHING_INTERVAL=0.1/' ~/env.sh
# sudo systemctl restart isuride-matcher

sudo truncate -s 0 /var/log/nginx/access.ltsv.log /var/log/mysql/mysql-slow.log
./bench run --addr 127.0.0.1:443 --target https://isuride.xiv.isucon.net \
  --payment-url http://127.0.0.1:12345 --payment-bind-port 12345
```

laptop 側:

```bash
isuctl pull
isuctl analyze
isuctl pack
isuctl bench-note --note "dogfood run"   # スコアを対話で報告（または SCORE を引数に）
```

- [ ] ベンチが完走（マッチング失敗は別途メモ）
- [ ] `out/raw/*` に LTSV アクセス + slow ログがある
- [ ] `out/analyze/*` に alp / slow 出力がある
- [ ] `out/pack.md` に見出しがある

## 6. 後片付け

- [ ] EC2 を stop または terminate
- [ ] 同じ設定で別インスタンスを使うなら古い SSH host key を消す

## 任意

- [ ] laptop で pprotein + SSH トンネル — [assets/pprotein/README.md](../assets/pprotein/README.md)
- [ ] ベンチ後に `isuctl bench-note` でスコアを報告した（低下時は rollback を検討）

## 既知のハマりどころ（ISUCON14 AMI）

- **非バースト** インスタンス（`c5.large+`）を使う。`t3.*` でクレジット 0 → 初期実装でも CODE=32
- 既定 matcher は `https://isuride...` を nginx/TLS 経由で叩く。負荷時に詰まってマッチングが飢餓する
  ドックフーディング / 初期練習向けの直し方:
  `assets/isucon14/matcher-http.service` も参照。
  ```bash
  # /etc/systemd/system/isuride-matcher.service の ExecStart:
  # curl -s --max-time 1 http://127.0.0.1:8080/api/internal/matching
  # ~/env.sh の ISUCON_MATCHING_INTERVAL=0.05
  sudo systemctl daemon-reload && sudo systemctl restart isuride-matcher
  ```
- bootstrap の `alp` は `~/local/bin`（login PATH）。古い AMI では `pt-query-digest` に先立つ `apt-get update` が必要
- MySQL `long_query_time=0` は DB をログで溺れさせる。キット既定は `0.2`
