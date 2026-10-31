# ISUCON2026 当日ランブック（もりこソロ / 2026-10-31 土）

競技 10:00–18:00 JST。作業機は **MacBook Air**（MacBook-Air.local）。Mac mini（morikonoMac-mini.local）は予備機。
キット: `~/Projects/isucon-loop-kit`（**Mac mini には**クローン＋`uv sync`＋GNU rsync 済み・テスト 102 本 pass。**MacBook Air は 10/29 時点オフラインで未確認** → 下の 0-A を前日にやる）。
レギュレーション: https://isucon.net/archives/59966826.html ／ **当日マニュアルがレギュより優先**。

> `<…>` は当日ポータル／マニュアルで埋めるところ。

---

## 0. 前日まで（10/30 金）にやっとく

### 0-A. MacBook Air セットアップ（Grok Bot から見えるように Air を起動＋接続しといて）
```bash
# 道具チェック
for c in git gh uv ssh rsync cursor brew; do printf "%-8s" $c; command -v $c || echo MISSING; done
rsync --version | head -1        # openrsync なら ↓ で GNU rsync 入れる
brew install rsync uv gh          # 足りないものだけ
gh auth status

# キット
mkdir -p ~/Projects && cd ~/Projects
git clone https://github.com/m8i-51/isucon-loop-kit.git
cd isucon-loop-kit && uv sync --extra dev && .venv/bin/pytest -q && .venv/bin/isuctl --help | head -3

# 鍵（練習機に入れた moriko_pri。Air にあるはず。無ければ入ってる機体から scp）
ls -l ~/.ssh/moriko_pri && chmod 600 ~/.ssh/moriko_pri
ssh-keygen -y -f ~/.ssh/moriko_pri >/dev/null && echo key-ok
```
- この kit（DAYOF.md / CHEATSHEET.md / ssh_config.isucon）は Mac mini の `~/Projects/isucon-dayof/` にある。Air へは AirDrop か `scp -r moriko@morikonoMac-mini.local:~/Projects/isucon-dayof ~/Projects/`
- **電源アダプタ必須**（8 時間）、スリープ防止: 当日は `caffeinate -dims &`
- Wi-Fi が落ちた時用に iPhone テザリングを確認しとく

### 0-B. 共通
- [ ] パスフレーズ付きなら Keychain に入れる（isuctl は `BatchMode=yes` で ssh するので、聞かれると落ちる）
  ```bash
  ssh-add --apple-use-keychain ~/.ssh/moriko_pri && ssh-add -l
  ```
- [ ] `ssh_config.isucon` を `~/.ssh/config` に追記（IP は当日書き換え）
- [ ] 公開鍵がポータル／GitHub に登録されてるか確認（ISUCON は「GitHub ユーザー名 → `github.com/<user>.keys` を authorized_keys に入れる」方式が多い）
  ```bash
  curl -s https://github.com/m8i-51.keys
  ssh-keygen -y -f ~/.ssh/moriko_pri   # ↑ にこれと同じ行があれば OK
  ```
- [ ] AWS コンソールに Air のブラウザでログインできる／リージョン `ap-northeast-1`／vCPU 上限（c 系オンデマンド）が足りてる
- [ ] Discord ログイン＋通知 ON、ポータルにログインできる
- [ ] 練習機（13.197.63.145 など）が残ってたら **stop / terminate**（課金止め）

---

## 1. 分刻み（09:45 → 初手ベンチ 〜10:30）

### 09:30 開会式ライブ（YouTube）
- https://www.youtube.com/watch?v=7EnEvey_0RI （予定 9:30 JST・開会式兼競技説明）
- ISUCONくんが要点を拾ってチャットに送る。自分でも流し見しておくと安心。

### 09:45 環境を開く
- ブラウザタブ: Discord（ISUCON2026 サーバの announcement）／ポータル `<PORTAL_URL>`／AWS コンソール（ap-northeast-1）／レギュ
- ターミナルタブを 3 つ（電源つないで `caffeinate -dims &`）: ①キット ②EC2 ssh ③予備
  ```bash
  cd ~/Projects/isucon-loop-kit && git pull --ff-only && source .venv/bin/activate && isuctl --help | head -3
  ssh-add -l          # moriko_pri が出ること（パスフレーズ付きの場合）
  ```
- Cursor: isucon Project（https://cursor.com/agents/bc-17b90332-0ba9-474f-a581-11a8194cd126）を開いとく

### 09:55 待機
- Discord のアナウンス確認。ポータルをリロードできるようにしとく。

### 10:00 開始 → マニュアル読む（〜10:08）
- ポータルの **当日マニュアル** を開く。読むのはここだけ先に:
  1. サーバ起動方法（CloudFormation テンプレ？ AMI ID？ 台数・インスタンスタイプ）
  2. ログインユーザー／鍵の入れ方
  3. ベンチの実行方法（ポータルから？）、採点条件、失格条件
  4. アプリ構成（言語切替方法、systemd unit 名、DB、nginx）
  5. 追加の禁止事項
- isucon Project に「開始メッセージ」（末尾）を投げて、マニュアル要約を並行でやらせる（※マニュアル本文はログイン必須ページ＝非公開情報。チーム外に出さない。AI 利用は OK）

### 10:08 AWS 起動（〜10:15）
CloudFormation 方式の場合:
- [ ] リージョン **ap-northeast-1**（マニュアル指定に従う）
- [ ] CloudFormation → スタック作成 → テンプレ `<CFN_TEMPLATE_URL>`
- [ ] パラメータ: GitHub ユーザー名 `m8i-51` ／ `<その他マニュアル指定>`
- [ ] 作成完了まで待つ（数分）→ 出力 or EC2 一覧から **Public IP** を控える

AMI 直起動の場合:
- [ ] AMI `<AMI_ID>`、タイプ `<マニュアル指定>`（勝手に変えない。t3 系はクレジット枯渇で詰む）
- [ ] キーペア／SG はマニュアル通り。SSH(22) を自分の IP から
- [ ] 台数はマニュアル指定どおり（指定外の EC2 を競技に使う＝禁止）

IP を控えたら:
```bash
export H1=<IP1>  H2=<IP2>  H3=<IP3>
sed -i '' "s/REPLACE_WITH_IP_1/$H1/;s/REPLACE_WITH_IP_2/$H2/;s/REPLACE_WITH_IP_3/$H3/" ~/.ssh/config
```

### 10:15 SSH 疎通
```bash
ssh isucon 'whoami; hostname; uptime'           # 非対話で返ってくれば isuctl も動く
ssh -t isucon                                    # 普通に入る
# 練習機みたいに「全てのチェックをパスしました」で切れる場合:
ssh -i ~/.ssh/moriko_pri -t isucon@$H1 'bash --noprofile --norc'
```
- `isucon@` で入れず `ubuntu@` だけ入れる AMI のときだけ `isuctl ensure-access`（ubuntu の authorized_keys を isucon に**上書きコピー**するので、isucon で入れるなら打たない）
- 入れたらサーバ上で状況だけ見る（変更しない）:
  ```bash
  ls ~; cat ~/env.sh 2>/dev/null
  systemctl list-units --type=service --state=running | grep -Ei 'isu|nginx|mysql|maria|postgres|redis|memcache'
  sudo ss -lntp | head -30
  nproc; free -h; df -h /
  ```

### 10:20 初手ベンチ（何もいじらない状態で）
- ポータルからベンチ実行 `<BENCH_BUTTON>`（マニュアルが CLI 指定ならそれ）
- 待ってる間に手元で config:
  ```bash
  cd ~/Projects/isucon-loop-kit && source .venv/bin/activate
  isuctl init-config --name isucon2026 --host $H1 --key ~/.ssh/moriko_pri
  # 複数台なら isucon.toml に [[hosts]] を追記（name=app2, host=$H2 ...）
  ```
- スコアが出たら:
  ```bash
  isuctl bench-note --note "初期実装そのまま"     # SCORE を聞かれる／引数でも可
  ```

### 10:23 キットで計測セット
```bash
isuctl discover        # roles / remote_app_dir を埋める → isucon.toml を目視確認
isuctl sync-down       # ./work にコード取得（git init + 初回コミットまで自動）
isuctl snapshot        # リモートに復元ポイント
isuctl bootstrap       # nginx LTSV / MySQL slow(0.2s) / alp / pt-query-digest
```
- 確認: `ssh isucon 'sudo nginx -t; ls -la /var/log/nginx/access.ltsv.log /var/log/mysql/mysql-slow.log'`
- 言語切替するならここで（マニュアルの方法で）。`isuctl deploy` は既定で `isucon-python.service` → `isuride-*`/`isucon-*` の順で restart するので、使う言語の unit 名を確認しとく。
- DB が MySQL じゃない（Postgres 等）なら slow は効かない → AI に pg_stat_statements 等を相談

### 10:27 計測ベンチ
```bash
ssh isucon 'sudo truncate -s 0 /var/log/nginx/access.ltsv.log /var/log/mysql/mysql-slow.log'
```
→ ポータルでベンチ → 終わったら
```bash
isuctl pull && isuctl analyze && isuctl pack
isuctl bench-note --note "bootstrap後（計測込み）"
open out/pack.md
```

### 10:30 最初の分析 → AI へ
- isucon Project（or Air の Cursor）に `out/pack.md` と `work/` を渡して「**仮説 1 つだけ**」選ばせる
- ループ:
  ```bash
  # AI がパッチ → work/ でコミット
  isuctl deploy
  ssh isucon 'sudo truncate -s 0 /var/log/nginx/access.ltsv.log /var/log/mysql/mysql-slow.log'
  # ポータルでベンチ
  isuctl pull && isuctl analyze && isuctl pack
  isuctl bench-note --note "<何を変えたか>"     # 下がったら → isuctl rollback
  ```

---

## 2. 中盤〜終盤の時刻メモ

| 時刻 | やること |
| --- | --- |
| 12:30 | 昼。ベンチ回してる間に食べる |
| 15:00 | 複数台構成にするならこの辺までに決める |
| 16:30 | **再起動試験**: `ssh isucon 'sudo reboot'` → 全台起動後にベンチ。データが残ってるか確認 |
| 17:15 | ログ・計測を切る（nginx access_log off、slow_query_log=0、pprof 等の削除）→ 再起動 → ベンチ |
| 17:40 | 以降は大きい変更しない。最終スコアを確認 |
| 18:00 | 終了。**追試があるので EC2 は消さない／止めない**（運営の案内まで） |

---

## 3. やってはいけない（レギュより）

- **ベンチ中に外部リソースを使う**（他インスタンスへの処理委譲、外部 API／マネージドサービスに逃がす等）。※監視・テスト・開発に PC や外部サーバ、AI を使うのは OK
- 指定 AMI／マニュアル通りに作った EC2 **以外** を競技に使う。監視用 EC2 を競技 VPC に置かない
- 変えちゃダメ: **アクセス先 URI**（サーバ生成の ID は文字種を変えない範囲なら可）、**レスポンス構造**（HTML DOM／JSON。表示に影響しない空白は可）、**JS/CSS の中身**、**画像・動画などメディアの中身**
- 再起動後に動かない状態にする／ベンチで書いたデータが**再起動後に取れない**（オンメモリだけのキャッシュで永続化しない等）。追試は再起動順序不定
- コンテスト進行用メンテナンスコマンドの互換性を壊す
- 競技終了まで問題内容・ベンチの計測方法などを公開・共有（**推察できる発言も NG**、SNS・X 含む）。チーム外の人と問題の話をしない。ポータルのログイン必須ページは非公開情報
- 提供されてないサーバ（ベンチマーカー等）へのアクセス試行、外部への不正アクセス
- 他チームとの結託、妨害
- スコアの捏造（追試で再現しないと失格）
- 当日マニュアル・ポータルで禁止とされたこと全部

質問は **競技中＝ポータル**、競技前後＝Discord。Discord の mention は見逃さない。

---

## 4. 詰まったとき

| 症状 | 対処 |
| --- | --- |
| `Permission denied (publickey)` | `ssh -v isucon` で使ってる鍵を確認。GitHub の keys と `ssh-keygen -y -f ~/.ssh/moriko_pri` が一致してるか。ubuntu では入れるなら `isuctl ensure-access` |
| isuctl だけ ssh 失敗 | パスフレーズ → `ssh-add --apple-use-keychain ~/.ssh/moriko_pri`。`ssh -o BatchMode=yes -i ~/.ssh/moriko_pri isucon@$H1 true` で再現 |
| ログイン直後に切れる | `ssh -t isucon@$H1 'bash --noprofile --norc'`。非対話 `ssh isucon true` が通れば isuctl は問題なし |
| host key changed | `ssh-keygen -R $H1` |
| deploy が ready マーカーで止まる | `isuctl sync-down` を先にやる |
| deploy 後アプリが restart されない | `systemctl list-units \| grep isu` で unit 名確認 → 手で `sudo systemctl restart <unit>` |
| スコア低下 | `isuctl rollback`（既定 HEAD~1、`git reset --hard` するので未コミット注意） |
