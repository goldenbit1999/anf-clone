"""TDD 가드 훅. Claude Code의 훅 이벤트 세 곳에서 호출된다. 메인 세션과 서브에이전트의 도구 호출에 모두 걸린다.

  pre  (PreToolUse, Write|Edit)  : 구현 파일을 고치기 전에, 짝 테스트가 지금 내용 그대로 수집·실행된 근거가 있는지 확인한다.
  post (PostToolUse, Write|Edit) : 고친 파일과 관련된 테스트를 돌려 GREEN·RED·SKIPPED·ERROR를 Claude에게 돌려주고 근거를 기록한다.
  stop (Stop)                    : 코드를 바꾼 뒤 전체 테스트가 GREEN으로 확인되기 전에는 종료를 한 번 막는다.

구현 파일 foo.py의 짝은 프로젝트 안 어디에 있든 test_foo.py 또는 foo_test.py다.

보장 범위: 짝 테스트가 있고, 수집되고, 실행됐다는 것까지다. 테스트가 올바른 동작을 검사하는지는 리뷰로 확인한다.
GREEN인 테스트로도 구현을 고칠 수 있다(리팩터링). 그래서 "새 동작은 RED부터"는 절차로 지킨다.
Write·Edit 도구만 보며, Bash로 쓴 파일과 .py가 아닌 파일은 대상이 아니다.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

SKIP_DIRS = {"venv", "node_modules", "__pycache__", "_workspace", "docs"}  # '.'으로 시작하는 폴더도 건너뛴다
TEST_DIRS = {"tests", "test"}
EXEMPT_NAMES = {"__init__.py", "conftest.py"}
STATE_DIR = Path(".claude") / "tdd-guard-state"
PRE_TIMEOUT = 90
POST_TIMEOUT = 90
STOP_TIMEOUT = 240
MAX_OUTPUT = 3000

# 구현 파일을 고쳐도 되는 근거가 되는 결과. missing-impl은 구현할 모듈이나 이름이 아직 없어서 생긴 예상한 RED다.
READY = {"red", "missing-impl", "green"}
NO_MODULE = re.compile(r"No module named '([\w.]+)'")
CANNOT_IMPORT = re.compile(r"cannot import name '\w+' from '([\w.]+)'")
PY_FILE = re.compile(r"([\w.-]+)\.py\b")


@dataclass
class Run:
    status: str  # green | red | missing-impl | error | skipped | no-tests | no-pytest | timeout
    summary: str
    output: str = ""
    counts: dict = field(default_factory=dict)
    skips: list = field(default_factory=list)
    command: str = ""


def skipped_dir(name):
    return name.startswith(".") or name in SKIP_DIRS


def rel_path(file_path, root):
    """file_path가 root 안에 있으면 root 기준 상대 경로를, 아니면 None을 돌려준다. 대소문자 차이는 무시한다."""
    p = Path(os.path.abspath(file_path)).parts
    r = Path(os.path.abspath(root)).parts
    if len(p) <= len(r) or [os.path.normcase(x) for x in p[: len(r)]] != [os.path.normcase(x) for x in r]:
        return None
    return Path(*p[len(r):])


def is_test_name(name):
    return name.startswith("test_") or name.endswith("_test.py")


def classify(rel):
    """'test'(테스트 모듈), 'exempt'(conftest·__init__·tests 폴더의 보조 파일), 'impl'(구현), None(대상 아님)."""
    if rel.suffix != ".py" or any(skipped_dir(d) for d in rel.parts[:-1]):
        return None
    if is_test_name(rel.name):
        return "test"
    if rel.name in EXEMPT_NAMES or any(d in TEST_DIRS for d in rel.parts[:-1]):
        return "exempt"
    return "impl"


def impl_stem(test_name):
    return test_name[5:-3] if test_name.startswith("test_") else test_name[:-8]


def find_tests(root, stem):
    wanted = {f"test_{stem}.py", f"{stem}_test.py"}
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not skipped_dir(d)]
        found += [Path(dirpath, f) for f in filenames if f in wanted]
    return sorted(found)


def python_exe(root, windows=None, env=None):
    """(인터프리터 경로, 가상환경 여부). 현재 OS의 가상환경만 고른다 (ADR D-14)."""
    windows = os.name == "nt" if windows is None else windows
    env = os.environ if env is None else env
    if windows:
        candidate = Path(root) / ".venv-win" / "Scripts" / "python.exe"
    else:
        venv = env.get("ANF_CLONE_VENV") or os.path.expanduser("~/.venvs/anf-clone")
        candidate = Path(venv) / "bin" / "python"
    return (str(candidate), True) if candidate.exists() else (sys.executable, False)


def environment(root):
    py, in_venv = python_exe(root)
    config = "pyproject.toml" if (Path(root) / "pyproject.toml").exists() else "없음"
    return f"(python: {py}{'' if in_venv else ' — 가상환경 없음'}, cwd: {root}, 설정: {config})"


def parse_junit(path):
    counts = {"passed": 0, "failed": 0, "error": 0, "skipped": 0}
    problems, skips = [], []
    for case in ET.parse(path).getroot().iter("testcase"):
        found = {child.tag: child for child in case}
        name = "::".join(x for x in (case.get("classname"), case.get("name")) if x)
        if "error" in found or "failure" in found:
            kind = "error" if "error" in found else "failed"
            el = found["error" if kind == "error" else "failure"]
            counts[kind] += 1
            problems.append((kind, name, el.get("message") or "", el.text or ""))
        elif "skipped" in found:
            counts["skipped"] += 1
            skips.append(f"{name}: {found['skipped'].get('message') or ''}")
        else:
            counts["passed"] += 1
    return counts, problems, skips


def names_impl(module, stem, impl_parts):
    """없다고 나온 모듈이 지금 만들 구현(파일 이름 또는 경로)을 가리키는가."""
    comps = module.split(".")
    if stem and stem in comps:
        return True
    parts = list(impl_parts or ())
    return any(parts[i:i + len(comps)] == comps for i in range(len(parts) - len(comps) + 1))


def impl_explains(text, stem, impl_parts):
    """수집·설정 오류가 구현이 없거나 깨져서 생겼으면 True. 테스트 자체·의존성 문제면 False."""
    m = NO_MODULE.search(text)
    if m:
        return names_impl(m.group(1), stem, impl_parts)
    m = CANNOT_IMPORT.search(text)
    if m:
        return names_impl(m.group(1), stem, impl_parts)
    return bool(stem) and any(f == stem for f in PY_FILE.findall(text))


def reason_of(kind, message, text):
    lines = [line[1:].strip() for line in text.splitlines() if line.startswith("E ")]
    if kind == "failed" and message:
        return message.splitlines()[0]
    return lines[-1] if lines else (message.splitlines() or [""])[0]


def count_text(counts):
    return ", ".join(f"{n} {k}" for k, n in counts.items() if n) or "0 collected"


def run_pytest(root, targets, timeout, stem=None, impl_parts=None):
    py, _ = python_exe(root)
    fd, xml = tempfile.mkstemp(suffix=".xml", prefix="tdd-guard-")
    os.close(fd)
    cmd = [py, "-m", "pytest", "-q", "--no-header", "-rfEs", f"--junitxml={xml}", *map(str, targets)]
    shown = " ".join(["python -m pytest", *(Path(os.path.relpath(t, root)).as_posix() for t in targets)])
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    try:
        try:
            r = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired:
            return Run("timeout", f"pytest가 {timeout}초 안에 끝나지 않았습니다.", command=shown)
        out = (r.stdout + r.stderr).strip()[-MAX_OUTPUT:]
        if "No module named pytest" in out:
            return Run("no-pytest", f"{py}에 pytest가 없습니다. `{py} -m pip install -e \".[dev]\"`로 설치하세요.",
                       out, command=shown)
        try:
            counts, problems, skips = parse_junit(xml)
        except (OSError, ET.ParseError):
            counts = None
    finally:
        try:
            os.unlink(xml)
        except OSError:
            pass
    if r.returncode == 5:
        return Run("no-tests", "수집된 테스트가 없습니다.", out, command=shown)
    if counts is None or r.returncode not in (0, 1, 2):
        return Run("error", f"pytest 종료 코드 {r.returncode}", out, command=shown)
    errors = [p for p in problems if p[0] == "error"]
    if errors:
        status = "missing-impl" if all(impl_explains(p[3], stem, impl_parts) for p in errors) else "error"
    elif counts["failed"]:
        status = "red"
    elif counts["passed"]:
        status = "green"
    else:
        status = "skipped" if counts["skipped"] else "no-tests"
    summary = "; ".join(f"{name}: {reason_of(kind, msg, text)}" for kind, name, msg, text in problems[:3])
    return Run(status, summary or count_text(counts), out, counts, skips, shown)


# ---- 근거 기록 -------------------------------------------------------------

def state_file(root, name):
    folder = Path(root) / STATE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    return folder / name


def load_evidence(root):
    try:
        return json.loads((Path(root) / STATE_DIR / "evidence.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def evidence_key(root, test):
    return Path(os.path.relpath(test, root)).as_posix()


def is_ready(evidence, root, test):
    entry = evidence.get(evidence_key(root, test))
    return bool(entry and entry.get("ready") and entry.get("sha256") == digest(test))


def record(root, test, run):
    """테스트 내용 해시별로 실행 근거를 남긴다. 테스트가 바뀌면 이전 근거는 무효가 된다."""
    evidence = load_evidence(root)
    key, sha = evidence_key(root, test), digest(test)
    old = evidence.get(key) if evidence.get(key, {}).get("sha256") == sha else {}
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    red = old.get("red")
    if not red and run.status in ("red", "missing-impl"):
        red = {"status": run.status, "summary": run.summary, "command": run.command, "at": now}
    entry = {"sha256": sha, "ready": bool(old.get("ready")) or run.status in READY,
             "status": run.status, "summary": run.summary, "command": run.command, "at": now, "red": red}
    evidence[key] = entry
    target = state_file(root, "evidence.json")
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(evidence, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, target)
    return entry


def marker(data, root):
    """코드가 바뀌었고 아직 GREEN으로 확인되지 않았음을 Stop 훅에 알리는 세션별 표시 파일."""
    session = re.sub(r"[^A-Za-z0-9_-]", "_", str(data.get("session_id") or "unknown"))
    return state_file(root, f"dirty-{session}.json")


# ---- 훅 이벤트 -------------------------------------------------------------

def emit(obj):
    sys.stdout.write(json.dumps(obj))  # ASCII 이스케이프: Windows 콘솔 인코딩과 무관하게 안전하다


def edited_file(data, root):
    file_path = (data.get("tool_input") or {}).get("file_path")
    rel = rel_path(file_path, root) if file_path else None
    return rel, classify(rel) if rel else None


def deny(reason):
    emit({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                 "permissionDecisionReason": f"TDD 가드: {reason}"}})


def why_not_ready(name, run):
    return {
        "no-tests": f"{name}에서 수집된 테스트가 없습니다. 빈 파일이거나 test_ 함수가 없습니다. 실패하는 테스트를 먼저 쓰세요.",
        "skipped": (f"{name}의 테스트가 이 OS에서 모두 skip돼 RED를 볼 수 없습니다 ({'; '.join(run.skips[:3])}). "
                    "여기서 도는 단위 테스트를 쓰세요. 커널 명령은 주입한 실행기로 바꿉니다 (ADR §9.2)."),
        "error": (f"{name}를 실행하지 못했습니다: {run.summary}. 테스트 문법·fixture·의존성 오류는 동작 검증 RED가 아닙니다. "
                  "구현할 모듈이 없어 생긴 import 오류라면 모듈 경로가 고치려는 파일과 맞는지 확인하세요."),
        "no-pytest": run.summary,
        "timeout": f"{name}: {run.summary}",
    }.get(run.status, f"{name}: {run.status}")


def pre(data, root):
    rel, kind = edited_file(data, root)
    if kind != "impl":
        return
    tests = find_tests(root, rel.stem)
    if not tests:
        return deny(f"{rel.as_posix()}의 테스트가 없습니다. 먼저 test_{rel.stem}.py(또는 {rel.stem}_test.py)에 "
                    "실패하는 테스트를 쓰고 RED를 확인한 다음 구현하세요.")
    evidence = load_evidence(root)
    if any(is_ready(evidence, root, t) for t in tests):
        return
    reasons = []
    for t in tests:  # 지금 내용의 테스트를 실행한 근거가 없으면 직접 실행해 근거를 만든다
        run = run_pytest(root, [t], max(10, PRE_TIMEOUT // len(tests)), rel.stem, rel.with_suffix("").parts)
        if record(root, t, run)["ready"]:
            return
        reasons.append(why_not_ready(evidence_key(root, t), run))
    deny(f"{rel.as_posix()}를 고칠 근거가 없습니다.\n" + "\n".join(reasons) + f"\n{environment(root)}")


def describe(name, run):
    skipped = run.counts.get("skipped", 0)
    skip_note = f"\nskip {skipped}개는 검증되지 않았습니다: {'; '.join(run.skips[:3])}" if skipped else ""
    return {
        "green": f"TDD 가드: {name} GREEN ({count_text(run.counts)}). 필요하면 리팩터링하고, "
                 f"다음 동작은 실패하는 테스트부터 쓰세요.{skip_note}",
        "red": (f"TDD 가드: {name} RED ({count_text(run.counts)}).\n{run.output}\n"
                "실패 이유가 '아직 구현되지 않음'인지 확인하세요(예상한 RED). "
                f"구현 중이라면 이 테스트를 통과시키는 최소한의 코드를 쓰세요.{skip_note}"),
        "missing-impl": (f"TDD 가드: {name} RED — 구현 없음 ({run.summary}). "
                         "구현할 모듈이나 이름이 아직 없어서 생긴 예상한 RED인지 확인하세요."),
        "skipped": (f"TDD 가드: {name} SKIPPED. 수집된 테스트 {skipped}개가 모두 skip됐습니다. "
                    f"GREEN이 아니며 검증되지 않았습니다.\n이유: {'; '.join(run.skips[:3])}"),
        "no-tests": f"TDD 가드: {name}에서 수집된 테스트가 없습니다. 검증되지 않았습니다.",
        "error": (f"TDD 가드: {name} ERROR — 동작 검증 RED가 아닙니다 ({run.summary}).\n{run.output}\n"
                  "테스트 문법, fixture, 의존성을 고치세요."),
    }.get(run.status, f"TDD 가드: {name} 테스트를 돌리지 못했습니다 ({run.status}). {run.summary}")


def post(data, root):
    rel, kind = edited_file(data, root)
    if kind is None:
        return
    marker(data, root).touch()
    if kind == "test":
        targets, stem, parts = [Path(root) / rel], impl_stem(rel.name), None
    elif kind == "impl":
        targets, stem, parts = find_tests(root, rel.stem), rel.stem, rel.with_suffix("").parts
    else:
        return  # conftest·__init__ 같은 파일은 Stop에서 전체 실행으로 확인한다
    if not targets:
        return
    messages = []
    for t in targets:
        run = run_pytest(root, [t], max(10, POST_TIMEOUT // len(targets)), stem, parts)
        record(root, t, run)
        messages.append(describe(evidence_key(root, t), run))
    emit({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                 "additionalContext": "\n\n".join(messages) + f"\n{environment(root)}"}})


STOP_LABELS = {"red": "실패", "missing-impl": "실패", "error": "수집·실행 오류", "skipped": "모두 skip",
               "no-tests": "수집된 테스트 없음", "no-pytest": "pytest 없음", "timeout": "시간 초과"}


def stop(data, root):
    flag = marker(data, root)
    if not flag.exists():
        return
    run = run_pytest(root, [], STOP_TIMEOUT)
    if run.status == "green":
        flag.unlink(missing_ok=True)
        return
    # 확인하지 못한 결과는 지우지 않는다. 다음 종료 때 다시 확인한다.
    flag.write_text(json.dumps({"status": run.status, "summary": run.summary,
                                "at": time.strftime("%Y-%m-%dT%H:%M:%S")}, ensure_ascii=False), encoding="utf-8")
    label = STOP_LABELS.get(run.status, run.status)
    if data.get("stop_hook_active"):
        return emit({"systemMessage": f"TDD 가드: 전체 테스트가 '{label}' 상태로 턴이 끝났습니다. "
                                      f"다음 종료 때 다시 확인합니다. 직접 확인: `python -m pytest` {environment(root)}"})
    if run.status in ("red", "missing-impl", "error"):
        reason = (f"TDD 가드: 코드를 바꾼 뒤 전체 테스트가 '{label}' 상태입니다.\n{run.output}\n"
                  "테스트를 통과시키세요. 의도한 RED라면(예: 사용자 확인을 기다리는 중) 그 사실을 사용자에게 알리고 마치세요.")
    else:
        reason = (f"TDD 가드: 코드를 바꿨지만 전체 테스트로 검증하지 못했습니다 ('{label}': {run.summary}).\n"
                  "해결하거나, 이번 변경이 검증되지 않았다고 사용자에게 보고하고 마치세요. "
                  "검증되지 않은 변경으로 기능을 done 처리하지 않습니다.")
    emit({"decision": "block", "reason": f"{reason}\n{environment(root)}"})


def main():
    data = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd())
    {"pre": pre, "post": post, "stop": stop}[sys.argv[1]](data, root)


if __name__ == "__main__":
    main()
