# ISUCON14 dogfood checklist

Manual end-to-end verification of `isuctl` against a real ISUCON14 AMI. Check off each step.

## 1. Launch instance

- [ ] Region: `ap-northeast-1`
- [ ] AMI: ISUCON14 official (`ami-0e334c50145a3ee41`) or [matsuu/aws-isucon](https://github.com/matsuu/aws-isucon) ISUCON14 image
- [ ] Instance type: **non-burstable** (`c5.large` / `c6i.large` 以上). `t3.*` は CPU クレジット枯渇で初期実装でも CODE=32（マッチング失敗）になりやすい
- [ ] Security group allows SSH (22) from your IP
- [ ] Note public IP / DNS as `HOST`

## 2. Init config + SSH access

```bash
isuctl init-config --host HOST --key ~/.ssh/YOUR_KEY
isuctl ensure-access   # copies ubuntu authorized_keys → isucon (AMI default)
```

- [ ] `isucon.toml` created with `app1` host
- [ ] `ensure-access` makes `isucon@HOST` reachable

## 3. Discover → sync-down → snapshot → bootstrap

```bash
isuctl discover
isuctl sync-down
isuctl snapshot
isuctl bootstrap
```

- [ ] `discover` updated roles / `remote_app_dir`
- [ ] `sync-down` populated `./work` (or configured `local_dir`)
- [ ] `snapshot` recorded on remote
- [ ] `bootstrap` applied nginx LTSV + MySQL slow log snippets

## 4. Dummy edit → deploy

- [ ] Make a trivial change under `local_dir` (e.g. comment in app code)
- [ ] `isuctl deploy` succeeds (requires sync-down ready marker)

```bash
isuctl deploy
```

## 5. Bench → pull → analyze → pack

On the contest host (same box AMI):

```bash
# Optional: reduce matching latency for stock app dogfood
# sed -i 's/ISUCON_MATCHING_INTERVAL=.*/ISUCON_MATCHING_INTERVAL=0.1/' ~/env.sh
# sudo systemctl restart isuride-matcher

sudo truncate -s 0 /var/log/nginx/access.ltsv.log /var/log/mysql/mysql-slow.log
./bench run --addr 127.0.0.1:443 --target https://isuride.xiv.isucon.net \
  --payment-url http://127.0.0.1:12345 --payment-bind-port 12345
```

Then on your laptop:

```bash
isuctl pull
isuctl analyze
isuctl pack
isuctl bench-note SCORE --note "dogfood run"
```

- [ ] Bench completes (note matching failures separately)
- [ ] `out/raw/*` contains LTSV access + slow logs
- [ ] `out/analyze/*` contains alp / slow output
- [ ] `out/pack.md` written with section headings

## 6. Teardown

- [ ] Stop or terminate the EC2 instance
- [ ] Remove stale SSH host keys if you will reuse the same config with a new instance

## Optional

- [ ] pprotein on laptop via SSH tunnel — see [assets/pprotein/README.md](../assets/pprotein/README.md)
- [ ] `isuctl bench-note SCORE --note "dogfood run"` after a benchmark

## Known gotchas (ISUCON14 AMI)

- Prefer **non-burstable** instances (`c5.large+`). `t3.*` with 0 CPU credits → stock app fails with CODE=32.
- Default matcher curls `https://isuride...` through nginx/TLS. Under load that request can stall and starve matching.
  Fix for dogfood / early practice:
  See also `assets/isucon14/matcher-http.service`.
  ```bash
  # /etc/systemd/system/isuride-matcher.service ExecStart:
  # curl -s --max-time 1 http://127.0.0.1:8080/api/internal/matching
  # and ISUCON_MATCHING_INTERVAL=0.05 in ~/env.sh
  sudo systemctl daemon-reload && sudo systemctl restart isuride-matcher
  ```
- Bootstrap installs `alp` to `~/local/bin` (login PATH). `pt-query-digest` needs `apt-get update` first on stale AMIs.
- MySQL `long_query_time=0` floods the DB; kit default is `0.2`.

