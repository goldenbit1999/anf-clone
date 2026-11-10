# ANF clone

A local, working clone of the Azure NetApp Files data plane. Volumes are real NFS exports (NFSv3 and NFSv4.1) that
clients mount; snapshots, revert, restore to a new volume, and throughput limits act on real data. The control plane
is an ARM-style asynchronous REST API. Requirements are in [docs/PRD.md](docs/PRD.md), the architecture in
[docs/ADR.md](docs/ADR.md), and how each feature maps to ANF and ONTAP in [docs/concepts/](docs/concepts/).

## Requirements

- WSL2 Ubuntu 24.04 (or another Linux host with the `nfsd` and `dm-thin` kernel modules), about 7 GB of memory.
- Docker Engine inside that Linux (`docker.io`), with the `docker compose` and `docker buildx` plugins. On WSL, keep
  Docker Desktop's integration for the distro off.
- Your user in the `docker` group. No sudo is needed: a privileged one-shot container prepares the host.

## Start

From the repository root, inside WSL:

```bash
docker compose -f deploy/compose.yaml up -d --build --wait
```

The first run builds the images and takes about a minute; later runs take seconds. The command returns when every
service is healthy. After a WSL restart, run the same command again.

| Service | Address (127.0.0.1 only) | What it is |
| --- | --- | --- |
| `anf-api` | http://127.0.0.1:8080 | ARM-style API (`Microsoft.NetApp`, api-version `2026-08-01`) |
| `dashboard` | http://127.0.0.1:8081/?subscription=&lt;id&gt; | Resource tree, provisioning state, and metric charts |
| `storage-agent` | http://127.0.0.1:8090 | ONTAP REST subset on LVM thin volumes, one knfsd instance per volume |
| `prometheus` | http://127.0.0.1:9090 | Metrics from `anf-api` and the storage agent |
| `init` | (runs once) | Loads kernel modules, builds the NFS server and client images, creates the `anf-vnet` network |

A Windows browser reaches these addresses through WSL's localhost forwarding.

## Run the demo

```bash
python3 scripts/demo.py
```

It replays the demo scenario in about a minute and a half: account, capacity pool, and NFSv3 and NFSv4.1 volumes; mounts and
writes from client containers; a snapshot and reading a deleted file from `.snapshot`; revert; restore to a new volume;
measured write throughput that follows a limit change; and the same load in Prometheus and through the dashboard. Each
step prints what the client saw. The limit is a ceiling: the throughput step fails if a run goes above 101% of its
limit plus one 1 MiB I/O in the 6 s window (fio counts finished I/Os, so one completion can land in the next run), or
if the measured throughput does not drop with the limit. A run slower than the limit only gets a note, because the
storage sometimes writes below the limit for a few seconds. It removes what it created when it ends. Exit code 0
means every step passed, 1 means a step failed (the output names it), and 2 means the stack is not running.

To look at the result in the dashboard, keep the resources, open the printed address, and remove them afterwards:

```bash
python3 scripts/demo.py --keep
# http://127.0.0.1:8081/?subscription=de300000-0000-4000-8000-000000000013
python3 scripts/demo.py --clean
```

## Stop

```bash
docker compose -f deploy/compose.yaml down
```

Volume instances (`anf-nfs-<uuid>` containers) are started by the storage agent, not by compose, so they keep serving
mounted clients while the stack is down; the next `up` picks them up again. Delete resources through the API (or
`demo.py --clean`) to remove them. `down -v` also deletes the API's state, so use it only when no resources are left.

## Tests

```bash
python -m pytest          # unit, contract, and control-plane tests (any OS, from the repo venv)
```

Stop the stack before the data-plane tests: they start their own storage agent and API on the same ports, and
`scripts/run-dataplane-tests.sh` refuses to start while ports 8080, 8081, 8090, or 9090 are in use. Commands, layers,
and the acceptance-criteria map are in [docs/testing.md](docs/testing.md).
