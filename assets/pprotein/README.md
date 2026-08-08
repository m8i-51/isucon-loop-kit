# pprotein setup (no VPC co-location)

[pprotein](https://github.com/kaz/pprotein) is the recommended viewer for alp / slow-query output during the ISUCON loop. This kit does **not** ship a custom dashboard — run pprotein on your **laptop** or another machine **outside** the contest VPC.

## Where to run

| OK | Not OK |
|---|---|
| Your laptop | Monitoring EC2 in the **same VPC** as contest servers |
| Home lab / separate AWS account / different VPC | Any host that shares network placement with the benchmark targets |

> **Warning:** Do **not** place a monitoring EC2 instance in the contest VPC. Extra load and shared failure domains can skew benchmarks and violate the spirit of solo practice. Keep observability off the contest network; use SSH port forwarding from your laptop instead.

## Prerequisites on servers

Before pprotein can read logs meaningfully, remote hosts need the right log formats. Run from this repo:

```bash
isuctl bootstrap
```

This deploys nginx LTSV access logging, MySQL slow-query settings, and (best-effort) alp on the remote host. See `src/isuctl/bootstrap.py` for details.

## Install pprotein (laptop)

Follow upstream instructions: [kaz/pprotein](https://github.com/kaz/pprotein).

Typical flow:

1. Clone or install the pprotein binary on your laptop.
2. Ensure `isuctl pull` / `isuctl analyze` have produced artifacts under `out/` (or point pprotein at the remote log paths per upstream docs).

## SSH local forward example

When pprotein expects a service on the remote host (e.g. port 19000), forward it to your laptop:

```bash
ssh -L 19000:127.0.0.1:19000 isucon@HOST
```

Replace `HOST` with the app server IP or DNS from `isucon.toml`. Open `http://127.0.0.1:19000` locally while the tunnel is up.

For multiple hosts, open one tunnel per host or use separate local ports (`19001`, …).

## Related commands

```text
isuctl pull      # fetch raw logs from remote
isuctl analyze   # run alp / slow-query digest into out/analyze/
isuctl pack      # bundle findings for Cursor
```
