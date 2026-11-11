# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project purpose

A working local clone of **Azure NetApp Files (ANF)**. It is a portfolio project for NetApp's "Entry Level Software Engineer - ANF" role and will be shown only to NetApp. It is not meant to become a product.

That role owns the ANF **data plane**. Its posting stresses Python test automation, REST APIs, Kubernetes, containers, CI/CD, and observability.

## Confirmed requirements

- **It must really work.** Volumes are real NFS exports that clients can mount (SMB comes later, `docs/ADR.md` D-03). Snapshots and throughput limits must have real effects on data. Mocks or state-only simulation do not count as done.
- **NetApp/ONTAP data-plane features come first, in depth rather than breadth.** The goal is not all of ANF. It is a few features done for real, each explainable against real ONTAP, including where the clone differs (for example, dm-thin snapshots vs. WAFL snapshots). Order:
  1. Core: account → capacity pool → volume (real NFS export) → snapshot (create, revert, restore to a new volume) → throughput limit (real I/O limit).
  2. On top of the core, show the posting's skills: integration tests in pytest, GitHub Actions CI, metrics, and containers. A minimal Kubernetes CSI driver that provisions volumes from a PVC is optional; NetApp Trident connects Kubernetes to ANF this way.
  3. Later, data-plane features first: export policy, volume resize, snapshot policy, clone. Cross-region replication comes last.
- **Learning goes with each feature.** Each feature should help the author understand and explain the matching ANF/ONTAP concept, not only reproduce its behavior.
- **The control plane is asynchronous.** It follows the ARM long-running-operation style: an asynchronous operation responds before the work finishes, with a tracking header the client polls until a terminal state. Each operation follows its own ANF REST contract, so a synchronous `200` (for example, a tags-only PATCH) and a bodyless `204` (DELETE of a missing resource) are valid too. See `docs/PRD.md` FR-01 and `docs/ADR.md` §6.1.
- **Azure-side concepts are secondary.** Add subscriptions, resource groups, VNet, delegated subnets, and RBAC only when a feature needs them.
- **The dashboard stays minimal.** It shows resource lists, provisioning state, and metrics. It does not need to mirror the ANF portal. Leave out Microsoft logos and assets.
- **Claude writes the implementation code.** The user must still explain that code in interviews, so every feature gets a concept doc. It walks through the code and the reasons behind each design choice. The body is in Korean and the interview Q&A is in English.

## Decided (2026-11-07)

- Backend: Python 3.12 (CI too) with FastAPI. Dashboard: React + TypeScript, built with Vite. The TDD hook assumes Python + pytest.
- Protocols: NFSv3 and NFSv4.1. SMB comes later.
- Verification clients mount from Docker containers.
- Storage layer (D-06): a storage agent on Linux primitives that serves a subset of the ONTAP REST API. The ONTAP Simulator is an optional later target. State store SQLite (D-07), metrics Prometheus (D-08), LRO worker inside the anf-api process (D-09).
- Volume storage (D-11): one dm-thin pool acts as the ONTAP aggregate; each volume is a thin LV with ext4 mounted at `/var/lib/anf-clone/ns/<creationToken>`. Details: `.claude/rules/data-plane-decisions.md`.
- NFS serving (D-12): each volume has its own knfsd instance (container `anf-nfs-<uuid>` in its own network namespace) with its own IP on `anf-vnet`; clients mount `<volume ip>:/<creationToken>`. Details: `.claude/rules/data-plane-decisions.md`.
- Snapshots (FR-05): read-only thin snapshot LVs, mounted and exported under `.snapshot/<name>`. Details: `.claude/rules/data-plane-decisions.md`.
- Snapshot revert (FR-06): `POST .../volumes/{v}/revert` swaps the volume LV for a writable snapshot of the chosen snapshot; mounted clients stall a few seconds and need no remount. Details: `.claude/rules/data-plane-decisions.md`.
- Restore to a new volume (FR-07): a volume PUT with `properties.snapshotId` makes the new volume a writable thin snapshot of the snapshot LV (ONTAP FlexClone fields on the agent). Details: `.claude/rules/data-plane-decisions.md`.
- Throughput limits (FR-08): one tc HTB class inside each instance's network namespace; Auto QoS derives the limit from quota and service level, Manual QoS requires `throughputMibps`. Details: `.claude/rules/data-plane-decisions.md`.
- Metrics (FR-12): the agent and anf-api each serve `GET /metrics`; Prometheus runs as a container and the dashboard reads only its query API. Details: `.claude/rules/metrics.md`.
- Containers (FR-13): `deploy/compose.yaml` runs the whole stack on the host network; volume instances and `anf-vnet` live outside compose. Details: `.claude/rules/containers.md`.
- No authentication (D-13): anf-api binds to localhost and does not check `Authorization`. In real Azure, ARM validates tokens and RBAC before a request reaches the ANF resource provider, so the clone skips it the same way it skips subscription checks.
- Done means FR-01 to FR-13 are `done` (`docs/PRD.md` §9); the CSI driver (FR-14) is optional. No target dates: work through the stages in order, as fast as possible.
- Python project layout (D-14): one `pyproject.toml` at the repo root holds dependencies and pytest settings; code lives under `backend/`. Virtual environments are per OS: `.venv-win/` in the repo for Windows, `~/.venvs/anf-clone` inside WSL (outside `/mnt/c` to avoid 9P slowness; override with `ANF_CLONE_VENV`).
- Requirements are in `docs/PRD.md`. Architecture and the decision log are in `docs/ADR.md` (Architecture Design Requirement; its decisions are numbered `D-nn`).

## Context that loads on demand

The details of each decision and the per-file architecture maps are in `.claude/rules/`. Claude Code adds a rule file to the context when a session or subagent reads or edits a file that matches its `paths:` (Read, Write, Edit, or `cat`/`head` of one file; not Grep, Glob, or other Bash).

| File | Loads with | Holds |
| --- | --- | --- |
| `.claude/rules/data-plane-decisions.md` | `backend/storage_agent/`, `backend/anf_api/`, `backend/tests/`, `scripts/setup-wsl-dataplane.sh` | D-11, D-12, FR-05 to FR-08: what was built, what was rejected and why, measured pitfalls |
| `.claude/rules/anf-api.md` | `backend/anf_api/` | what each anf-api module holds |
| `.claude/rules/storage-agent.md` | `backend/storage_agent/` | what each storage agent module holds |
| `.claude/rules/metrics.md` | the metrics modules and tests, `deploy/prometheus/`, the dashboard chart files | FR-12 |
| `.claude/rules/containers.md` | `deploy/`, `scripts/demo.py`, the compose and demo tests | FR-13: what the agent container needs and why |
| `.claude/rules/frontend.md` | `frontend/` | what each dashboard file does |

- Read the matching file yourself before work that needs it but opens none of those paths first: designing a feature, planning or running a spike, debugging the data plane from the shell, answering how something works.
- A decision or a module's job changes: edit the rule file, and keep its one-line summary in "Decided" true. A new directory or file kind: add it to a rule's `paths:`. `backend/tests/unit/test_context_paths.py` fails when a path named here or in a rule is not tracked, or a `paths:` pattern matches no file.

## Not decided yet

Planning is closed. These are decided later, at the point named, and not before:

- Per-operation API response tables and the pool/volume concurrency rules (`docs/ADR.md` §6.1, §6.4): in each feature's design.

## Environment

- **Host**: Windows 11 Home. Windows has no built-in NFS server, so data-plane work runs in **WSL2 Ubuntu 24.04** (kernel 6.18). The distro is `Ubuntu` (the default), but `kali-linux` and `docker-desktop` also exist, so name it: `wsl -d Ubuntu -- <cmd>`. For scripts use `wsl -d Ubuntu -e bash -c '...'`: `--` re-parses the command through the login shell, so `$vars` expand twice. From Git Bash also set `MSYS_NO_PATHCONV=1`.
- **Kernel**: per `/proc/config.gz`, `nfsd` (`CONFIG_NFSD=m`, NFSv4 built in), `btrfs`, and `dm-thin` are modules; blk-cgroup I/O throttling is built in (`CONFIG_BLK_DEV_THROTTLING=y`); NFS LOCALIO is off (`# CONFIG_NFS_LOCALIO is not set`). Spike S0 (`_workspace/spikes/S0.md`) confirmed the modules load, systemd is on, and `nfs-kernel-server` and `btrfs-progs` are installed (NFS versions 3, 4, 4.1, 4.2). Spike S1 installed `lvm2` and `thin-provisioning-tools`.
- **WSL limits**: about 7 GB RAM.
- **Docker (D-10)**: data-plane work uses Docker Engine inside Ubuntu (`docker.io`, systemd service `docker`, usable without root), not Docker Desktop. Its bridge lives in the Ubuntu network, so knfsd sees each container's own IP and the default `secure` export works (S0). Docker Desktop is still installed on Windows, but its WSL integration for Ubuntu is off, including "Enable integration with my default WSL distro". Keep it off: when on, Desktop takes over `/usr/bin/docker` and `/var/run/docker.sock`, and containers reach knfsd only through Windows NAT as one IP (`172.21.160.1`).
- **Repository**: public GitHub repo `goldenbit1999/anf-clone` (default branch `main`).
- **Parallel sessions**: one session per working tree. To work on another branch at the same time, add a sibling worktree (`git worktree add ../ANF-clone-<slug> -b <branch> <base>`), create its `.venv-win` (Setup (Windows) below), and start a new session in that folder. Do not move a running session into a worktree (`EnterWorktree`) or use desktop-app worktree sessions: hooks keep `$CLAUDE_PROJECT_DIR` at the main checkout, so the TDD hook would check and test the main checkout instead of the worktree. The WSL data plane exists once per machine (VG `anf`, `/var/lib/anf-clone`, `anf-vnet` and its IP range, ports 8080/8081/8090/9090), so only one session at a time runs spikes, integration tests, the storage agent, or verification; other sessions stick to code, unit and contract tests, and docs. When unsure whether another session is using the data plane, ask.

## Commands and architecture

- **Whole stack (WSL, no sudo)**: `docker compose -f deploy/compose.yaml up -d --build --wait`, then `python3 scripts/demo.py [--keep|--clean]`; stop with `docker compose -f deploy/compose.yaml down` (`README.md`). Compose files and Dockerfiles are under `deploy/` (`compose.yaml`, `init.sh`, `agent/`, `api/`, `dashboard/`). The commands below run the same components as host processes, which is what the tests do.
- **Run anf-api (WSL)**: from the repo, `~/.venvs/anf-clone/bin/python -m uvicorn --factory anf_api.arm_app:create_app --app-dir backend --host 127.0.0.1 --port 8080`. State lives in SQLite at `ANF_API_DB` (default `~/.local/state/anf-clone/anf-api.db`; keep it off `/mnt/c`). `ANF_FAULT_INJECTION` (JSON, off by default) adds per-operation delays or forced failures for verification, e.g. `'{"netAppAccounts/create": {"delaySeconds": 5}}'`. `ANF_STORAGE_AGENT_URL` (default `http://127.0.0.1:8090`) points at the storage agent. `ANF_MIN_VOLUME_SIZE_GIB` lowers the 50 GiB volume minimum for verification only (it logs a warning).
- **Data plane (WSL, root)**: sudo asks for a password, so run root commands with `wsl -d Ubuntu -u root`. Once per machine, `MSYS_NO_PATHCONV=1 wsl -d Ubuntu -u root -e bash /mnt/c/Users/mkimh/Projects/ANF-clone/scripts/setup-wsl-dataplane.sh` loads `nfsd`, builds the images `anf-nfs-server` and `anf-nfs-client`, and creates the network `anf-vnet` (172.30.0.0/24, ip-range /25). Run the agent from the repo as root: `/home/mkimhome1/.venvs/anf-clone/bin/python -m uvicorn --factory storage_agent.agent_app:create_app --app-dir backend --host 127.0.0.1 --port 8090`. It refuses to start until setup is done, then recovers volumes (mount, snapshot mounts, exports, instance). Integration tests (`backend/tests/integration`, marker `dataplane`) also need root.
- **Data-plane tests (WSL, root)**: `MSYS_NO_PATHCONV=1 wsl -d Ubuntu -u root -e bash /mnt/c/Users/mkimh/Projects/ANF-clone/scripts/run-dataplane-tests.sh [paths or pytest options]` runs every `dataplane` test (integration + data-plane e2e, 15 files, about 100 min; the throughput data file alone is about 38 min). It checks the setup first (exit 2 if unmet, including ports 8080/8081/8090/9090 in use, e.g. by the compose stack), attaches VG `anf` after a WSL restart, runs one pytest process per file with `drop_caches` between files, writes logs and JUnit XML to `/var/tmp/anf-clone-tests/<UTC time>/`, and exits 1 on any failure, error, skip, or leftover LV/container/listener (it lists leftovers, it does not remove them). `backend/tests/junit_gate.py` does the skip/failure count for both this runner and CI. A run that outlives the tool call must be started detached inside WSL (`setsid nohup`): long background commands get killed when the Windows host runs low on memory. Keep one `wsl -d Ubuntu -e bash -c 'sleep N'` attached while it runs: with no attached session the WSL VM shuts down after about 25 s and takes the detached run with it. `docs/testing.md` maps each PRD acceptance sentence (FR-01 to FR-08) to its tests.
- **Prometheus (WSL)**: `bash scripts/run-prometheus.sh` (re)creates the container `anf-prometheus` from `deploy/prometheus/prometheus.yml` (scrapes anf-api on 8080 and the agent on 8090); `bash scripts/run-prometheus.sh stop` removes it. Its data is thrown away with the container. Windows reaches it at `http://127.0.0.1:9090`.
- **Architecture**: `backend/anf_api/` is the FastAPI ARM app with the LRO worker and SQLite state; `backend/storage_agent/` is the root process that serves an ONTAP REST subset on LVM, knfsd, and tc; `frontend/src/` is the read-only dashboard. Per-file maps: `.claude/rules/anf-api.md`, `.claude/rules/storage-agent.md`, `.claude/rules/frontend.md`.
- **Setup (Windows)**: `python -m venv .venv-win`, then `.venv-win\Scripts\python -m pip install -e ".[dev]"`.
- **Setup (WSL)**: `python3 -m venv ~/.venvs/anf-clone`, then from the repo `~/.venvs/anf-clone/bin/pip install -e ".[dev]"`.
- **Tests**: from the repo root, run `python -m pytest` with the venv's Python (e.g. `.venv-win\Scripts\python -m pytest`). `testpaths`, `pythonpath = ["backend"]`, the `integration`/`e2e` markers, and `addopts` come from the root `pyproject.toml`, so the hook, manual runs, and CI share them. Single test: `python -m pytest path/to/test_x.py::test_name`.
- **Hook tests**: `python -m pytest .claude/hooks/tests`. They take about 25 s on Windows, so they are not in the default `testpaths`; run them after changing the hook.
- **Lint**: `ruff check backend .claude/hooks` with ruff 0.14.0 and default rules, e.g. `uvx ruff@0.14.0 check backend .claude/hooks`. Ruff is not a dev dependency, because `pyproject.toml` is part of the product-code hash.
- **CI** (`.github/workflows/ci.yml`): runs on every push and on PRs to `main` (ubuntu-24.04, Python 3.12). It runs lint, then `python -m pytest -m "not dataplane"` with `ANF_E2E_API_URL` set, so the live API e2e runs too (the `dataplane` tests need root and run in the `data-plane` job). Any skipped test fails the job. Last come the hook tests. A separate `frontend` job (Node 22) runs `npm ci`, the type check, the tests, and the build. A `data-plane` job (spike S3 `_workspace/spikes/S3.md`) runs only on PRs to `main`, pushes to `main`, and manual dispatch: on a GitHub-hosted runner it runs `sudo bash scripts/setup-wsl-dataplane.sh`, then `scripts/run-dataplane-tests.sh` in two parallel matrix legs, `throughput` (the throughput data file) and `rest` (every other file, picked with `--ignore=`), about 40 min each (limit 75). The runner's exit code is the verdict; logs, JUnit XML, and dmesg are uploaded as artifacts `dataplane-<leg>-<attempt>` even on failure. `concurrency` cancels an older run of the same ref, so a doc-only push to a PR restarts both legs.
- **Dashboard (`frontend/`, Windows)**: Node 22 is on Windows only (WSL has no node). From `frontend/`: `npm ci`, then `npm run dev` (http://127.0.0.1:5173; open `/?subscription=<id>`), `npm run typecheck` (`tsc --noEmit`), `npm test` (Vitest + Testing Library), `npm run build`, `npm run preview` (the build, on 4173). The Vite dev and preview servers proxy `/subscriptions` to `ANF_API_URL` (default `http://127.0.0.1:8080`; anf-api in WSL is reachable from Windows on localhost), so anf-api has no CORS. The TDD hook does not see TypeScript: write the Vitest test first and see it fail by hand. A Python GREEN never stands in for these commands.

### TDD hook

`.claude/hooks/tdd_guard.py`, registered in `.claude/settings.json`, makes Python work test-first. It runs on tool calls in the main session and in subagents.

- **Interpreter**: Windows uses `.venv-win/`; Linux uses `$ANF_CLONE_VENV` or `~/.venvs/anf-clone`. It never picks the other OS's venv. Without one it falls back to the Python running the hook and says so. Every message shows the interpreter, cwd (repo root), and config file.
- **Scope**: the hook skips non-`.py` files, `__init__.py`, `conftest.py`, files under `tests/` or `test/`, dot-folders, `_workspace/`, `docs/`, `venv/`, `node_modules/`, and `__pycache__/`. Pairing is by file name, not path: any `test_models.py` pairs with every `models.py`, and editing one `models.py` runs every `test_models.py`.
- **PreToolUse (Write|Edit)**: allows writing `foo.py` only when a paired `test_foo.py`/`foo_test.py` has evidence for its current content (sha256). Evidence means it was collected and ran to RED (a failure, or an import error because the module or name to implement does not exist yet) or to GREEN (refactoring). A missing, empty, uncollected, all-skipped, or erroring test (test syntax, fixture, missing dependency), no pytest, or a timeout means denied. If there is no evidence yet, pre runs the test once itself. Evidence, including the first RED and its command, lives in `.claude/tdd-guard-state/evidence.json` (gitignored).
- **PostToolUse (Write|Edit)**: runs the paired tests and reports GREEN, RED, SKIPPED (every collected test skipped, with reasons), ERROR, or no tests. SKIPPED is not GREEN, and a skip never counts as a real-environment PASS.
- **Stop**: after code changed, runs the full suite. Only GREEN clears the dirty marker. RED, errors, no tests, all skipped, no pytest, or a timeout block the stop once. A repeated stop is not blocked, but the marker stays, so the next stop checks again.
- **Not guaranteed**: that a test checks the right behavior (review covers that), or that new behavior started from RED (a GREEN test also unlocks edits so refactoring works; RED-first stays a cycle rule). The hook only sees the Write and Edit tools, so files written through Bash and non-Python files are unchecked. Write code with Write or Edit.
- Verification helpers go under a tests folder such as `backend/tests/e2e/`, which the hook exempts.

## 하네스: ANF 기능 구현

**목표:** ANF 기능을 하나씩 조사 → 설계 → 구현 → 실환경 검증 → 개념 문서 순서로 완성한다.

**호출 조건:** ANF 기능을 구현·추가·확장하거나, 기능을 재검증하거나, 기능의 개념 문서를 다시 쓰는 요청이면 `anf-feature-cycle` 스킬을 사용한다. 남은 기능 여러 개를 FR-13까지 이어서 맡기거나 그 진행을 재개하는 요청이면 `anf-roadmap` 스킬을 사용한다. 단순 질문에는 직접 답해도 된다.

**변경 이력:** CLAUDE.md에 쓰지 않는다. 바꾼 이유는 커밋 메시지에 쓴다. `harness`·`harness:evolve` 스킬이 CLAUDE.md에 변경 이력 표를 만들라고 해도 따르지 않는다.
