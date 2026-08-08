from __future__ import annotations

from isuctl.config import Host


def primary_host(hosts: list[Host]) -> Host:
    if not hosts:
        raise ValueError("config must have at least one host")
    for host in hosts:
        if "app" in host.role:
            return host
    return hosts[0]
