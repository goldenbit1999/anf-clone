# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project purpose

A working local clone of **Azure NetApp Files (ANF)**. It is a portfolio project for NetApp's "Entry Level Software Engineer - ANF" role and will be shown only to NetApp. It is not meant to become a product.

That role owns the ANF **data plane**. Its posting stresses Python test automation, REST APIs, Kubernetes, containers, CI/CD, and observability.

## Confirmed requirements

- **It must really work.** Volumes are real NFS/SMB exports that clients can mount. Snapshots and throughput limits must have real effects on data. Mocks or state-only simulation do not count as done.
- **NetApp/ONTAP features come first.** The long-term goal is all of ANF. Start with account, capacity pool, volume, and snapshot, then expand.
- **Learning goes with each feature.** Each feature should help the author understand and explain the matching ANF/ONTAP concept, not only reproduce its behavior.
- **The control plane is asynchronous.** It follows the ARM long-running-operation style: return a `provisioningState` right away and let the client poll for completion.
- **Azure-side concepts are secondary.** Add subscriptions, resource groups, VNet, delegated subnets, and RBAC only when a feature needs them.
- **The end goal is a dashboard that mirrors the ANF portal's features.** It does not have to match 100%. Leave out Microsoft logos and assets.
- **Claude writes the implementation code.** The user must still explain that code in interviews, so every feature gets a concept doc. It walks through the code and the reasons behind each design choice. The body is in Korean and the interview Q&A is in English.

## Not decided yet

Ask the user before assuming any of these:

- Tech stack. Python for the backend and React + TypeScript for the frontend were proposed but not confirmed. The author knows Python well, C/C++/React/TypeScript at a basic level, and almost no Go or C#. The TDD hook (2026-11-07) assumes Python + pytest; change it if the backend language changes.
- Storage backend: Linux primitives (btrfs, knfsd, cgroups) or the NetApp ONTAP Simulator.
- Protocols, where clients mount from, authentication, and timeline.

## Environment

- **Host**: Windows 11 Home. Windows has no built-in NFS server, so data-plane work runs in **WSL2 Ubuntu 24.04** (kernel 6.18). The distro is `Ubuntu` (the default), but `kali-linux` and `docker-desktop` also exist, so name it: `wsl -d Ubuntu -- <cmd>`.
- **Kernel modules**: the WSL kernel ships `nfsd` (with NFSv4), `btrfs`, `dm-thin`, and blk-cgroup I/O throttling as modules. Nobody has checked yet that they load.
- **WSL limits**: about 7 GB RAM.
- **Docker Desktop**: installed, but it is not always running. Start it before using `docker`.
- **Repository**: private GitHub repo `goldenbit1999/anf-clone` (default branch `main`).

## Commands and architecture

There is no application code yet. Add build commands and an architecture overview here once the stack is chosen.

- **Tests**: `python -m pytest` (Windows Python, pytest 9.2). If a project `.venv` exists, the hook uses its Python. Single test: `python -m pytest path/to/test_x.py::test_name`.

### TDD hook

`.claude/hooks/tdd_guard.py`, registered in `.claude/settings.json`, makes Python work test-first:

- **PreToolUse (Write|Edit)**: blocks writing or editing `foo.py` unless `test_foo.py` or `foo_test.py` exists somewhere in the repo. The hook skips non-`.py` files, `__init__.py`, `conftest.py`, files under `tests/` or `test/`, dot-folders, `_workspace/`, `docs/`, `venv/`, `node_modules/`, and `__pycache__/`.
- Pairing is by file name, not path: any `test_models.py` unlocks every `models.py`, and editing one `models.py` runs every `test_models.py`.
- **PostToolUse (Write|Edit)**: runs the matching test file and sends RED or GREEN back to Claude.
- **Stop**: if code changed this turn and the full suite fails, blocks the stop once.
- The hook only sees the Write and Edit tools. It does not check files written through Bash, so write code with Write or Edit.

## 하네스: ANF 기능 구현

**목표:** ANF 기능을 하나씩 조사 → 설계 → 구현 → 실환경 검증 → 개념 문서 순서로 완성한다.

**호출 조건:** ANF 기능을 구현·추가·확장하거나, 기능을 재검증하거나, 기능의 개념 문서를 다시 쓰는 요청이면 `anf-feature-cycle` 스킬을 사용한다. 단순 질문에는 직접 답해도 된다.

**변경 이력:**
| 날짜 | 변경 내용 | 대상 | 사유 |
| --- | --- | --- | --- |
| 2026-11-07 | Harness v2로 처음 구성 | 전체 | - |
| 2026-11-07 | 원문 내려받기 절차, `[녹화]` 근거, 컨트롤 플레인 전용 기능의 검증 기준, 정해야 할 선택지 반환 추가. anf-researcher의 `tools`에 Bash·ToolSearch 추가는 사용자 승인 대기 중 | anf-researcher, anf-research, real-env-verify, anf-feature-cycle | 첫 조사 시험에서 비용 과다(토큰 25만), 녹화 근거 표시 공백, 계정처럼 데이터 효과가 없는 기능의 기준 부재 발견 |
| 2026-11-07 | TDD 훅 추가(테스트 없는 구현 파일 차단, 수정마다 관련 테스트 실행, 실패 중 종료 1회 차단). 3단계를 테스트 우선 순서로 변경 | `.claude/hooks/tdd_guard.py`, `.claude/settings.json`, anf-feature-cycle | 사용자 요청: TDD 강제 |
| 2026-11-07 | anf-researcher의 `tools`에 Bash·ToolSearch 추가(두 번째 줄의 승인 대기 항목) | anf-researcher | 본문이 `curl` 내려받기와 ToolSearch를 지시하는데 도구 목록에 없어 실행할 수 없었음. 사용자 승인 |
