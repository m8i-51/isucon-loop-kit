# AGENTS.md

Laptop loop and deploy contract for this repo.

## Deploy / init / check

Do not deploy with ad-hoc `rsync`, `scp`, or one-off SSH copy loops.

Preferred entry, from a directory that contains `ansible/playbooks` (the kit root or a subdirectory):

```bash
isuctl deploy --branch <name-or-sha> [--limit s1,s2]
isuctl check [--limit s1]
isuctl provision [--limit s1,s2]
```

`isuctl` is a thin wrapper. It runs `ansible-playbook` with cwd `ansible/` against `playbooks/deploy.yml`, `check.yml`, and `init.yml`. Raw `ansible-playbook` is allowed and is what those commands call. The deploy playbook checks out `branch` from `repo_url`; push the ref before deploying.

Hard bans, inventory rules, and the report format: [`ansible/AGENTS.md`](ansible/AGENTS.md).

## Loop (not deploy)

`isuctl` still owns the laptop loop:

`discover` → `sync-down` → edit in git → deploy (above) → `check` → bench → `pull` → `analyze` → `pack` → `bench-note`

`rollback` resets the local worktree (`--ref`, default `HEAD~1`), then deploys that SHA through the same ansible path.

Layout: [`LAYOUT.md`](LAYOUT.md).
