"""scripts/demo.py의 순수 부분과 종료 코드 (FR-13, 설계 _workspace/containers/02_main_design.md §2, AC-04).

데모 대본 전체(1~7단계)가 실제 스택에서 도는지는 실환경 e2e(test_compose_stack_live.py)가 본다.
여기서는 HTTP와 docker를 가짜로 바꿔 판정, 출력, 종료 코드만 본다.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import demo  # noqa: E402


# --- 순수 부분 ---


def test_fio_mibps_reads_errors_and_write_rate_after_leading_noise():
    job = {"error": 0, "write": {"io_bytes": 320 * 1048576, "runtime": 10000}}
    stdout = "fio: note: something\n" + json.dumps({"jobs": [job]})
    assert demo.fio_mibps(stdout) == (0, 32.0)


@pytest.mark.parametrize("measured, ok", [(28.79, False), (28.8, True), (31.1, True), (32.32, True), (32.33, False)])
def test_within_accepts_90_to_101_percent_of_the_limit(measured, ok):
    assert demo.within(measured, 32.0) is ok


def test_prom_value_reads_one_sample_or_none():
    assert demo.prom_value({"status": "success", "data": {"result": []}}) is None
    body = {"status": "success", "data": {"result": [{"metric": {}, "value": [1700000000.0, "16777216"]}]}}
    assert demo.prom_value(body) == 16777216.0


def test_operation_error_names_the_code_and_message():
    assert demo.operation_error({"status": "Succeeded"}) is None
    failed = {"status": "Failed", "error": {"code": "InternalServerError", "message": "lvcreate failed"}}
    assert demo.operation_error(failed) == "Failed: InternalServerError: lvcreate failed"


# --- 종료 코드 (가짜 API·docker) ---


class FakeApi:
    """1단계까지만 흉내 낸다. 모든 비동기 작업은 바로 끝나고, volume_outcome이 볼륨 생성 작업의 종결 본문이다.
    리소스는 하나도 없어서 DELETE는 204다."""

    def __init__(self, volume_outcome=None, down=False):
        self.volume_outcome = volume_outcome or {"status": "Succeeded"}
        self.down = down
        self.calls = []

    def __call__(self, method, url, body=None):
        self.calls.append((method, url))
        if self.down:
            raise ConnectionRefusedError(111, "Connection refused")
        if method == "DELETE":
            return demo.Reply(204, {}, b"")
        if method == "PUT":
            n = len(self.calls)
            return demo.Reply(201, {"azure-asyncoperation": f"http://op/{n}?volume={'/volumes/' in url}"}, b"{}")
        if url.startswith("http://op/"):
            final = self.volume_outcome if url.endswith("volume=True") else {"status": "Succeeded"}
            return demo.Reply(200, {}, json.dumps(final).encode())
        return demo.Reply(200, {}, b'{"properties": {"provisioningState": "Succeeded"}, "value": []}')


class FakeDocker:
    def __init__(self, missing_image=False):
        self.missing_image = missing_image
        self.calls = []

    def __call__(self, argv, timeout=None):
        self.calls.append(argv)
        rc = 1 if self.missing_image and argv[:3] == ["docker", "image", "inspect"] else 0
        return subprocess.CompletedProcess(argv, rc, "", "")


def test_stack_down_exits_2_with_the_start_command_and_sends_nothing_else(capsys):
    api, docker = FakeApi(down=True), FakeDocker()
    assert demo.main([], http=api, run=docker) == 2
    err = capsys.readouterr().err
    assert "docker compose -f deploy/compose.yaml up -d --build --wait" in err
    assert [m for m, _ in api.calls if m != "GET"] == []
    assert docker.calls == []


def test_missing_client_image_exits_2(capsys):
    assert demo.main([], http=FakeApi(), run=FakeDocker(missing_image=True)) == 2
    assert "anf-nfs-client" in capsys.readouterr().err


def test_failed_volume_stops_at_step_1_shows_the_error_and_cleans_up(capsys):
    failed = {"status": "Failed", "error": {"code": "InternalServerError", "message": "lvcreate failed"}}
    api, docker = FakeApi(volume_outcome=failed), FakeDocker()
    assert demo.main([], http=api, run=docker) == 1
    err = capsys.readouterr().err
    assert "[1]" in err and "lvcreate failed" in err
    # 2단계(클라이언트)로 가지 않는다
    assert not [a for a in docker.calls if a[:2] == ["docker", "run"]]
    # 실패한 뒤에도 치운다: 마지막 PUT 뒤에 DELETE가 있다
    last_put = max(i for i, (m, _) in enumerate(api.calls) if m == "PUT")
    assert [m for m, _ in api.calls[last_put:]].count("DELETE") >= 3


def test_keep_leaves_resources_after_a_failure(capsys):
    failed = {"status": "Failed", "error": {"code": "InternalServerError", "message": "lvcreate failed"}}
    api = FakeApi(volume_outcome=failed)
    assert demo.main(["--keep"], http=api, run=FakeDocker()) == 1
    last_put = max(i for i, (m, _) in enumerate(api.calls) if m == "PUT")
    assert [m for m, _ in api.calls[last_put:]].count("DELETE") == 0
