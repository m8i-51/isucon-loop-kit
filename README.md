# isucon-loop-kit

ソロ向け ISUCON ループキット（`isuctl`）。

手元（laptop）から計測ループを回す薄い CLI です。デプロイ / check / 初動 provision は `ansible-playbook` のラッパーです。競技サーバ上では動かしません。

```text
discover → sync-down → 編集 → isuctl deploy → isuctl check → bench → pull → analyze → pack → bench-note
```

主成果物は `out/pack.md`。Cursor / Claude Code など生成AIが読んで次の一手を出す想定で、自作ダッシュボードは作りません。人が深く掘るときは `out/analyze/*` か laptop の [pprotein](assets/pprotein/README.md)。

## 大会当日

| 役割 | やること |
| --- | --- |
| あなた | EC2・ベンチ・`bench-note`・`isuctl deploy` / `check` / 切り戻し判断 |
| 生成AI | `out/pack.md`（必要なら `out/analyze/*`）と `work/` を読んで、仮説 **1 つ**だけ直す |

**最初の30分**

1. EC2 起動、ポータル確認
2. 何もいじらず初手ベンチ → `isuctl bench-note`（基準点）
3. `init-config`（未作成なら）→ `discover` → `sync-down` → `snapshot` → `bootstrap`
4. 再ベンチ → `pull` → `analyze` → `pack`
5. AI に `out/pack.md` を渡して次の仮説を1つ選ぶ

**改善ループ**

1. AI がパッチ → コミットして remote に載せる → `isuctl deploy --branch <name|sha>` → `isuctl check`
2. EC2 でベンチ
3. `pull` → `analyze` → `pack` → また AI へ
4. `bench-note` … 上がれば残す / 下がれば `isuctl rollback --ref <git-ref>`（手元を reset して、その SHA を ansible deploy）

計測なしの全面書き換えは後回し。終盤に再起動耐性を見る。

## 前提

- Python 3.12+
- `ssh` / `rsync`（discover / sync-down / pull 用）
- `ansible-playbook`（`isuctl deploy` / `check` / `provision` が呼ぶ）
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

# 改善ループ（isuctl が ansible-playbook を呼ぶ）
isuctl deploy --branch main          # 必要なら --limit s1,s2
isuctl check
isuctl provision                     # 初動だけ。playbooks/init.yml
# 同じことを生の ansible でやる場合（ansible/ が cwd）
# ansible-playbook playbooks/deploy.yml -e branch=main
# ansible-playbook playbooks/check.yml
# ansible-playbook playbooks/init.yml
# EC2 上でベンチを実行（isuctl は起動しない）
isuctl pull && isuctl analyze && isuctl pack
isuctl bench-note           # スコア報告（対話。引数でも可）
isuctl rollback --ref HEAD~1
```

既定ユーザーは `isucon`（`bootstrap_user=ubuntu`）。

**デプロイ:** `isuctl deploy` / `check` / `provision` が入口。中身は `ansible/playbooks/`。サーバは `repo_url` の branch / SHA を checkout する（手元 `work/` の rsync ではない）。ref は先に remote へ載せておく。切り戻しは `isuctl rollback`。

**`bench-note`:** 前回・最高との差分を出し、前回より低いときは記録前に確認します（`--yes` で省略可）。

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

## 置き場（これが唯一のキット）

| パス | 役割 |
| --- | --- |
| このリポジトリ (`isucon-loop-kit`) | 本体。計測ループもデプロイ入口も `isuctl`。実体は `ansible/` |
| `ansible/` | deploy / check / init の playbook（`isuctl` がここを呼ぶ） |
| `docs/dayof/` | 当日メモ・チートシート・ssh_config |
| `~/isu_work-2026/` | ISUCON2026 本番スクラッチ（アーカイブ。キットに混ぜない） |

昔バラバラだった `~/isucon-kit` と `Projects/isucon-dayof` はここへ吸収済み。新しい道具は **このリポの中** にだけ足す。

## デプロイ（isuctl → Ansible）

AI・人間とも、まずは `isuctl`。契約の細則は [`ansible/AGENTS.md`](./ansible/AGENTS.md)。

```bash
isuctl provision                         # 初動: playbooks/init.yml
isuctl deploy --branch <name-or-sha>     # playbooks/deploy.yml -e branch=…
isuctl check                             # playbooks/check.yml
# どれも [--limit s1,s2]。キットのルート（ansible/playbooks が見える場所）で実行
```

生の playbook も同じ API で、`isuctl` が実際に呼ぶ形です。

```bash
cd ansible
ansible-playbook playbooks/init.yml
ansible-playbook playbooks/deploy.yml -e branch=<name>
ansible-playbook playbooks/check.yml
```

`discover` / `sync-down` / `pull` / `analyze` / `pack` / `bench-note` は今まで通り `isuctl` の仕事です。デプロイに ad-hoc な `rsync` / `scp` は使わない。

## 2026 からの教訓

問題固有のログは `~/isu_work-2026/`。来年用に蒸留したのは [docs/lessons-2026.md](./docs/lessons-2026.md)。
