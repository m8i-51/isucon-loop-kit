# isucon-loop-kit

ソロ向け ISUCON ループキット（`isuctl`）。

設計メモ: [`docs/superpowers/specs/2026-08-09-isucon-loop-kit-design.md`](docs/superpowers/specs/2026-08-09-isucon-loop-kit-design.md)

## なにをするか

**手元マシン（laptop）** から SSH/rsync で競技 EC2 を操作する薄い CLI です。競技サーバ上で動かすものではありません。

```text
discover → sync-down → ローカル編集 → deploy → bench → pull → analyze → pack
```

重いダッシュボードは作らず、可視化は laptop 側の pprotein などを使う前提です。

## 前提

- Python **3.12+**
- `ssh` / `rsync`（macOS / Linux なら普通にある）
- 競技 EC2 へ入れる SSH 鍵
- （任意）手元に `alp` / `pt-query-digest`。無くても analyze はフォールバックする

## セットアップ（本番でもこれ）

```bash
git clone https://github.com/m8i-51/isucon-loop-kit.git
cd isucon-loop-kit

python3.12 -m venv .venv
source .venv/bin/activate   # Windows なら .venv\Scripts\activate
pip install -e .
```

開発（pytest など）するときだけ:

```bash
pip install -e ".[dev]"
```

動作確認:

```bash
isuctl --help
```

## 典型フロー

```bash
# リポジトリ直下で（isucon.toml がここに作られる）
isuctl init-config --host HOST --key ~/.ssh/YOUR_KEY
isuctl ensure-access          # AMI が ubuntu→isucon 鍵コピー必要なとき
isuctl discover
isuctl sync-down
isuctl snapshot
isuctl bootstrap              # nginx LTSV / MySQL slow / alp など

# ローカル work/ を編集したあと
isuctl deploy

# ベンチは EC2 上で実行 → 終わったら手元で
isuctl pull
isuctl analyze
isuctl pack
isuctl bench-note SCORE --note "memo"
```

`init-config` の既定は `user=isucon` / `bootstrap_user=ubuntu`。鍵パスは自分のものを指定する。

## 注意

- `isucon.toml` / `work/` / `out/` / 鍵は git 管理外。クローンしたマシンで毎回作り直す
- ベンチ本体は EC2 上で叩く（`isuctl` はベンチ起動まではしない）
- 監視 EC2 を競技 VPC に同居させない（pprotein は laptop）

## ドキュメント

- [pprotein セットアップ](assets/pprotein/README.md) — 監視は競技 VPC 内ではなく laptop で動かす
- [ISUCON14 犬食いチェックリスト](scripts/dogfood-checklist.md) — 実 AMI での手動 E2E 手順と既知のハマりどころ
- [matcher 直叩き unit 例](assets/isucon14/matcher-http.service) — CODE=32 回避用（nginx/TLS 経由を避ける）
