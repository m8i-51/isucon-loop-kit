#!/usr/bin/env python3
"""ISUCON2026 portal benchmark helper (protobuf API)."""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://portal.isucon.net"
DEFAULT_COOKIE = Path.home() / ".config/isucon-portal/cookies.txt"


def encode_varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def encode_enqueue(target_id: int) -> bytes:
    return b"\x08" + encode_varint(target_id)


def sync_cookie_from_chrome(path: Path) -> None:
    from Crypto.Cipher import AES

    pw = subprocess.check_output(
        ["security", "find-generic-password", "-w", "-s", "Chrome Safe Storage", "-a", "Chrome"],
        text=True,
    ).strip()
    key = hashlib.pbkdf2_hmac("sha1", pw.encode(), b"saltysalt", 1003, dklen=16)
    src = Path.home() / "Library/Application Support/Google/Chrome/Default/Cookies"
    td = tempfile.mkdtemp()
    dest = Path(td) / "Cookies"
    shutil.copy2(src, dest)
    con = sqlite3.connect(dest)
    row = con.execute(
        "select encrypted_value from cookies where host_key='portal.isucon.net' "
        "and name='isuxportal_session' order by creation_utc desc limit 1"
    ).fetchone()
    con.close()
    if not row:
        raise SystemExit("no isuxportal_session in Chrome")
    ev = row[0]
    dec = AES.new(key, AES.MODE_CBC, b" " * 16).decrypt(ev[3:])
    pad = dec[-1]
    val = dec[:-pad]
    s = val[32:].decode("utf-8") if len(val) > 32 else val.decode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"isuxportal_session={s}\n")
    print(f"synced cookie -> {path}")


def load_cookie(args: argparse.Namespace) -> str:
    if getattr(args, "sync", False):
        sync_cookie_from_chrome(Path(args.cookie_file))
    if args.cookie:
        return args.cookie.strip()
    path = Path(args.cookie_file)
    if path.exists():
        return path.read_text().strip()
    env = os.environ.get("PORTAL_COOKIE", "").strip()
    if env:
        return env
    sync_cookie_from_chrome(path)
    return path.read_text().strip()


def fetch_csrf(cookie: str) -> tuple[str, str]:
    req = urllib.request.Request(
        BASE + "/contestant/benchmark_jobs",
        headers={"Cookie": cookie, "Accept": "text/html"},
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        html = res.read().decode("utf-8", "replace")
    m = re.search(r'name="csrf-token"\s+content="([^"]+)"', html)
    if not m:
        sys.exit("csrf-token meta not found (session expired? try sync-cookie)")
    return m.group(1), html


def api(method: str, path: str, cookie: str, csrf: str, body: bytes | None = None) -> bytes:
    headers = {
        "Cookie": cookie,
        "X-Csrf-Token": csrf,
        "Accept": "application/protobuf, application/vnd.google.protobuf, text/plain",
    }
    data = None
    if body is not None:
        headers["Content-Type"] = "application/vnd.google.protobuf"
        data = body
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            return res.read()
    except urllib.error.HTTPError as e:
        sys.stderr.write(f"HTTP {e.code}: {e.read()[:500]!r}\n")
        raise


def cmd_sync(args: argparse.Namespace) -> None:
    sync_cookie_from_chrome(Path(args.cookie_file))


def cmd_status(args: argparse.Namespace) -> None:
    cookie = load_cookie(args)
    csrf, html = fetch_csrf(cookie)
    raw = api("GET", "/api/contestant/benchmark_jobs", cookie, csrf)
    print(f"api list bytes={len(raw)}")
    ids = list(dict.fromkeys(re.findall(r"/contestant/benchmark_jobs/(\d+)", html)))
    print("html job ids:", ", ".join(ids[:8]))
    for label in ("RUNNING", "PENDING", "FINISHED", "ERRORED"):
        if label in html:
            print("seen", label)


def cmd_enqueue(args: argparse.Namespace) -> None:
    cookie = load_cookie(args)
    csrf, _ = fetch_csrf(cookie)
    body = encode_enqueue(args.target_id)
    raw = api("POST", "/api/contestant/benchmark_jobs", cookie, csrf, body)
    print(f"enqueued bytes={len(raw)} hex={raw.hex()}")
    print("https://portal.isucon.net/contestant/benchmark_jobs")


def cmd_wait(args: argparse.Namespace) -> None:
    cookie = load_cookie(args)
    job = args.job_id
    while True:
        csrf, _ = fetch_csrf(cookie)
        req = urllib.request.Request(
            f"{BASE}/contestant/benchmark_jobs/{job}",
            headers={"Cookie": cookie, "Accept": "text/html"},
        )
        with urllib.request.urlopen(req, timeout=30) as res:
            html = res.read().decode("utf-8", "replace")
        if any(s in html for s in ("FINISHED", "ERRORED", "CANCELLED")):
            for s in ("FINISHED", "ERRORED", "CANCELLED", "Passed", "FAILED", "合格", "不合格"):
                if s in html:
                    print("hit", s)
            nums = re.findall(r">(\d{3,6})<", html)
            print("nums", nums[:10])
            return
        print(f"job {job} still running…")
        time.sleep(args.interval)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--cookie")
    p.add_argument("--cookie-file", default=str(DEFAULT_COOKIE))
    p.add_argument("--sync", action="store_true", help="refresh cookie from Chrome first")
    sub = p.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("sync-cookie")
    sc.set_defaults(func=cmd_sync)
    s = sub.add_parser("status")
    s.set_defaults(func=cmd_status)
    e = sub.add_parser("enqueue")
    e.add_argument("--target-id", type=int, required=True)
    e.set_defaults(func=cmd_enqueue)
    w = sub.add_parser("wait")
    w.add_argument("job_id", type=int)
    w.add_argument("--interval", type=float, default=15)
    w.set_defaults(func=cmd_wait)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
