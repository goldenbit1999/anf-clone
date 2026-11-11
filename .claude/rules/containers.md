---
paths:
  - "deploy/**"
  - "scripts/demo.py"
  - "backend/tests/**/test_compose*.py"
  - "backend/tests/unit/test_demo.py"
---

# Containers decisions (FR-13)

- Containers (FR-13, spike S9 `_workspace/spikes/S9.md`): `docker compose -f deploy/compose.yaml up -d --build --wait` starts everything without sudo (the user needs the `docker` group, which is root-equivalent). Services, all on the host network and bound to 127.0.0.1: a one-shot privileged `init` (runs `scripts/setup-wsl-dataplane.sh` in the host namespaces and makes `ns` an rshared bind), `storage-agent` (8090), `anf-api` (8080, non-root, SQLite in a named volume), `prometheus` (9090), and `dashboard` (nginx on 8081: the built SPA plus proxies `/subscriptions` → 8080 and `/prometheus/` → 9090). The agent container needs every one of these (each was a measured failure in S9): `privileged`, `pid: host` (`nsenter -t <pid>`), `network_mode: host`, a non-recursive bind of `/var/lib/anf-clone` (a recursive one leaves a hidden private copy of the volume mounts after an agent restart and revert fails), an `rshared` bind of `ns` (instances must see the volume mounts), `/run/lock/lvm`, `/run/udev:ro` with `ipc: host` (without udev sync a mount can race `lvcreate`; `/run/udev` without host IPC makes `lvcreate` hang for minutes), `/dev`, `/lib/modules:ro`, and the Docker socket (it starts sibling containers). Volume instances and `anf-vnet` live outside compose: `down` leaves them serving, client I/O continues, and the next `up` recovers them; delete resources through the API to remove them. A re-run recreates the four services (`--build` yields a new image ID each time) but not volumes or instances. `scripts/demo.py` (stdlib only, no root) replays the PRD §5 scenario in about 90 s against the stack and removes what it made (`--keep`, `--clean`; exit 2 without the stack). The stack and the data-plane tests share ports 8080/8090/9090 (and 8081), so stop the stack before running tests. Design: `_workspace/containers/02_main_design.md`.
