#!/usr/bin/env bash
# Sample instances during a bench. See scripts/bench_metrics.py --help
exec python3 "$(cd "$(dirname "$0")" && pwd)/bench_metrics.py" "$@"
