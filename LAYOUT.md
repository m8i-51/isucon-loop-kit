# Layout

Single home for ISUCON tooling: **this repo**.

- `isuctl` — laptop loop (discover → sync/pull/analyze/pack) and the thin wrapper for deploy / check / provision. Those three call `ansible-playbook`; they do not rsync the app tree.
- `ansible/` — playbooks that wrapper runs (init / deploy / check). Contract: `ansible/AGENTS.md`.
- `docs/dayof/` — contest-day notes
- `~/isu_work-2026/` — 2026 contest scratch only (do not merge into kit)

Do not create sibling kits under `~/isucon-*` or `Projects/isucon-*` without putting them here first.

- `docs/lessons-2026.md` — reusable lessons distilled from 2026 (not the raw contest log)
