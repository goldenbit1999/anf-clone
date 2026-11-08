"""tdd_guard.py 훅의 검증 사례. 각 테스트는 임시 프로젝트를 만들고 그 안에서 실제 pytest를 돌린다."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tdd_guard as tg  # noqa: E402

FAILING_TEST = "from pkg.calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n"
IMPL_OK = "def add(a, b):\n    return a + b\n"
IMPL_WRONG = "def add(a, b):\n    return 0\n"
ALL_SKIPPED = "import pytest\n\n@pytest.mark.skip(reason='linux only')\ndef test_add():\n    pass\n"


def write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def call(fn, root, capsys, **data):
    fn({"session_id": "s1", **data}, root)
    out = capsys.readouterr().out
    return json.loads(out) if out else None


def edit(path):
    return {"tool_input": {"file_path": str(path)}}


def deny_reason(resp):
    assert resp is not None, "거절을 기대했는데 허용됐다"
    out = resp["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"
    return out["permissionDecisionReason"]


def context(resp):
    return resp["hookSpecificOutput"]["additionalContext"]


@pytest.fixture
def root(tmp_path):
    write(tmp_path, "pkg/__init__.py", "")
    return tmp_path


# ---- pre: 구현 파일 수정 허용 조건 ---------------------------------------------

def test_pre_denies_without_test_file(root, capsys):
    assert "test_calc.py" in deny_reason(call(tg.pre, root, capsys, **edit(root / "pkg/calc.py")))


def test_pre_denies_empty_test_file(root, capsys):
    write(root, "test_calc.py", "")
    assert "수집된 테스트가 없습니다" in deny_reason(call(tg.pre, root, capsys, **edit(root / "pkg/calc.py")))


def test_pre_denies_test_with_syntax_error(root, capsys):
    write(root, "test_calc.py", "def test_add(:\n    pass\n")
    assert "SyntaxError" in deny_reason(call(tg.pre, root, capsys, **edit(root / "pkg/calc.py")))


def test_pre_denies_missing_dependency(root, capsys):
    write(root, "test_calc.py", "import not_installed_dep_xyz\n\ndef test_add():\n    pass\n")
    assert "not_installed_dep_xyz" in deny_reason(call(tg.pre, root, capsys, **edit(root / "pkg/calc.py")))


def test_pre_denies_when_all_tests_skipped(root, capsys):
    write(root, "test_calc.py", ALL_SKIPPED)
    assert "linux only" in deny_reason(call(tg.pre, root, capsys, **edit(root / "pkg/calc.py")))


def test_pre_allows_expected_red_for_missing_module(root, capsys):
    write(root, "test_calc.py", FAILING_TEST)
    assert call(tg.pre, root, capsys, **edit(root / "pkg/calc.py")) is None
    entry = tg.load_evidence(root)["test_calc.py"]
    assert entry["red"]["status"] == "missing-impl"
    assert entry["red"]["command"] == "python -m pytest test_calc.py"


def test_pre_allows_missing_package_that_matches_impl_path(tmp_path, capsys):
    write(tmp_path, "test_calc.py", "from newpkg.calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n")
    assert call(tg.pre, tmp_path, capsys, **edit(tmp_path / "newpkg/calc.py")) is None


def test_pre_allows_after_assertion_red(root, capsys):
    write(root, "pkg/calc.py", IMPL_WRONG)
    write(root, "test_calc.py", FAILING_TEST)
    assert call(tg.pre, root, capsys, **edit(root / "pkg/calc.py")) is None
    assert tg.load_evidence(root)["test_calc.py"]["red"]["status"] == "red"


def test_pre_allows_refactoring_on_green(root, capsys):
    write(root, "pkg/calc.py", IMPL_OK)
    write(root, "test_calc.py", FAILING_TEST)
    assert call(tg.pre, root, capsys, **edit(root / "pkg/calc.py")) is None
    assert tg.load_evidence(root)["test_calc.py"]["status"] == "green"


def test_pre_allows_fixing_broken_impl(root, capsys):
    write(root, "pkg/calc.py", "def add(a, b:\n")
    write(root, "test_calc.py", FAILING_TEST)
    assert call(tg.pre, root, capsys, **edit(root / "pkg/calc.py")) is None


def test_evidence_is_invalidated_when_test_changes(root, capsys):
    test = write(root, "test_calc.py", FAILING_TEST)
    assert call(tg.pre, root, capsys, **edit(root / "pkg/calc.py")) is None
    test.write_text("", encoding="utf-8")
    deny_reason(call(tg.pre, root, capsys, **edit(root / "pkg/calc.py")))


def test_ready_evidence_survives_a_later_broken_run(root, capsys):
    write(root, "test_calc.py", FAILING_TEST)
    call(tg.post, root, capsys, **edit(root / "test_calc.py"))
    impl = write(root, "pkg/calc.py", "def add(a, b:\n")  # 구현을 고치다 문법 오류를 냈다
    call(tg.post, root, capsys, **edit(impl))
    assert call(tg.pre, root, capsys, **edit(impl)) is None  # 고칠 수 있어야 한다


def test_verifier_helper_under_tests_dir_is_not_blocked(root, capsys):
    assert call(tg.pre, root, capsys, **edit(root / "backend/tests/e2e/mount_helpers.py")) is None


# ---- post: 결과 보고 -----------------------------------------------------------

def test_red_to_green_cycle(root, capsys):
    test = write(root, "test_calc.py", FAILING_TEST)
    assert "RED" in context(call(tg.post, root, capsys, **edit(test)))
    impl = root / "pkg/calc.py"
    assert call(tg.pre, root, capsys, **edit(impl)) is None
    impl.write_text(IMPL_OK, encoding="utf-8")
    assert "GREEN" in context(call(tg.post, root, capsys, **edit(impl)))


def test_post_reports_skipped_not_green(root, capsys):
    test = write(root, "test_calc.py", ALL_SKIPPED)
    ctx = context(call(tg.post, root, capsys, **edit(test)))
    assert ctx.startswith("TDD 가드: test_calc.py SKIPPED") and "linux only" in ctx


def test_post_reports_error_not_red(root, capsys):
    test = write(root, "test_calc.py", "def test_add(:\n    pass\n")
    ctx = context(call(tg.post, root, capsys, **edit(test)))
    assert ctx.startswith("TDD 가드: test_calc.py ERROR")


def test_post_shows_interpreter_cwd_and_config(root, capsys):
    test = write(root, "test_calc.py", FAILING_TEST)
    ctx = context(call(tg.post, root, capsys, **edit(test)))
    assert "python:" in ctx and f"cwd: {root}" in ctx and "설정: 없음" in ctx


# ---- stop: 종료 확인 -----------------------------------------------------------

def dirty(root):
    tg.marker({"session_id": "s1"}, root).touch()
    return tg.marker({"session_id": "s1"}, root)


def test_stop_does_nothing_without_code_change(root, capsys):
    assert call(tg.stop, root, capsys) is None


def test_stop_blocks_once_on_no_tests_and_keeps_marker(root, capsys):
    flag = dirty(root)
    assert call(tg.stop, root, capsys)["decision"] == "block"
    again = call(tg.stop, root, capsys, stop_hook_active=True)
    assert "decision" not in again and "수집된 테스트 없음" in again["systemMessage"]
    assert json.loads(flag.read_text(encoding="utf-8"))["status"] == "no-tests"


def test_stop_keeps_failure_until_green(root, capsys):
    write(root, "test_calc.py", FAILING_TEST)
    impl = write(root, "pkg/calc.py", IMPL_WRONG)
    flag = dirty(root)
    assert call(tg.stop, root, capsys)["decision"] == "block"
    assert "decision" not in call(tg.stop, root, capsys, stop_hook_active=True)
    assert flag.exists()
    impl.write_text(IMPL_OK, encoding="utf-8")
    assert call(tg.stop, root, capsys) is None
    assert not flag.exists()


def test_stop_treats_all_skipped_as_unverified(root, capsys):
    write(root, "test_calc.py", ALL_SKIPPED)
    dirty(root)
    assert "모두 skip" in call(tg.stop, root, capsys)["reason"]


def test_stop_blocks_when_pytest_missing(root, capsys, monkeypatch):
    monkeypatch.setattr(tg.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "python: No module named pytest"))
    dirty(root)
    assert "pytest 없음" in call(tg.stop, root, capsys)["reason"]


def test_stop_blocks_on_timeout(root, capsys, monkeypatch):
    def too_slow(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])
    monkeypatch.setattr(tg.subprocess, "run", too_slow)
    flag = dirty(root)
    assert "시간 초과" in call(tg.stop, root, capsys)["reason"]
    assert flag.exists()


# ---- 인터프리터 선택 (ADR D-14) -------------------------------------------------

def test_python_exe_picks_the_venv_for_this_os(tmp_path):
    win = write(tmp_path, ".venv-win/Scripts/python.exe", "")
    lin = write(tmp_path, "wsl-venv/bin/python", "")
    assert tg.python_exe(tmp_path, windows=True, env={}) == (str(win), True)
    assert tg.python_exe(tmp_path, windows=False, env={"ANF_CLONE_VENV": str(tmp_path / "wsl-venv")}) == (str(lin), True)


def test_python_exe_never_crosses_os(tmp_path):
    write(tmp_path, "wsl-venv/bin/python", "")
    assert tg.python_exe(tmp_path, windows=True, env={"ANF_CLONE_VENV": str(tmp_path / "wsl-venv")}) == (sys.executable, False)
    write(tmp_path, ".venv-win/Scripts/python.exe", "")
    assert tg.python_exe(tmp_path, windows=False, env={"ANF_CLONE_VENV": str(tmp_path / "none")}) == (sys.executable, False)
