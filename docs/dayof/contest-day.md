# ISUCON2026 当日

本番は 2026-10-31（土）10:00–18:00 JST。手元は MacBook Air（Mac mini ではない）。ツールは手元の [isucon-loop-kit](https://github.com/m8i-51/isucon-loop-kit)（`isuctl`）。競技サーバでは動かさない。

10:00 に「本番開始」と HOST / ポータルが来たら、最初の返信は [初手だけ](#10-00-の返信) に限る。

## ループ

`discover → sync-down → 編集 → deploy → bench → pull → analyze → pack → bench-note`

主成果物は `out/pack.md`。仮説は常に 1 つ。上がれば残す。下がれば `isuctl rollback`。

## 最初の30分

README「大会当日」の順。初手ベンチより前にアプリも計測設定も触らない。

1. EC2 起動、ポータル確認
2. 何もいじらず初手ベンチ → `isuctl bench-note`（基準点）
3. `init-config`（未作成なら）→ `discover` → `sync-down` → `snapshot` → `bootstrap`
4. 再ベンチ → `pull` → `analyze` → `pack`
5. `out/pack.md` を読んで仮説を 1 つ選ぶ

`isuctl` はベンチを起動しない。ベンチは競技サーバ上で、ポータル記載のコマンドを使う。

```bash
# キットのクローン直下。isucon.toml が無いときだけ
isuctl init-config --host HOST --user isucon --key ~/.ssh/moriko_pri
isuctl discover && isuctl sync-down
isuctl snapshot && isuctl bootstrap
# 再ベンチのあと
isuctl pull && isuctl analyze && isuctl pack
isuctl bench-note SCORE --note "baseline"
```

`ensure-access` は ubuntu から isucon へ鍵をコピーするときだけ。今回の鍵は `isucon` に入る前提。

## SSH

- 秘密鍵: `~/.ssh/moriko_pri`
- ユーザー: `isucon`
- 練習インスタンス `13.197.63.145` ではこの鍵でログイン済み（2026-10-22）

```bash
ssh -i ~/.ssh/moriko_pri isucon@HOST
```

ログインシェルがすぐ終わるとき:

```bash
ssh -i ~/.ssh/moriko_pri -t isucon@HOST 'bash --noprofile --norc'
```

## レギュレーション

- URI、レスポンス構造、JS / CSS / メディアは変更禁止
- ベンチ中の外部リソース委譲は禁止
- 再起動後も動作し、データが残ること
- AI による分析と生成は可
- 採点追試あり（再起動後に再現できること）
- 計測なしの全面書き換えは後回し
- 終盤に再起動耐性を確認する

## 手元の確認

手元 = MacBook Air。

コンテスト前に、キットのクローン直下で実行する。

```bash
ls -l ~/.ssh/moriko_pri
ssh-keygen -lf ~/.ssh/moriko_pub
python3.12 --version
command -v ssh
command -v rsync
isuctl --version
command -v alp || echo "alp なし。analyze はフォールバック"
command -v pt-query-digest || echo "pt-query-digest なし。analyze はフォールバック"
```

`isuctl` が無いとき:

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e .
```

## 10:00 の返信

HOST とポータル情報を受け取った直後は、これだけ返す。

```text
いじらず初手ベンチ。アプリも設定も触らない。

ssh -i ~/.ssh/moriko_pri isucon@HOST
# シェルがすぐ終わるとき
ssh -i ~/.ssh/moriko_pri -t isucon@HOST 'bash --noprofile --norc'

サーバ上で、ポータル記載のベンチコマンドを1回だけ実行する。

手元（isucon-loop-kit 直下）:
isuctl bench-note SCORE --note "baseline"
```

`SCORE` はベンチ結果の点数。`init-config` 以降は、この基準点を記録してから。
