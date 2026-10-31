# scripts/

Helpers used from the laptop. Contest-year portal IDs / hostnames may be hard-coded — rewrite before reuse.

| Script | Role |
| --- | --- |
| `bench_metrics.py` / `.sh` | Sample host/DB metrics during a bench (SSH). |
| `portal_bench.py` | ISUCON portal enqueue helper (year-specific API). |
| `dogfood-*.sh` | Docker dogfood loop. |

Deploy is **not** here — use `../ansible/`.
