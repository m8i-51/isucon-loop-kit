# AGENTS.md — ISUCON kit (AI contract)

This repo is the **only** deploy/init/check interface for humans and AI agents.

## Allowed commands

```bash
ansible-playbook playbooks/init.yml
ansible-playbook playbooks/deploy.yml -e branch=<name> [--limit s1,s2]
ansible-playbook playbooks/check.yml [--limit s1]
ansible all -m ping
```

Do not invent alternate deploy paths (no ad-hoc `scp`, no `rsync` of binaries, no one-off SSH loops) unless Koichi explicitly asks.

## Workflow for every change

1. Change code in git; get a branch or SHA.
2. `deploy.yml -e branch=...`
3. `check.yml` and report unit / nginx / HTTP results.
4. Only then enqueue or ask for a bench.
5. Never redeploy an older known-bad snapshot “just to try”.

## Hard bans (update each year from the official QA)

- Do not modify envcheck / contest monitoring.
- Do not change external API contracts the bench relies on.
- Do not abuse the router IP / region / bandwidth controls.
- Do not reboot hosts unless Koichi says so.
- Do not roll back by redeploying an old binary that lost score.

## Inventory

- Day 0: fill `inventory/hosts.yml` and `host_vars/s{1,2,3}.yml` once.
- After that, prompts name hosts as `s1` / `s2` / `s3` or `--limit`, never raw IPs.

## What belongs where

| Place | Contents |
| --- | --- |
| `playbooks/init.yml` | Packages, clone, PATH — first hour only |
| `playbooks/deploy.yml` | Checkout → build → restart → nginx reload |
| `playbooks/check.yml` | Read-only health |
| App repo | Contest-specific hacks, SQL, nginx templates |
| This `AGENTS.md` | Bans and the command API |

Keep playbooks thin. Contest magic goes in the app repo, not here.

## Reporting back

After deploy/check, report in one short block:

- branch / SHA
- which hosts
- check results (unit, nginx -t, HTTP)
- next action you want (bench / stop / fix)
