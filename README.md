# isucon-loop-kit

ソロ向け ISUCON ループキット（`isuctl`）。

手元（laptop）から SSH / rsync で競技 EC2 を操作する薄い CLI です。競技サーバ上では動かしません。

```text
discover → sync-down → 編集 → deploy → bench → pull → analyze → pack → bench-note
```

主成果物は `out/pack.md`。Cursor / Claude Code など生成AIが読んで次の一手を出す想定で、自作ダッシュボードは作りません。人が深く掘るときは `out/analyze/*` か laptop の [pprotein](assets/pprotein/README.md)。

## 大会当日

| 役割 | やること |
| --- | --- |
| あなた | EC2・ベンチ・`bench-note`・deploy / rollback の判断 |
| 生成AI | `out/pack.md`（必要なら `out/analyze/*`）と `work/` を読んで、仮説 **1 つ**だけ直す |

**最初の30分**

1. EC2 起動、ポータル確認
2. 何もいじらず初手ベンチ → `isuctl bench-note`（基準点）
3. `init-config`（未作成なら）→ `discover` → `sync-down` → `snapshot` → `bootstrap`
4. 再ベンチ → `pull` → `analyze` → `pack`
5. AI に `out/pack.md` を渡して次の仮説を1つ選ぶ

**改善ループ**

1. AI がパッチ → コミット → `deploy`
2. EC2 でベンチ
3. `pull` → `analyze` → `pack` → また AI へ
4. `bench-note` … 上がれば残す / 下がれば `rollback`

計測なしの全面書き換えは後回し。終盤に再起動耐性を見る。

## 前提

- Python 3.12+
- `ssh` / `rsync`
- 競技 EC2 用の SSH 鍵
- （任意）laptop 側の `alp` / `pt-query-digest` — `analyze` は手元で動く。無くてもフォールバックする

## セットアップ

```bash
git clone https://github.com/m8i-51/isucon-loop-kit.git
cd isucon-loop-kit
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e .            # 開発: pip install -e ".[dev]"  /  uv sync --extra dev
isuctl --help
```

`isucon.toml` / `work/` / `out/` / 鍵は git 管理外です。

## 使い方

```bash
# 初回（リポジトリ直下）
isuctl init-config --host HOST --key ~/.ssh/YOUR_KEY
isuctl ensure-access        # 必要な AMI のみ（ubuntu → isucon）
isuctl discover && isuctl sync-down
isuctl snapshot && isuctl bootstrap

# 改善ループ
isuctl deploy               # work/ を編集・コミットしたあと（isuride-* / isucon-* を順に再起動）
# EC2 上でベンチを実行（isuctl は起動しない）
isuctl pull && isuctl analyze && isuctl pack
isuctl bench-note           # スコア報告（対話。引数でも可）
```

既定ユーザーは `isucon`（`bootstrap_user=ubuntu`）。

**`bench-note`:** 前回・最高との差分を出し、前回より低いときは記録前に確認します（`--yes` で省略可）。戻すなら `isuctl rollback`。

## Docker ドックフーディング

AMI なしで一通り回す（Cloud Agent / 手元 Docker）:

```bash
./scripts/dogfood-docker-up.sh
./scripts/dogfood-docker-loop.sh          # 任意: BENCH_SCORE=12345
```

詳細: [Docker ドックフーディング](assets/isucon14-docker/README.md) / 実 AMI: [チェックリスト](scripts/dogfood-checklist.md)

## ドキュメント

| | |
| --- | --- |
| [設計](docs/superpowers/specs/2026-08-09-isucon-loop-kit-design.md) | 方針 |
| [pprotein](assets/pprotein/README.md) | alp / slow ビューア（laptop） |
| [Docker ドックフーディング](assets/isucon14-docker/README.md) | compose + SSH ターゲット |
| [AMI チェックリスト](scripts/dogfood-checklist.md) | 実機 E2E・ハマりどころ |
| [matcher-http.service](assets/isucon14/matcher-http.service) | ISUCON14 CODE=32 回避例 |

監視用 EC2 を競技 VPC に置かないこと。

## ライセンス・商標

MIT License（[LICENSE](LICENSE)）。

本プロジェクトは ISUCON 運営・さくらインターネット株式会社とは無関係の非公式ツールです。

「ISUCON」は、さくらインターネット株式会社の商標または登録商標です。  
https://isucon.net
