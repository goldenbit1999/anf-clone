# ANF clone

A local, working clone of the Azure NetApp Files data plane. Volumes are real NFS exports (NFSv3 and NFSv4.1) that
clients mount; snapshots, revert, restore to a new volume, and throughput limits act on real data. The control plane
is an ARM-style asynchronous REST API. Requirements are in [docs/PRD.md](docs/PRD.md), the architecture in
[docs/ADR.md](docs/ADR.md), and how each feature maps to ANF and ONTAP in [docs/concepts/](docs/concepts/).

The goal is depth, not breadth: a few ANF data-plane features built for real on Linux primitives, each verified from an
NFS client and explained against ONTAP, including where the clone differs. Mocks and state-only simulation did not
count as done.

## What works

Every feature below is `done` in [docs/feature-status.md](docs/feature-status.md). Each was built test-first, verified
in the real environment against its acceptance criteria, and written up in a concept doc.

| FR | Feature | What a client or caller observes | Concept doc |
| --- | --- | --- | --- |
| FR-01, FR-02 | Async operations (ARM LRO), NetApp account | `201`/`202` before the work finishes, then `Azure-AsyncOperation` or `Location` polling to `Succeeded` or `Failed`; unfinished operations resume after a restart | [netapp-account](docs/concepts/netapp-account.md) |
| FR-03 | Capacity pool | Service level and Auto/Manual QoS set the throughput budget; a volume that would overfill the pool is rejected | [capacity-pool](docs/concepts/capacity-pool.md) |
| FR-04 | Volume (NFS) | Mount `<mount IP>:/<creationToken>` over NFSv3 or NFSv4.1 and read and write; writes past the quota fail with `ENOSPC`; a deleted volume no longer mounts | [volume](docs/concepts/volume.md) |
| FR-05 | Snapshot | A deleted file is readable under `.snapshot/<name>/`; files there cannot be changed | [snapshot](docs/concepts/snapshot.md) |
| FR-06 | Revert to a snapshot | The volume returns to the snapshot's content; mounted clients stall a few seconds and need no remount | [snapshot-revert](docs/concepts/snapshot-revert.md) |
| FR-07 | Restore to a new volume | The new volume has the snapshot's content; writing to it leaves the source volume and snapshot unchanged | [restore-new-volume](docs/concepts/restore-new-volume.md) |
| FR-08 | Throughput limit | Measured client throughput stays under the Auto or Manual QoS limit and follows a limit change | [throughput-limit](docs/concepts/throughput-limit.md) |
| FR-09 | Dashboard | Resource tree whose `provisioningState` updates without a reload | [dashboard](docs/concepts/dashboard.md) |
| FR-10 | Test automation | One command runs the data-plane suite on the real kernel; a skip counts as a failure | [test-automation](docs/concepts/test-automation.md) |
| FR-11 | CI | GitHub Actions runs lint, unit and contract tests, the dashboard build, and the data-plane suite on a hosted runner | [ci](docs/concepts/ci.md) |
| FR-12 | Metrics | Volume throughput, IOPS, and usage, plus API and operation metrics, in Prometheus and in dashboard charts | [metrics](docs/concepts/metrics.md) |
| FR-13 | Containers | One `docker compose` command starts the stack; `scripts/demo.py` replays the demo scenario | [containers](docs/concepts/containers.md) |

## Architecture

```text
  caller (curl, scripts/demo.py)       dashboard :8081 (React, served by nginx)
          │ ARM REST                          │ ARM REST + Prometheus queries
          ▼                                   ▼
  anf-api :8080        FastAPI: ARM routes, LRO worker, SQLite state
          │ ONTAP-shaped REST: /api/storage/volumes, .../snapshots, /api/cluster/jobs
          ▼
  storage agent :8090  root process: LVM, one NFS server instance per volume, tc
          ├─ dm-thin pool "aggr0"                              stands in for the aggregate
          │    ├─ thin LV + ext4 per volume                    FlexVol
          │    └─ read-only thin snapshot LVs                  Snapshot copies
          └─ container anf-nfs-<uuid> per volume               data LIF + NFS service
               own network namespace and IP on anf-vnet,
               knfsd (NFSv3 or NFSv4.1), tc HTB limit          QoS policy (max throughput)
                         ▲
                         │ mount <volume IP>:/<creationToken>
               NFS client containers

  Prometheus :9090 scrapes /metrics on anf-api and the storage agent.
```

The stand-ins reproduce what a client sees, not ONTAP internals:

| ANF or ONTAP | In this clone |
| --- | --- |
| NetApp account, capacity pool | Control-plane records only. No public source maps them to an ONTAP object, so they create nothing on the storage side |
| Aggregate | One dm-thin pool on a sparse file (VG `anf`, thin pool `aggr0`) |
| FlexVol volume | Thin LV with ext4, mounted at `/var/lib/anf-clone/ns/<creationToken>` |
| Mount target, data LIF | Per-volume IP on the Docker network `anf-vnet`, served by the volume's own knfsd |
| Snapshot copy | Read-only thin snapshot LV, mounted and exported under `.snapshot/<name>` |
| SnapRestore (revert) | Swap the volume LV for a writable snapshot of the chosen snapshot |
| FlexClone (restore to a new volume) | Writable thin snapshot of the snapshot LV; the agent takes ONTAP's `clone.*` fields |
| QoS policy, max throughput | One tc HTB class inside the instance's network namespace |

## Where it differs from ANF and ONTAP

Each concept doc lists every difference with its source and marks guesses as guesses. The ones most worth knowing:

- **dm-thin and ext4, not WAFL.** Snapshots and clones share blocks, so they are created instantly as in ONTAP. But a
  snapshot's space comes out of the thin pool, not the volume's quota, and `.snapshot` exists only at the volume root.
- **One NFS server and IP per volume.** ANF volumes can share a mount IP behind one SVM (inferred). The clone gives
  each volume its own knfsd so it can limit volumes separately: NFSv4.1 clients merge mounts of different IPs on one
  server into one connection, so a shared server cannot tell volumes apart.
- **Throughput is limited on the network path, not in storage.** The HTB class counts wire bytes in both directions,
  divided by 0.9564 for headers. The limit is a ceiling, not isolation: heavy writes by a neighbor on the same
  aggregate still slow a limited volume.
- **Restore to a new volume does not copy.** ANF copies data in the background after the volume exists
  (`cloneProgress`). The clone's new volume is a writable thin snapshot and is independent at once.
- **Revert swaps a block device.** ANF replaces the volume's inode table. The clone blocks the instance's input for
  about 2 s while it swaps LVs; clients stall a few seconds and keep their mounts.
- **Metrics are raw Prometheus counters.** ANF publishes 5-minute averages in Azure Monitor. The clone exports knfsd
  byte and RPC counters and computes rates with `rate()`; it has no latency metrics, because knfsd has no latency
  counters. The concept doc maps each metric to its Azure name.
- **No authentication and no VNet.** ARM checks tokens and RBAC before a request reaches ANF, so the clone binds to
  localhost and skips them (ADR D-13). A subnet ID is checked for format only.
- **Error codes ANF does not document.** Where no recording or document gives the real response, the clone picks one,
  and the concept doc says it is the clone's choice.

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

## CI

[.github/workflows/ci.yml](.github/workflows/ci.yml) runs on every push and on pull requests to `main`: ruff,
`pytest -m "not dataplane"` (including an end-to-end run against a live API), the hook tests, and a dashboard job
(type check, Vitest, build). A skipped test fails the job. On pull requests to `main`, pushes to `main`, and manual runs, a `data-plane` job
prepares a GitHub-hosted runner with the same setup script and runs the whole data-plane suite on its kernel, in two
parallel legs of about 40 minutes each.

## Repository layout

| Path | What it holds |
| --- | --- |
| `backend/anf_api/` | ARM-style API: routes, LRO worker, SQLite state, metrics |
| `backend/storage_agent/` | ONTAP REST subset on LVM, the per-volume NFS server image (`nfs_server/`), tc |
| `backend/tests/` | Unit, contract, integration, and end-to-end tests (the `dataplane` marker needs root) |
| `frontend/` | Dashboard (React, TypeScript, Vite) |
| `deploy/` | Compose stack, Dockerfiles, Prometheus configuration |
| `scripts/` | Host setup, data-plane test runner, Prometheus, demo |
| `docs/` | PRD, ADR (decisions `D-nn`), concept docs, test map, feature status |
| `_workspace/` | Per-feature research briefs, designs, verification reports, and spikes S0–S9 |
| `.claude/` | The development harness: TDD hook, skills, agents, context rules |

## How it was built

The implementation was written with Claude Code inside the harness in `.claude/`:

- Each feature went through one cycle: research the ANF and ONTAP sources, design (decisions and acceptance criteria in
  `_workspace/<feature>/02_main_design.md`), implement test-first, verify in the real WSL2 and Docker environment by
  what clients observe, then write the concept doc.
- Data-plane assumptions that could break a design were tested in spikes first (`_workspace/spikes/`).
- A hook (`.claude/hooks/tdd_guard.py`) refuses an edit to a Python module until its paired test, as currently
  written, has been collected and run to a failure or a pass. After code changes it runs the full suite before a
  session stops.

The concept docs are in Korean with interview Q&A in English. They walk through the code and the reason for each
design choice.

## Status

The planned scope, FR-01 to FR-13 ([PRD §9](docs/PRD.md#9-성공-기준)), is complete. Not built:

- FR-14, a minimal Kubernetes CSI driver (optional; the role NetApp Trident plays for ANF).
- FR-15 to FR-18: export policy, volume resize, snapshot policy, clone from a volume. FR-19: cross-region replication.
- SMB.

Known limits are in [docs/testing.md](docs/testing.md#5-알려진-한계) and in each concept doc's differences section.
