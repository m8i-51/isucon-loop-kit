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

## Compose transport (local practice)

When `isucon.toml` has a `[compose]` table, the same loop targets a local compose project instead of SSH. See [examples/compose](examples/compose/README.md). Ansible playbooks stay the contest-host path and are not invoked for that config. Do not point `[compose]` at contest hosts.

`deploy` archives the requested git ref into `source_dest`, then runs `docker compose build` and `up -d --wait`. Go images bake the binary at build time, so a source edit is live only after that rebuild. Uncommitted files are left out of the image. `bench` runs the configured command with `docker compose run` on the bench service/profile.

macOS Docker Desktop: the published-port proxy RSTs above about 128 concurrent connections (`somaxconn`). Run the bench inside the compose network. A host-side `go run` against the published port drops score at that limit.

Layout: [`LAYOUT.md`](LAYOUT.md).
