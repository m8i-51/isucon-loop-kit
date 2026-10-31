# AGENTS.md — ISUCON kit (AI contract)

Playbooks in this directory are the deploy/init/check implementation. Preferred entry for agents is `isuctl` (it shells out to these playbooks). Raw `ansible-playbook` remains allowed.

## Allowed commands

From the kit root (a directory that contains `ansible/playbooks`):

```bash
isuctl deploy --branch <name-or-sha> [--limit s1,s2]
isuctl check [--limit s1]
isuctl provision [--limit s1,s2]
```

Equivalent raw form, run with cwd `ansible/` (this is what `isuctl` executes):

```bash
ansible-playbook playbooks/init.yml
ansible-playbook playbooks/deploy.yml -e branch=<name> [--limit s1,s2]
ansible-playbook playbooks/check.yml [--limit s1]
ansible all -m ping
```

`deploy` checks out `branch` from `repo_url`. It does not upload the laptop worktree. Push the ref first.

Do not invent alternate deploy paths (no ad-hoc `scp`, no `rsync` of binaries, no one-off SSH loops) unless Koichi explicitly asks.

## Workflow for every change

1. Change code in git and push a branch or SHA that `repo_url` can see.
2. `isuctl deploy --branch ...` (or `deploy.yml -e branch=...`).
3. `isuctl check` (or `check.yml`) and report unit / nginx / HTTP results.
4. Only then enqueue or ask for a bench.
5. Never redeploy an older known-bad snapshot “just to try”.
   `isuctl rollback --ref <git-ref>` resets the local worktree, then deploys that SHA through the same playbook. The SHA still has to exist on `repo_url`.

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

## Lessons

Reusable bans and habits: [`docs/lessons-2026.md`](../docs/lessons-2026.md). Update that file when a new Clar or FAIL teaches something lasting.
