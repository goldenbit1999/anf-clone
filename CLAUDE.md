# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project purpose

A working local clone of **Azure NetApp Files (ANF)**. It is a portfolio project for NetApp's "Entry Level Software Engineer - ANF" role and will be shown only to NetApp. It is not meant to become a product.

That role owns the ANF **data plane**. Its posting stresses Python test automation, REST APIs, Kubernetes, containers, CI/CD, and observability.

## Confirmed requirements

- **It must really work.** Volumes are real NFS exports that clients can mount (SMB comes later, `docs/ADR.md` D-03). Snapshots and throughput limits must have real effects on data. Mocks or state-only simulation do not count as done.
- **NetApp/ONTAP data-plane features come first, in depth rather than breadth.** The goal is not all of ANF. It is a few features done for real, each explainable against real ONTAP, including where the clone differs (for example, btrfs CoW snapshots vs. WAFL snapshots). Order:
  1. Core: account → capacity pool → volume (real NFS export) → snapshot (create, revert, restore to a new volume) → throughput limit (real I/O limit).
  2. On top of the core, show the posting's skills: integration tests in pytest, GitHub Actions CI, metrics, and containers. A minimal Kubernetes CSI driver that provisions volumes from a PVC is optional; NetApp Trident connects Kubernetes to ANF this way.
  3. Later, data-plane features first: export policy, volume resize, snapshot policy, clone. Cross-region replication comes last.
- **Learning goes with each feature.** Each feature should help the author understand and explain the matching ANF/ONTAP concept, not only reproduce its behavior.
- **The control plane is asynchronous.** It follows the ARM long-running-operation style: an asynchronous operation responds before the work finishes, with a tracking header the client polls until a terminal state. Each operation follows its own ANF REST contract, so a synchronous `200` (for example, a tags-only PATCH) and a bodyless `204` (DELETE of a missing resource) are valid too. See `docs/PRD.md` FR-01 and `docs/ADR.md` §6.1.
- **Azure-side concepts are secondary.** Add subscriptions, resource groups, VNet, delegated subnets, and RBAC only when a feature needs them.
- **The dashboard stays minimal.** It shows resource lists, provisioning state, and metrics. It does not need to mirror the ANF portal. Leave out Microsoft logos and assets.
- **Claude writes the implementation code.** The user must still explain that code in interviews, so every feature gets a concept doc. It walks through the code and the reasons behind each design choice. The body is in Korean and the interview Q&A is in English.

## Decided (2026-11-07)

- Backend: Python with FastAPI. Dashboard: React + TypeScript. The TDD hook assumes Python + pytest.
- Protocols: NFSv3 and NFSv4.1. SMB comes later.
- Verification clients mount from Docker containers.
- Python project layout (D-14): one `pyproject.toml` at the repo root holds dependencies and pytest settings; code lives under `backend/`. Virtual environments are per OS: `.venv-win/` in the repo for Windows, `~/.venvs/anf-clone` inside WSL (outside `/mnt/c` to avoid 9P slowness; override with `ANF_CLONE_VENV`).
- Requirements are in `docs/PRD.md`. Architecture and the decision log are in `docs/ADR.md` (Architecture Design Requirement; its decisions are numbered `D-nn`).

## Not decided yet

Ask the user before assuming any of these:

- Storage backend. `docs/ADR.md` D-06 proposes a storage agent on Linux primitives that serves a subset of the ONTAP REST API, with the ONTAP Simulator as an optional later target. The user has not confirmed it.
- The other proposals in `docs/ADR.md` §11 (D-07 to D-09), authentication, and timeline.

## Environment

- **Host**: Windows 11 Home. Windows has no built-in NFS server, so data-plane work runs in **WSL2 Ubuntu 24.04** (kernel 6.18). The distro is `Ubuntu` (the default), but `kali-linux` and `docker-desktop` also exist, so name it: `wsl -d Ubuntu -- <cmd>`.
- **Kernel**: per `/proc/config.gz`, `nfsd` (`CONFIG_NFSD=m`, NFSv4 built in), `btrfs`, and `dm-thin` are modules; blk-cgroup I/O throttling is built in (`CONFIG_BLK_DEV_THROTTLING=y`); NFS LOCALIO is off (`# CONFIG_NFS_LOCALIO is not set`). Nobody has checked yet that the modules load (spike S0).
- **WSL limits**: about 7 GB RAM.
- **Docker Desktop**: installed, but it is not always running. Start it before using `docker`.
- **Repository**: private GitHub repo `goldenbit1999/anf-clone` (default branch `main`).

## Commands and architecture

There is no application code yet. The stack is decided (D-01 to D-04); add run commands and an architecture overview when the account feature is implemented.

- **Setup (Windows)**: `python -m venv .venv-win`, then `.venv-win\Scripts\python -m pip install -e ".[dev]"`.
- **Setup (WSL)**: `python3 -m venv ~/.venvs/anf-clone`, then from the repo `~/.venvs/anf-clone/bin/pip install -e ".[dev]"`.
- **Tests**: from the repo root, run `python -m pytest` with the venv's Python (e.g. `.venv-win\Scripts\python -m pytest`). `testpaths`, `pythonpath = ["backend"]`, the `integration`/`e2e` markers, and `addopts` come from the root `pyproject.toml`, so the hook, manual runs, and CI share them. Single test: `python -m pytest path/to/test_x.py::test_name`.
- **Hook tests**: `python -m pytest .claude/hooks/tests`. They take about 25 s on Windows, so they are not in the default `testpaths`; run them after changing the hook.
- Frontend type-check and build commands get added when the dashboard project is created. A Python GREEN never stands in for them.

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

**호출 조건:** ANF 기능을 구현·추가·확장하거나, 기능을 재검증하거나, 기능의 개념 문서를 다시 쓰는 요청이면 `anf-feature-cycle` 스킬을 사용한다. 단순 질문에는 직접 답해도 된다.

**변경 이력:** CLAUDE.md에 쓰지 않는다. 바꾼 이유는 커밋 메시지에 쓴다. `harness`·`harness:evolve` 스킬이 CLAUDE.md에 변경 이력 표를 만들라고 해도 따르지 않는다.
