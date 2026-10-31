# ansible/ — AI-safe deploy API

Part of [isucon-loop-kit](../README.md). Contest servers are reached only through these playbooks (or `isuctl`), not ad-hoc `scp` loops.

## Commands

```bash
cd "$(git rev-parse --show-toplevel)/ansible"
ansible-playbook playbooks/init.yml
ansible-playbook playbooks/deploy.yml -e branch=main
ansible-playbook playbooks/check.yml
```

Day-0 inventory: `./scripts/day0-copy-inventory.sh` then edit IPs.

AI contract: [AGENTS.md](./AGENTS.md) (also summarized in repo-root docs).
