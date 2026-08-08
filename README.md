# isucon-loop-kit

ソロ向け ISUCON ループキット（`isuctl`）。

設計メモ: [`docs/superpowers/specs/2026-08-09-isucon-loop-kit-design.md`](docs/superpowers/specs/2026-08-09-isucon-loop-kit-design.md)

## なにをするか

競技サーバを正として、次のループを回す薄い CLI です。

```text
discover → sync-down → ローカル編集 → deploy → bench → pull → analyze → pack
```

重いダッシュボードは作らず、可視化は laptop 側の pprotein などを使う前提です。

## セットアップ

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## 典型フロー

```bash
isuctl init-config --host HOST --key ~/.ssh/YOUR_KEY
isuctl ensure-access
isuctl discover
isuctl sync-down
isuctl snapshot
isuctl bootstrap

# ローカルで編集したあと
isuctl deploy

# ベンチ後
isuctl pull
isuctl analyze
isuctl pack
isuctl bench-note SCORE --note "memo"
```

## ドキュメント

- [pprotein セットアップ](assets/pprotein/README.md) — 監視は競技 VPC 内ではなく laptop で動かす
- [ISUCON14 犬食いチェックリスト](scripts/dogfood-checklist.md) — 実 AMI での手動 E2E 手順と既知のハマりどころ
- [matcher 直叩き unit 例](assets/isucon14/matcher-http.service) — CODE=32 回避用（nginx/TLS 経由を避ける）
