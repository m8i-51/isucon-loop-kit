# ISUCON Loop Kit 設計

日付: 2026-08-09  
対象: ISUCON2026 予選（2026-10-31）向け、1人チーム用準備キット

## 1. 背景とゴール

ISUCON2026 は自前 AWS アカウント上で AMI から EC2 を起動して競技する。コードの起点は手元ではなく **EC2 上の初期実装** である。

ゴールは、ボトルネック特定から改善・再計測までのループを爆速化すること。

### 成功条件

- デプロイ往復: おおむね 10 秒以内
- ベンチ後 → ボトルネック一覧表示: 1 分以内
- 「遅い URI → 候補コード / SQL」が画面または 1 ファイルに揃う
- `discover → sync-down → bootstrap → deploy → pull → analyze → pack` が過去問 1 本で通る

### 制約・前提

- チーム人数: 1 人
- 本番主言語: Python
- 準備方針: ツール寄り（過去問は犬食い検証用に最小限）
- レギュレーション上、モニタリング・開発・AI 分析は外部利用可。ベンチ中の処理委譲は不可
- GitHub Actions 本格 CI は主経路にしない（遅い）

## 2. 全体構成

```text
[手元 Mac]
  ├─ isuctl (CLI) …… discover / sync-down / deploy / pull / analyze / pack
  ├─ 可視化 …… pprotein（または同等の薄い閲覧層）
  └─ Cursor …… pack 成果物を読んでパッチ

        │ ssh / rsync
        ▼
[AWS EC2 × N]  ← 当日 AMI / 練習は ISUCON14 AMI
  app(Python) / nginx / MySQL など
```

### 意図的にやらないこと

- GitHub Actions 待ちの本格 CI/CD
- 多人数向けリアルタイム共有ダッシュボードの自作フルスタック
- Go 移植前提のキット
- 全過去問制覇カリキュラム
- ベンチマーカー本体の再実装
- Prometheus/Grafana など重い o11y フルセット（1 人には過剰）

## 3. コンポーネント

### 3.1 `isuctl`（CLI・本体）

Python 3.12+ で実装する。当日アプリと同じ感覚でメンテできることを優先する。

| コマンド | 役割 |
|---|---|
| `discover` | アプリ配置・言語・systemd・DB・ホスト役割を探索し `isucon.toml` を埋める |
| `sync-down` | EC2 → 手元へコード／設定／スキーマを取得（**最初の一手**） |
| `snapshot` | サーバ側の復元ポイント（tar または git） |
| `bootstrap` | alp 向け nginx ログ、slow query、Python 計測フック、権限など初手一式 |
| `deploy` | rsync 同期 → 必要なら migrate → app 再起動 |
| `pull` | access.log / slow.log / app 計測ログ / スコアメモをローカルへ |
| `analyze` | alp・pt-query-digest（または同等）を実行し `out/` に正規化 |
| `pack` | Cursor 用にボトルネック要約＋関連ファイル候補を 1 パック化 |
| `bench-note` | スコアとメモを履歴に追記 |
| `rollback` | 直前タグ／コミットへ戻して再デプロイ |

#### デプロイ方針

- 主経路: 手元で編集 → `git commit` → `isuctl deploy`
- GitHub push は任意バックアップ。必須経路にしない
- `deploy` は `sync-down` 済み（または確認フラグ）がないと動かない／初回は dry-run

### 3.2 可視化

自前の巨大ダッシュボードは作らない。

- 第一候補: **pprotein**（alp / slow query の閲覧）
- 補助: `analyze` 成果物のローカル閲覧（必要なら最小 HTML）
- 計測用サーバを競技 VPC に置く構成は避ける（envcheck / 失格リスクの先例あり）。手元または SSH トンネル前提

### 3.3 解析パック（AI 連携）

`isuctl pack` が例えば `out/pack.md` を出す。固定スキーマ:

- Top N endpoints（alp）
- Top N SQLs（digest）
- 推測されるハンドラ／クエリ呼び出し箇所（簡易 grep＋ヒューリスティック）
- `schema.sql` 抜粋
- 「次に試す仮説」テンプレ

計測結果なしの静的解析だけを主経路にしない。Cursor は pack 経由で使う。

### 3.4 設定: `isucon.toml`

```toml
[project]
name = "isucon2026"
local_dir = "./work"

[ssh]
user = "isucon"
key = "~/.ssh/isucon.pem"

[[hosts]]
name = "app1"
host = "x.x.x.x"
role = ["app", "web"]
remote_app_dir = "/home/isucon/webapp"

[[hosts]]
name = "db1"
host = "y.y.y.y"
role = ["db"]
```

`discover` / `sync-down` が基本的に自動で埋める。手修正は例外時のみ。

### 3.5 ディレクトリ構成（手元）

```text
isucon-loop-kit/     # ツール本体（本リポジトリ）
work/                # 当日／練習の問題コード（sync-down 先、git 管理）
out/                 # analyze / pack の成果物
docs/                # 設計・手順
```

## 4. 当日フロー

### 4.1 最初の 30 分

1. AMI から EC2 起動、SSH、ポータル／マニュアル確認
2. **何もいじる前に初手ベンチ**（基準スコア）
3. `discover` → `sync-down` → 手元で初回コミット
4. サーバ側 `snapshot`
5. `bootstrap`
6. 再ベンチ → `pull` → `analyze` → ホットパス確認

### 4.2 改善ループ

1. 可視化 / pack でボトルネック特定
2. 仮説を **1 つだけ**選ぶ
3. Python を手元で修正 → コミット
4. `deploy`
5. ベンチ
6. `pull` && `analyze`
7. スコア↑なら残す / ↓や破壊なら `rollback`

### 4.3 1人運用ルール

- 一度に一つの仮説
- `deploy` / `rollback` の手順を体に入れる
- AI は pack 経由。計測なしの全面書き直しは後回し
- 終盤に再起動耐性チェック（追試対策）

## 5. 検証（犬食い）

### 環境

- **ISUCON14** の公開 AMI を東京リージョンで 1 台起動
  - 公式例: `ami-0e334c50145a3ee41`（予告なく消える可能性あり）
  - 代替: [matsuu/aws-isucon](https://github.com/matsuu/aws-isucon) の ISUCON14 AMI
- 目的は高スコアではなく、キットの一連フローが通ること
- 使い終わったらインスタンス停止／削除（課金注意）

### 合格条件

`discover → sync-down → bootstrap → deploy → pull → analyze → pack` が手動なしで（または最小手作業で）完走する。

## 6. 技術スタック

| 層 | 選択 |
|---|---|
| CLI | Python 3.12+ |
| リモート操作 | SSH / rsync |
| 集計 | alp、pt-query-digest（なければ同等の自前） |
| 可視化 | pprotein（第一候補） |
| 設定 | `isucon.toml` |
| バックアップ | ローカル git + 任意 GitHub |

## 7. リスクと対策

| リスク | 対策 |
|---|---|
| sync-down 前に deploy してサーバを壊す | deploy ガード、サーバ snapshot |
| 計測基盤を競技 VPC に置いて失格 | 手元 / トンネル前提。外部処理委譲禁止を遵守 |
| ツール作り込みすぎて当日手順が未練度 | 犬食いは必須。スコア練習は後回しでよいがフロー通しは必須 |
| AMI 消失 | matsuu / 公式の代替 AMI、必要なら packer 再ビルド手順をメモ |

## 8. 実装スコープ（次フェーズ）

実装計画では概ね次の順で切る。

1. `isucon.toml` + SSH/rsync 基盤
2. `discover` / `sync-down` / `snapshot`
3. `deploy` / `rollback`
4. `bootstrap`（nginx LTSV / slow query）
5. `pull` / `analyze` / `bench-note`
6. `pack`
7. pprotein 導入手順（または最小閲覧 UI）
8. ISUCON14 AMI での犬食い検証
