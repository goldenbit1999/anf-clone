"""storage agent의 명령 실행기: 셸 없이 인자 목록으로 실행한다 (ADR R-07, 볼륨 설계 §6.2)."""

import subprocess
import sys

import pytest

from storage_agent.runner import CommandError, Runner


def test_runs_argument_list_and_captures_output():
    result = Runner().run([sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr)"])
    assert result.returncode == 0
    assert result.stdout == "out\n"
    assert result.stderr == "err\n"


def test_failure_raises_command_error_with_stderr():
    with pytest.raises(CommandError) as e:
        Runner().run([sys.executable, "-c", "import sys; print('boom', file=sys.stderr); sys.exit(3)"])
    assert e.value.result.returncode == 3
    assert "boom" in str(e.value)


def test_check_false_returns_failed_result():
    result = Runner().run([sys.executable, "-c", "import sys; sys.exit(5)"], check=False)
    assert result.returncode == 5


def test_passes_input_to_stdin():
    result = Runner().run([sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"], input="abc")
    assert result.stdout == "ABC\n"


def test_refuses_shell_string():
    # 문자열 하나는 셸 명령으로 오해될 수 있으므로 받지 않는다
    with pytest.raises(TypeError):
        Runner().run("echo hi")


def test_missing_program_is_command_error():
    with pytest.raises(CommandError) as e:
        Runner().run(["anf-clone-no-such-program-xyz"])
    assert e.value.result.returncode == 127


def test_child_never_waits_on_agent_stdin(monkeypatch):
    # LVM 확인 질문 같은 프롬프트가 데몬의 표준 입력을 기다리며 멈추지 않게, 입력이 없으면 빈 입력(EOF)을 준다
    seen = {}

    def fake_run(argv, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    Runner().run(["lvremove", "anf/x"])
    assert seen["stdin"] is subprocess.DEVNULL


def test_suppresses_lvm_fd_warnings():
    # LVM은 상속된 파일 기술자마다 경고를 낸다 (S1 추가 관찰)
    result = Runner().run([sys.executable, "-c", "import os; print(os.environ['LVM_SUPPRESS_FD_WARNINGS'])"])
    assert result.stdout == "1\n"
