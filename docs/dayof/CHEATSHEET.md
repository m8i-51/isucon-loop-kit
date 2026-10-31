# 開会式ライブ 9:30 https://www.youtube.com/watch?v=7EnEvey_0RI

# ISUCON2026 チートシート（コピペ用）

```bash
# --- 準備（MacBook Air） ---
caffeinate -dims &
cd ~/Projects/isucon-loop-kit && git pull --ff-only && source .venv/bin/activate
ssh-add --apple-use-keychain ~/.ssh/moriko_pri; ssh-add -l
export H1=<IP1> H2=<IP2> H3=<IP3>
sed -i '' "s/REPLACE_WITH_IP_1/$H1/;s/REPLACE_WITH_IP_2/$H2/;s/REPLACE_WITH_IP_3/$H3/" ~/.ssh/config

# --- SSH ---
ssh isucon 'whoami; hostname'
ssh -i ~/.ssh/moriko_pri -t isucon@$H1 'bash --noprofile --norc'   # 入ってすぐ切れる時
ssh-keygen -R $H1                                                   # host key changed
isuctl ensure-access                                                # isucon で入れず ubuntu だけ入れる時のみ

# --- サーバ確認 ---
ssh isucon "systemctl list-units --type=service --state=running | grep -Ei 'isu|nginx|mysql|maria|postgres|redis'"
ssh isucon 'nproc; free -h; df -h /; cat ~/env.sh'

# --- 初期化（初手ベンチ後） ---
isuctl init-config --name isucon2026 --host $H1 --key ~/.ssh/moriko_pri
isuctl bench-note <SCORE> --note "初期実装"
isuctl discover && isuctl sync-down && isuctl snapshot && isuctl bootstrap

# --- 1 ループ ---
isuctl deploy
ssh isucon 'sudo truncate -s 0 /var/log/nginx/access.ltsv.log /var/log/mysql/mysql-slow.log'
#   ↓ ポータルでベンチ
isuctl pull && isuctl analyze && isuctl pack && open out/pack.md
isuctl bench-note <SCORE> --note "<変更内容>"
isuctl rollback                                                     # 下がった時（HEAD~1）

# --- 終盤 ---
ssh isucon 'sudo reboot'          # 16:30 再起動試験 → ベンチ → データ残ってるか
# 17:15 ログ切る: nginx access_log off / MySQL slow_query_log=0 → 再起動 → ベンチ
```

ダメ: ベンチ中の外部リソース／URI・レスポンス構造・JS/CSS・メディア変更／再起動でデータ消える／問題内容を外に出す（推察できる発言も）
質問: 競技中=ポータル、前後=Discord。18:00 後も EC2 は消さない（追試）。
