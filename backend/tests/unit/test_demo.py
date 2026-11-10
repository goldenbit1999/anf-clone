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


@pytest.mark.parametrize("runs, limit, ok", [
    ([19.7, 19.8, 19.8], 20.0, True),
    ([14.3, 12.48, 19.9], 20.0, True),   # 스토리지가 한도보다 느린 회(검증 1회차의 72%)는 실패가 아니다
    ([19.7, 20.36, 19.8], 20.0, True),   # 천장 = 101%(20.2) + 6 s 창의 1 MiB I/O 하나(0.167) = 20.367
    ([19.7, 20.37, 19.8], 20.0, False),
    ([4.96, 4.76, 5.12], 5.0, True),     # 수정 확인 07회: 앞 회로 밀린 I/O 하나만큼 높게 셌다
    ([4.96, 5.21, 4.96], 5.0, True),     # 천장 = 5.05 + 0.167 = 5.217
    ([4.96, 5.22, 4.96], 5.0, False),
    ([4.96, 5.3, 4.96], 5.0, False),     # I/O 하나로 설명되지 않는 진짜 초과
])
def test_under_ceiling_allows_101_percent_plus_one_io_per_run(runs, limit, ok):
    assert demo.under_ceiling(runs, limit) is ok


def test_the_ceiling_uses_the_io_size_and_window_of_the_fio_command():
    # fio는 끝난 I/O만 세므로, 회마다 창 경계에서 I/O 하나(bs ÷ 측정 시간)만큼 많거나 적게 셀 수 있다
    assert f" --bs={demo.FIO_BS_MIB}M " in demo.FIO and f" --runtime={demo.FIO_RUNTIME_S} " in demo.FIO
    assert demo.ceiling(5.0) == pytest.approx(5.0 * 1.01 + demo.FIO_BS_MIB / demo.FIO_RUNTIME_S)


@pytest.mark.parametrize("before, after, ok", [
    ([19.7, 19.8, 19.8], [4.97, 4.96, 4.97], True),
    ([14.3, 12.48, 19.9], [4.97, 4.96, 4.97], True),   # 내리기 전이 느렸어도 새 한도보다는 빨랐다
    ([5.0, 5.05, 19.8], [4.97, 4.96, 4.97], False),    # 내리기 전 중앙값이 새 한도의 101%(5.05)를 넘지 않는다
    ([19.7, 19.8, 19.8], [4.97, 5.1, 5.1], False),     # 내린 뒤 중앙값이 새 한도의 101%를 넘는다
])
def test_follows_limit_needs_the_median_above_the_new_limit_before_and_within_it_after(before, after, ok):
    assert demo.follows_limit(before, after, 5.0) is ok


def test_the_limit_pair_leaves_room_for_the_slowest_write_seen():
    # 이 환경에서 잰 쓰기 한 회의 가장 낮은 비율은 한도의 36%다(수정 확인 10회차, 20 MiB/s에서 7.22. 그 전에는
    # 구현 중 10 MiB/s에서 3.76, 38%). 첫 한도에서 그만큼 느려져도 "따라 바뀜"(내리기 전 중앙값 > 새 한도의 101%)이
    # 깨지지 않아야 한다
    assert 0.36 * demo.LIMIT > demo.NEW_LIMIT * demo.HIGH


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
        if method == "PATCH":
            return demo.Reply(202, {"azure-asyncoperation": "http://op/patch"}, b"")
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


# --- 6단계 판정 (가짜 fio) ---


class FakeFio:
    """docker exec로 돈 fio마다 JSON 출력을 차례로 돌려준다. 값은 6 s 동안 쓴 바이트로 만든 MiB/s다."""

    def __init__(self, *mibps):
        self.mibps = list(mibps)

    def __call__(self, argv, timeout=None):
        job = {"error": 0, "write": {"io_bytes": round(self.mibps.pop(0) * 6 * 1048576), "runtime": 6000}}
        return subprocess.CompletedProcess(argv, 0, json.dumps({"jobs": [job]}), "")


def test_step6_shows_slow_storage_as_a_note_not_a_failure(capsys):
    # 검증 1회차에 실패한 모양(중앙값 72%)을 첫 한도에 맞춘 값이다. 한도는 지켰고 내린 뒤 따라 바뀌었다
    slow = [round(demo.LIMIT * r, 2) for r in (0.715, 0.624, 0.995)]
    demo.Demo(FakeApi(), FakeFio(*slow, 4.97, 4.96, 4.97)).step6()
    out = capsys.readouterr().out
    assert f"[6] fio write on vol-v41 with the limit {demo.LIMIT:g} MiB/s: " in out
    assert "= 72%)" in out
    assert "[6]   the storage wrote slower than the limit this time" in out
    assert f"[6] fio write on vol-v41 with the limit {demo.NEW_LIMIT:g} MiB/s: 4.97, 4.96, 4.97 MiB/s" in out
    assert out.count("slower than the limit") == 1  # 99%인 두 번째 측정에는 붙지 않는다
    assert f"followed the limit: median {slow[0]:g} MiB/s under {demo.LIMIT:g} MiB/s -> 4.97 MiB/s under " in out
    assert "no run went above its ceiling (101% of the limit plus one 1 MiB I/O in the 6 s window)" in out


def test_step6_fails_when_a_run_goes_above_the_limit():
    api = FakeApi()
    over = [demo.LIMIT * 0.99, demo.LIMIT * 1.02, demo.LIMIT * 0.99]
    with pytest.raises(demo.StepFailed, match=r"above the ceiling of 20\.37 MiB/s"):
        demo.Demo(api, FakeFio(*over)).step6()
    assert "PATCH" not in [m for m, _ in api.calls]  # 한도를 넘은 채로 다음으로 가지 않는다


def test_step6_fails_when_the_throughput_does_not_follow_the_new_limit():
    # 내리기 전 중앙값이 새 한도의 101% 이하라 한도를 바꾼 효과가 보이지 않는다
    with pytest.raises(demo.StepFailed, match="did not follow"):
        demo.Demo(FakeApi(), FakeFio(5.0, 4.9, demo.LIMIT, 4.97, 4.96, 4.97)).step6()
