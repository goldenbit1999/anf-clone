"""TDD 가드 훅. Claude Code의 훅 이벤트 세 곳에서 호출된다.

  pre  (PreToolUse, Write|Edit)  : 짝이 되는 테스트가 없는 구현 파일의 작성·수정을 막는다.
  post (PostToolUse, Write|Edit) : 고친 파일과 관련된 테스트를 돌려 결과를 Claude에게 돌려준다.
  stop (Stop)                    : 이번 턴에 코드를 바꿨는데 전체 테스트가 실패 중이면 종료를 한 번 막는다.

구현 파일 foo.py의 짝은 프로젝트 안 어디에 있든 test_foo.py 또는 foo_test.py다.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SKIP_DIRS = {"venv", "node_modules", "__pycache__", "_workspace", "docs"}  # '.'으로 시작하는 폴더도 건너뛴다
TEST_DIRS = {"tests", "test"}
EXEMPT_NAMES = {"__init__.py", "conftest.py"}
POST_TIMEOUT = 90
STOP_TIMEOUT = 240
MAX_OUTPUT = 3000


def skipped_dir(name):
    return name.startswith(".") or name in SKIP_DIRS


def rel_path(file_path, root):
    """file_path가 root 안에 있으면 root 기준 상대 경로를, 아니면 None을 돌려준다. 대소문자 차이는 무시한다."""
    p = Path(os.path.abspath(file_path)).parts
    r = Path(os.path.abspath(root)).parts
    if len(p) <= len(r) or [os.path.normcase(x) for x in p[: len(r)]] != [os.path.normcase(x) for x in r]:
        return None
    return Path(*p[len(r):])


def classify(rel):
    """'test'(테스트 모듈), 'exempt'(conftest·__init__·tests 폴더의 보조 파일), 'impl'(구현), None(대상 아님)."""
    if rel.suffix != ".py" or any(skipped_dir(d) for d in rel.parts[:-1]):
        return None
    name = rel.name
    if name.startswith("test_") or name.endswith("_test.py"):
        return "test"
    if name in EXEMPT_NAMES or any(d in TEST_DIRS for d in rel.parts[:-1]):
        return "exempt"
    return "impl"


def find_tests(root, stem):
    wanted = {f"test_{stem}.py", f"{stem}_test.py"}
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not skipped_dir(d)]
        found += [Path(dirpath, f) for f in filenames if f in wanted]
    return sorted(found)


def python_exe(root):
    for candidate in (root / ".venv" / "Scripts" / "python.exe", root / ".venv" / "bin" / "python"):
        if candidate.exists():
            return str(candidate)
    return sys.executable


def run_pytest(root, targets, timeout):
    """('green'|'red'|'no-tests'|'no-pytest'|'timeout', 출력 끝부분)을 돌려준다."""
    cmd = [python_exe(root), "-m", "pytest", "-q", "--no-header", "-rfE", *map(str, targets)]
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    try:
        r = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return "timeout", f"pytest가 {timeout}초 안에 끝나지 않았습니다."
    out = (r.stdout + r.stderr).strip()[-MAX_OUTPUT:]
    if "No module named pytest" in out:
        return "no-pytest", "pytest가 설치되어 있지 않습니다. `python -m pip install pytest`로 설치하세요."
    return {0: "green", 5: "no-tests"}.get(r.returncode, "red"), out


def marker(data):
    """이번 턴에 코드가 바뀌었음을 Stop 훅에 알리는 세션별 표시 파일."""
    session = re.sub(r"[^A-Za-z0-9_-]", "_", str(data.get("session_id") or "unknown"))
    folder = Path(tempfile.gettempdir()) / "claude-tdd-guard"
    folder.mkdir(exist_ok=True)
    return folder / f"{session}.dirty"


def emit(obj):
    sys.stdout.write(json.dumps(obj))


def edited_file(data, root):
    file_path = (data.get("tool_input") or {}).get("file_path")
    rel = rel_path(file_path, root) if file_path else None
    return rel, classify(rel) if rel else None


def pre(data, root):
    rel, kind = edited_file(data, root)
    if kind != "impl" or find_tests(root, rel.stem):
        return
    emit({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": (
            f"TDD 가드: {rel.as_posix()}의 테스트가 없습니다. "
            f"먼저 test_{rel.stem}.py(또는 {rel.stem}_test.py)에 실패하는 테스트를 쓰고 "
            "RED를 확인한 다음 구현하세요."
        ),
    }})


def post(data, root):
    rel, kind = edited_file(data, root)
    if kind is None:
        return
    marker(data).touch()
    if kind == "test":
        targets = [root / rel]
    elif kind == "impl":
        targets = find_tests(root, rel.stem)
    else:
        return  # conftest·__init__ 같은 파일은 Stop에서 전체 실행으로 확인한다
    if not targets:
        return
    status, out = run_pytest(root, targets, POST_TIMEOUT)
    names = ", ".join(Path(os.path.relpath(t, root)).as_posix() for t in targets)
    message = {
        "green": f"TDD 가드: {names} GREEN. 필요하면 리팩터링하고, 다음 동작은 실패하는 테스트부터 쓰세요.",
        "red": (f"TDD 가드: {names} RED.\n{out}\n"
                "방금 테스트를 썼다면 실패 이유가 '아직 구현되지 않음'인지 확인하세요. "
                "구현 중이라면 이 테스트를 통과시키는 최소한의 코드를 쓰세요."),
        "no-tests": f"TDD 가드: {names}에서 수집된 테스트가 없습니다.",
    }.get(status, f"TDD 가드: 테스트를 돌리지 못했습니다. {out}")
    emit({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": message}})


def stop(data, root):
    flag = marker(data)
    if not flag.exists():
        return
    flag.unlink()
    status, out = run_pytest(root, [], STOP_TIMEOUT)
    if status in ("green", "no-tests"):
        return
    if status != "red":
        emit({"systemMessage": f"TDD 가드: 전체 테스트를 확인하지 못했습니다. {out}"})
    elif data.get("stop_hook_active"):
        emit({"systemMessage": "TDD 가드: 테스트가 실패한 채로 턴이 끝났습니다. `python -m pytest`로 확인하세요."})
    else:
        emit({"decision": "block", "reason": (
            f"TDD 가드: 이번 턴에 코드를 바꿨는데 전체 테스트가 실패 중입니다.\n{out}\n"
            "테스트를 통과시키세요. 의도한 RED라면(예: 사용자 확인을 기다리는 중) 그 사실을 사용자에게 알리고 마치세요."
        )})


def main():
    data = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd())
    {"pre": pre, "post": post, "stop": stop}[sys.argv[1]](data, root)


if __name__ == "__main__":
    main()
