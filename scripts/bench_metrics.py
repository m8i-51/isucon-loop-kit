#!/usr/bin/env python3
"""Sample asia1/europe1/america1/asia2 during a running bench (read-only).

Usage:
  ./scripts/bench_metrics.sh                 # 5s interval, 240s max (Ctrl-C to stop early)
  ./scripts/bench_metrics.sh -d 15 -i 5 --tag idle
  python3 scripts/portal_bench.py enqueue --target-id N && ./scripts/bench_metrics.sh --tag bench
Output: out/bench-metrics/<ts>[-tag]/{samples.jsonl,hosts.csv,pg.csv,pg_end.txt}
"""
from __future__ import annotations

import argparse, csv, json, os, signal, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

HOSTS = ["asia1", "europe1", "america1", "asia2"]
DB_HOST = "asia2"
PSQL = "PGPASSWORD=isureal psql -h 127.0.0.1 -U isureal -d isureal -AtqX -F'|'"
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=4",
       "-o", "ControlMaster=auto", "-o", "ControlPath=/tmp/bm-%r@%h", "-o", "ControlPersist=600"]

# vmstat & iostat run concurrently (1s each) so a sample costs ~1.2s remote.
REMOTE = r'''
(vmstat -w 1 2 | tail -1 > /tmp/.bm_vm) & 
(command -v iostat >/dev/null && iostat -dxy 1 1 > /tmp/.bm_io) &
echo "LOAD $(cut -d' ' -f1-4 /proc/loadavg)"
echo "NCPU $(nproc)"
free -m | awk '/^Mem:/{print "MEM",$2,$3,$7}'
echo "ESTAB $(ss -Htn state established | wc -l)"
echo "TW $(ss -Htn state time-wait | wc -l)"
ss -s | awk '/^TCP:/{print "SSTCP",$0}'
ps -eo pcpu,rss,comm --sort=-pcpu | sed -n 2,5p | awk '{print "TOP",$1,$2,$3}'
wait
echo "VM $(cat /tmp/.bm_vm)"
[ -f /tmp/.bm_io ] && awk '/^Device/{f=1;next} f&&NF>5&&$1!~/^loop/{print "IO",$1,$2,$8,$(NF-1)?$0:$0}' /tmp/.bm_io | awk '{print "IO",$2,$NF}'
'''
PG = r'''
echo "PGACT $(%(psql)s -c "select count(*) from pg_stat_activity where state='active' and pid<>pg_backend_pid()")"
echo "PGCONN $(%(psql)s -c "select count(*) from pg_stat_activity where backend_type='client backend'")"
%(psql)s -c "select coalesce(wait_event_type,'CPU'),coalesce(wait_event,'-'),count(*) from pg_stat_activity where state='active' and pid<>pg_backend_pid() group by 1,2 order by 3 desc" | sed 's/^/PGWAIT /'
%(psql)s -c "select xact_commit,xact_rollback,blks_read,blks_hit,tup_returned,tup_fetched,tup_inserted,tup_updated,tup_deleted,deadlocks,temp_bytes from pg_stat_database where datname='isureal'" | sed 's/^/PGDB /'
''' % {"psql": PSQL}

def ssh(host: str, cmd: str, timeout: float = 8) -> str:
    try:
        r = subprocess.run(SSH + [host, cmd], capture_output=True, text=True, timeout=timeout)
        return r.stdout + (("\nERR " + r.stderr.strip()) if r.returncode and r.stderr.strip() else "")
    except subprocess.TimeoutExpired:
        return "ERR timeout"

def parse(host: str, out: str) -> dict:
    d: dict = {"host": host, "top": [], "io": {}, "pgwait": {}}
    for line in out.splitlines():
        k, _, v = line.partition(" ")
        f = v.split()
        try:
            if k == "LOAD": d["load1"], d["load5"] = float(f[0]), float(f[1]); d["runq"] = f[3]
            elif k == "NCPU": d["ncpu"] = int(f[0])
            elif k == "MEM": d["mem_total"], d["mem_used"], d["mem_avail"] = map(int, f[:3])
            elif k == "ESTAB": d["estab"] = int(f[0])
            elif k == "TW": d["timewait"] = int(f[0])
            elif k == "VM":  # r b swpd free buff cache si so bi bo in cs us sy id wa st
                n = list(map(int, f[:17]))
                d.update(r=n[0], b=n[1], si=n[6], so=n[7], bi=n[8], bo=n[9], intr=n[10], cs=n[11],
                         us=n[12], sy=n[13], id=n[14], wa=n[15], st=n[16])
            elif k == "IO": d["io"][f[0]] = float(f[1])
            elif k == "TOP": d["top"].append(f"{f[2]}:{f[0]}")
            elif k == "PGACT": d["pg_active"] = int(f[0])
            elif k == "PGCONN": d["pg_conn"] = int(f[0])
            elif k == "PGWAIT":
                a = v.split("|"); d["pgwait"][f"{a[0]}:{a[1]}"] = int(a[2])
            elif k == "PGDB": d["pgdb"] = list(map(int, v.split("|")))
            elif k == "ERR": d["err"] = v[:200]
        except (ValueError, IndexError):
            pass
    d["io_util_max"] = max(d["io"].values()) if d["io"] else None
    return d

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--interval", type=float, default=5)
    ap.add_argument("-d", "--duration", type=float, default=240)
    ap.add_argument("--tag", default="")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "out/bench-metrics"))
    a = ap.parse_args()
    ts = datetime.now().strftime("%Y%m%d-%H%M%S") + (f"-{a.tag}" if a.tag else "")
    od = Path(a.out) / ts; od.mkdir(parents=True, exist_ok=True)
    stop = False
    def _sig(*_):
        nonlocal stop; stop = True
    signal.signal(signal.SIGINT, _sig); signal.signal(signal.SIGTERM, _sig)
    jf = open(od / "samples.jsonl", "a")
    hcols = ["t", "host", "load1", "ncpu", "r", "b", "us", "sy", "id", "wa", "st", "cs", "intr",
             "mem_used", "mem_avail", "estab", "timewait", "io_util_max", "top"]
    hf = open(od / "hosts.csv", "w", newline=""); hw = csv.writer(hf); hw.writerow(hcols)
    pf = open(od / "pg.csv", "w", newline=""); pw = csv.writer(pf)
    pw.writerow(["t", "pg_active", "pg_conn", "d_commit", "d_blks_read", "d_blks_hit", "d_tup_ins", "d_tup_upd", "d_tup_del", "temp_bytes", "waits"])
    print(f"-> {od}  (interval={a.interval}s max={a.duration}s, Ctrl-C to stop)", flush=True)
    t0 = time.time(); prev_db = None
    with ThreadPoolExecutor(len(HOSTS)) as ex:
        while not stop and time.time() - t0 < a.duration:
            tick = time.time(); t = round(tick - t0, 1)
            futs = {h: ex.submit(ssh, h, REMOTE + (PG if h == DB_HOST else "")) for h in HOSTS}
            line = [f"t={t:>5}"]
            for h in HOSTS:
                d = parse(h, futs[h].result()); d["t"] = t; d["ts"] = datetime.now().isoformat(timespec="seconds")
                jf.write(json.dumps(d) + "\n")
                hw.writerow([d.get(c) if c != "top" else " ".join(d["top"]) for c in hcols])
                line.append(f"{h}:ld{d.get('load1')} cpu{100-d.get('id',100)}%wa{d.get('wa')} est{d.get('estab')}"
                            + (f" io{d['io_util_max']:.0f}%" if d.get('io_util_max') is not None else "")
                            + (" ERR" if 'err' in d else ""))
                if h == DB_HOST:
                    db = d.get("pgdb"); dl = [None] * 7
                    if db and prev_db:
                        x = [b - p for b, p in zip(db, prev_db)]
                        dl = [x[0], x[2], x[3], x[6], x[7], x[8], db[10]]
                    prev_db = db or prev_db
                    pw.writerow([t, d.get("pg_active"), d.get("pg_conn"), *dl, json.dumps(d["pgwait"])])
                    line.append(f"pg act{d.get('pg_active')} conn{d.get('pg_conn')} commit+{dl[0]}")
            jf.flush(); hf.flush(); pf.flush()
            print(" | ".join(line), flush=True)
            time.sleep(max(0, a.interval - (time.time() - tick)))
    end = ssh(DB_HOST, f"{PSQL} -c 'select * from pg_stat_bgwriter' ; {PSQL} -c 'select * from pg_stat_checkpointer' 2>/dev/null; "
              f"{PSQL} -c \"select * from pg_stat_database where datname='isureal'\"", timeout=15)
    (od / "pg_end.txt").write_text(end)
    print(f"done -> {od}")

if __name__ == "__main__":
    main()
