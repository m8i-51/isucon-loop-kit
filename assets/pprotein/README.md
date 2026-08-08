# pprotein セットアップ（競技 VPC に同居させない）

[pprotein](https://github.com/kaz/pprotein) は、ISUCON ループ中の alp / slow-query 閲覧に推奨するビューアです。このキットは専用ダッシュボードを同梱しません。**laptop** か、競技 VPC の外のマシンで動かしてください。

## どこで動かすか

| OK | NG |
|---|---|
| 自分の laptop | 競技サーバと**同じ VPC** にある監視用 EC2 |
| 自宅ラボ / 別 AWS アカウント / 別 VPC | ベンチ対象とネットワーク配置を共有するホスト |

> **注意:** 競技 VPC 内に監視用 EC2 を置かないでください。負荷や障害ドメインの共有でベンチが歪みます。観測は競技ネットの外に置き、laptop から SSH ポートフォワードで繋ぎます。

## サーバ側の前提

pprotein が意味のあるログを読む前に、リモート側のログ形式を整えます。このリポジトリから:

```bash
isuctl bootstrap
```

nginx の LTSV アクセスログ、MySQL slow query 設定、（ベストエフォートで）alp を配備します。詳細は `src/isuctl/bootstrap.py` を参照。

## pprotein の導入（laptop）

上流の手順に従ってください: [kaz/pprotein](https://github.com/kaz/pprotein)

典型フロー:

1. laptop に pprotein を clone / インストールする
2. `isuctl pull` / `isuctl analyze` で `out/` に成果物がある状態にする（または上流ドキュメントどおりリモートログを指す）

## SSH ローカルフォワード例

リモートのサービス（例: 19000）を laptop に転送する:

```bash
ssh -L 19000:127.0.0.1:19000 isucon@HOST
```

`HOST` は `isucon.toml` のアプリサーバ IP / DNS に置き換える。トンネル中は `http://127.0.0.1:19000` を開く。

複数ホストならトンネルを分けるか、ローカルポートを分ける（`19001` など）。

## 関連コマンド

```text
isuctl pull      # リモートから生ログ取得
isuctl analyze   # alp / slow 解析 → out/analyze/
isuctl pack      # Cursor 用に発見事項を束ねる
```
