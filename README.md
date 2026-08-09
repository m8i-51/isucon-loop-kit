# isucon-loop-kit

ソロ向け ISUCON ループキット（`isuctl`）。

**手元（laptop）** から SSH / rsync で競技 EC2 を操作する薄い CLI です。競技サーバ上では動かしません。

```text
discover → sync-down → 編集 → deploy → bench → pull → analyze → pack → bench-note
```

可視化は `out/pack.md` を主、必要なら laptop 側の [pprotein](assets/pprotein/README.md)。自作ダッシュボードは想定しません。

## 前提

- Python **3.12+**
- `ssh` / `rsync`
- 競技 EC2 へ入れる SSH 鍵
- （任意）`alp` / `pt-query-digest` — 無くても `analyze` はフォールバックする

## セットアップ

```bash
git clone https://github.com/m8i-51/isucon-loop-kit.git
cd isucon-loop-kit

python3.12 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
# 開発時: pip install -e ".[dev]"
# または: uv sync --extra dev

isuctl --help
```

## 典型フロー

```bash
# 初回（リポジトリ直下で。isucon.toml がここにできる）
isuctl init-config --host HOST --key ~/.ssh/YOUR_KEY
isuctl ensure-access   # ubuntu → isucon の鍵コピーが必要な AMI 向け
isuctl discover
isuctl sync-down
isuctl snapshot
isuctl bootstrap       # nginx LTSV / MySQL slow / alp など

# 改善ループ
isuctl deploy          # work/ を編集・コミットしたあと
# （EC2 上でベンチを実行）
isuctl pull
isuctl analyze
isuctl pack            # out/pack.md
isuctl bench-note      # スコアは対話入力（引数でも可）
```

`init-config` の既定は `user=isucon` / `bootstrap_user=ubuntu`。

### スコア報告（`bench-note`）

ベンチ本体は EC2 上で叩きます。終わったら手元でスコアを報告します。

```bash
isuctl bench-note                 # 対話で入力
isuctl bench-note 12345 -n "memo" # 引数で直接
```

- 前回・最高との差分を表示する
- 前回より低いときは記録前に確認する（`--yes` でスキップ可）
- 悪化を残したくないときは `isuctl rollback`

## Docker 犬食い（AMI なし）

Cloud Agent / 手元 Docker 向け。詳細は [assets/isucon14-docker/README.md](assets/isucon14-docker/README.md)。

```bash
./scripts/dogfood-docker-up.sh
./scripts/dogfood-docker-loop.sh
# スコアを入れるなら: BENCH_SCORE=12345 ./scripts/dogfood-docker-loop.sh
```

実 AMI の手動 E2E は [scripts/dogfood-checklist.md](scripts/dogfood-checklist.md)。

## 注意

- `isucon.toml` / `work/` / `out/` / 鍵は git 管理外
- `isuctl` はベンチ起動まではしない
- 監視用 EC2 を競技 VPC に同居させない（pprotein は laptop）

## ドキュメント

| 文書 | 内容 |
| --- | --- |
| [設計メモ](docs/superpowers/specs/2026-08-09-isucon-loop-kit-design.md) | 全体方針 |
| [pprotein](assets/pprotein/README.md) | alp / slow の任意ビューア |
| [Docker 犬食い](assets/isucon14-docker/README.md) | compose + SSH ターゲット |
| [AMI 犬食いチェックリスト](scripts/dogfood-checklist.md) | 実機 E2E とハマりどころ |
| [matcher-http.service](assets/isucon14/matcher-http.service) | ISUCON14 CODE=32 回避例 |
