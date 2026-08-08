# ISUCON14 dogfood checklist

Manual end-to-end verification of `isuctl` against a real ISUCON14 AMI. Check off each step.

## 1. Launch instance

- [ ] Region: `ap-northeast-1`
- [ ] AMI: ISUCON14 official (`ami-0e334c50145a3ee41`) or [matsuu/aws-isucon](https://github.com/matsuu/aws-isucon) ISUCON14 image
- [ ] Security group allows SSH (22) from your IP
- [ ] Note public IP / DNS as `HOST`

## 2. Init config

```bash
isuctl init-config --host HOST
```

- [ ] `isucon.toml` created with `app1` host

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

## 5. pull → analyze → pack

Generate traffic (manual curl or benchmark), then:

```bash
isuctl pull
isuctl analyze
isuctl pack
```

- [ ] `out/raw/*` contains logs
- [ ] `out/analyze/*` contains alp / slow output
- [ ] `out/pack.md` written with section headings

## 6. Teardown

- [ ] Stop or terminate the EC2 instance
- [ ] Remove stale SSH host keys if you will reuse the same config with a new instance

## Optional

- [ ] pprotein on laptop via SSH tunnel — see [assets/pprotein/README.md](../assets/pprotein/README.md)
- [ ] `isuctl bench-note SCORE --note "dogfood run"` after a benchmark
