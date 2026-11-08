"""볼륨 NFS 서버 인스턴스: docker 명령 순서, 공유 마운트, export 파일, agent 시작 검사
(볼륨 설계 결정 17·18, §6.1, 스냅샷 설계 결정 1·6·7·13·14).

실제 컨테이너·knfsd 동작은 통합 테스트(`tests/integration/test_flexvol_linux.py`)가 확인한다.
"""

import json
from pathlib import Path

import pytest

from storage_agent.nfs_instance import (
    READY_ATTEMPTS,
    READY_RETRY_SECONDS,
    VOLUME_IPS,
    InstanceError,
    NfsInstances,
    StartupError,
    container_name,
)
from storage_agent.runner import CommandError, Result

NS = Path("/var/lib/anf-clone/ns")
U = "11111111-2222-3333-4444-555555555555"
U32 = "11111111222233334444555555555555"
NAME = "anf-nfs-" + U32
S1 = "aaaaaaaa-0000-4000-8000-000000000001"
S2 = "aaaaaaaa-0000-4000-8000-000000000002"
GOOD_NETWORK = json.dumps([{"Subnet": "172.30.0.0/24", "IPRange": "172.30.0.0/25", "Gateway": "172.30.0.1"}])
READY_CHECK = ["docker", "exec", NAME, "test", "-e", "/run/anf-ready"]


class FakeRunner:
    """argv 앞부분으로 응답을 정한다. 정하지 않은 명령은 성공한다. 응답을 여러 개 정하면 차례로 주고 마지막은 계속 준다."""

    def __init__(self):
        self.calls: list[list[str]] = []
        self.responses: dict[tuple, list[Result]] = {}

    def respond(self, prefix: str, returncode=0, stdout=""):
        self.responses[tuple(prefix.split())] = [Result(returncode, stdout, "")]

    def sequence(self, prefix: str, *results: tuple[int, str]):
        self.responses[tuple(prefix.split())] = [Result(rc, out, "") for rc, out in results]

    def run(self, argv, check=True, input=None):
        self.calls.append(argv)
        queue = next((q for p, q in self.responses.items() if tuple(argv[:len(p)]) == p), [Result(0, "", "")])
        result = queue.pop(0) if len(queue) > 1 else queue[0]
        if check and result.returncode != 0:
            raise CommandError(argv, result)
        return result


@pytest.fixture
def runner():
    return FakeRunner()


@pytest.fixture
def sleeps():
    return []


@pytest.fixture
def exports(tmp_path):
    return tmp_path / "exports"


@pytest.fixture
def instances(runner, sleeps, exports):
    return NfsInstances(runner, ns=NS, exports=exports, sleep=sleeps.append)


def test_container_name_and_volume_ips():
    assert container_name(U) == NAME
    # 클라이언트는 Docker가 .2~.127에서, 볼륨 인스턴스는 agent가 .129~.254에서 받는다 (결정 18)
    assert (VOLUME_IPS[0], VOLUME_IPS[-1], len(VOLUME_IPS)) == ("172.30.0.129", "172.30.0.254", 126)


# --- 보장 ---


def test_ensure_runs_a_new_instance(runner, instances, exports):
    # export 표는 agent가 쓰는 파일이다. 인스턴스는 그 디렉터리를 /etc/exports.d로 읽기 전용 바인드한다 (결정 7)
    runner.respond("docker inspect", 1)
    instances.ensure(U, "vol1", "172.30.0.129", "nfs4.1")
    assert runner.calls[1:] == [[
        "docker", "run", "-d", "--name", NAME, "--network", "anf-vnet", "--ip", "172.30.0.129",
        "--privileged", "--mount", f"type=bind,src={NS},dst=/export,bind-propagation=rslave",
        "--mount", f"type=bind,src={exports / U32},dst=/etc/exports.d,readonly",
        "-e", "ANF_TOKEN=vol1", "-e", "ANF_PROTO=nfs4.1", "anf-nfs-server",
    ], READY_CHECK]


def test_start_does_not_wait(runner, instances):
    # 시작 복구는 인스턴스를 모두 띄운 뒤에 준비를 기다린다 (결정 14)
    runner.respond("docker inspect", 0, "false\n")
    instances.start(U, "vol1", "172.30.0.129", "nfs4.1")
    assert runner.calls[1:] == [["docker", "start", NAME]]
    instances.wait_ready(U)
    assert runner.calls[-1] == READY_CHECK


def test_ensure_starts_a_stopped_instance(runner, instances):
    # WSL 재시작 뒤: 재시작 정책이 없으므로 컨테이너가 멈춘 채 남아 있다. 고정 IP는 그대로다
    runner.respond("docker inspect", 0, "false\n")
    instances.ensure(U, "vol1", "172.30.0.129", "nfs3")
    assert runner.calls[1:] == [["docker", "start", NAME], READY_CHECK]


def test_ensure_leaves_a_running_instance(runner, instances):
    runner.respond("docker inspect", 0, "true\n")
    instances.ensure(U, "vol1", "172.30.0.129", "nfs3")
    assert runner.calls[1:] == [READY_CHECK]


# --- 준비 대기 (1회차 AC-03 FAIL: 준비 전에 job이 끝났다) ---


def test_ensure_waits_until_the_instance_is_ready(runner, instances, sleeps):
    # 진입점은 knfsd가 유예 기간 없이 서비스할 때만 준비 표시를 만든다
    runner.sequence("docker inspect", (1, ""), (0, "true\n"))
    runner.sequence("docker exec", (1, ""), (1, ""), (0, ""))
    instances.ensure(U, "vol1", "172.30.0.129", "nfs4.1")
    assert runner.calls.count(READY_CHECK) == 3
    assert sleeps == [0.5, 0.5]


def test_ensure_fails_when_the_instance_exits(runner, instances):
    # 진입점이 knfsd를 몇 번 다시 시작해도 유예 기간이 끝나지 않으면 0이 아닌 코드로 끝난다
    runner.sequence("docker inspect", (1, ""), (0, "false\n"))
    runner.respond("docker exec", 1)
    runner.respond("docker logs", 0, "anf-nfs: NFSv4 client tracking did not start; giving up\n")
    with pytest.raises(InstanceError, match="client tracking did not start"):
        instances.ensure(U, "vol1", "172.30.0.129", "nfs4.1")


def test_ensure_gives_up_when_never_ready(runner, instances, sleeps):
    # 죽은 NFSv4.1 클라이언트 기록이 있으면 진입점이 유예 기간(grace 45초)을 기다린다. 그래서 150초까지 기다린다 (결정 1)
    runner.sequence("docker inspect", (1, ""), (0, "true\n"))
    runner.respond("docker exec", 1)
    with pytest.raises(InstanceError, match="not ready after 150 s"):
        instances.ensure(U, "vol1", "172.30.0.129", "nfs4.1")
    assert runner.calls.count(READY_CHECK) == READY_ATTEMPTS
    assert READY_ATTEMPTS * READY_RETRY_SECONDS == 150


# --- 제거 ---


def test_remove_stops_then_removes(runner, instances):
    # docker stop의 SIGTERM으로 진입점이 잠금 해제·rpc.nfsd 0을 한 뒤 끝난다
    runner.respond("docker inspect", 0, "true\n")
    instances.remove(U)
    assert runner.calls[1:] == [["docker", "stop", "-t", "30", NAME], ["docker", "rm", NAME]]


def test_remove_stopped_instance(runner, instances):
    runner.respond("docker inspect", 0, "false\n")
    instances.remove(U)
    assert runner.calls[1:] == [["docker", "rm", NAME]]


def test_remove_missing_instance(runner, instances):
    runner.respond("docker inspect", 1)
    instances.remove(U)
    assert len(runner.calls) == 1


# --- export 파일 (결정 6·7) ---

VOLUME_LINE = f"/vol1 *(rw,sync,no_subtree_check,no_root_squash,secure,crossmnt,mp,fsid={U})\n"
EXPORTFS = ["docker", "exec", NAME, "exportfs", "-ra"]


def test_write_exports_for_a_volume_without_snapshots(runner, instances, exports):
    runner.respond("docker inspect", 1)
    instances.write_exports(U, "vol1", [])
    assert (exports / U32 / "volume.exports").read_text() == VOLUME_LINE
    assert runner.calls[1:] == []  # 인스턴스가 없으면 시작할 때 진입점이 적용한다


def test_write_exports_with_snapshots_applies_to_a_running_instance(runner, instances, exports):
    # 스냅샷마다 자기 fsid로 읽기 전용 export (S4 E2). 줄은 이름순이다
    runner.respond("docker inspect", 0, "true\n")
    instances.write_exports(U, "vol1", [("weekly", S2), ("daily.2026-11-08_0010", S1)])
    assert (exports / U32 / "volume.exports").read_text() == VOLUME_LINE + (
        f"/vol1/.snapshot/daily.2026-11-08_0010 *(ro,sync,no_subtree_check,no_root_squash,secure,mp,fsid={S1})\n"
        f"/vol1/.snapshot/weekly *(ro,sync,no_subtree_check,no_root_squash,secure,mp,fsid={S2})\n"
    )
    assert runner.calls[1:] == [EXPORTFS]
    assert [p.name for p in (exports / U32).iterdir()] == ["volume.exports"]  # 임시 파일이 남지 않는다


def test_write_exports_replaces_the_file(runner, instances, exports):
    runner.respond("docker inspect", 0, "true\n")
    instances.write_exports(U, "vol1", [("s1", S1)])
    instances.write_exports(U, "vol1", [])
    assert (exports / U32 / "volume.exports").read_text() == VOLUME_LINE
    assert runner.calls.count(EXPORTFS) == 2


def test_write_exports_not_applied_to_a_stopped_instance(runner, instances):
    runner.respond("docker inspect", 0, "false\n")
    instances.write_exports(U, "vol1", [("s1", S1)])
    assert EXPORTFS not in runner.calls


def test_remove_exports(instances, exports):
    instances.write_exports(U, "vol1", [])
    instances.remove_exports(U)
    assert not (exports / U32).exists()
    instances.remove_exports(U)  # 없으면 그대로 성공


# --- 스냅샷 잠금 해제 (결정 13) ---


def test_unlock_releases_nfs_state_inside_the_instance(runner, instances):
    # 클라이언트가 스냅샷 안의 파일을 열고 있어도 umount되게 knfsd의 잠금·NFSv4 상태를 푼다 (S4 E4)
    runner.respond("docker inspect", 0, "true\n")
    instances.unlock(U, "vol1/.snapshot/s1")
    assert runner.calls[1:] == [[
        "docker", "exec", NAME, "sh", "-c", 'echo "$1" > /proc/fs/nfsd/unlock_filesystem', "unlock",
        "/export/vol1/.snapshot/s1",
    ]]


@pytest.mark.parametrize("inspect", [(1, ""), (0, "false\n")])
def test_unlock_without_a_running_instance_does_nothing(runner, instances, inspect):
    runner.respond("docker inspect", *inspect)
    instances.unlock(U, "vol1/.snapshot/s1")
    assert len(runner.calls) == 1


# --- ns 공유 마운트 ---


def test_shared_ns_from_plain_directory(runner, instances):
    # WSL의 /는 private라 rslave 바인드가 거절된다. ns를 자기 자신에 바인드하고 공유로 만든다
    runner.respond("findmnt", 1)
    instances.ensure_shared_ns()
    assert runner.calls[1:] == [["mount", "--bind", str(NS), str(NS)], ["mount", "--make-rshared", str(NS)]]


def test_shared_ns_private_mount_is_made_shared(runner, instances):
    runner.respond("findmnt", 0, "private\n")
    instances.ensure_shared_ns()
    assert runner.calls[1:] == [["mount", "--make-rshared", str(NS)]]


def test_shared_ns_already_shared(runner, instances):
    runner.respond("findmnt", 0, "shared\n")
    instances.ensure_shared_ns()
    assert len(runner.calls) == 1


# --- agent 시작 검사 ---


def test_check_host_passes(runner, instances):
    runner.respond("docker network inspect", 0, GOOD_NETWORK)
    instances.check_host()


@pytest.mark.parametrize("prefix, returncode, stdout, words", [
    ("docker info", 1, "", "Docker"),
    ("docker image inspect", 1, "", "anf-nfs-server"),
    ("docker network inspect", 1, "", "anf-vnet"),
    ("docker network inspect", 0, json.dumps([{"Subnet": "172.30.0.0/24", "IPRange": ""}]), "ip-range"),
])
def test_check_host_fails_with_a_hint(runner, instances, prefix, returncode, stdout, words):
    runner.respond("docker network inspect", 0, GOOD_NETWORK)
    runner.respond(prefix, returncode, stdout)
    with pytest.raises(StartupError) as e:
        instances.check_host()
    assert words in str(e.value)
    assert "setup-wsl-dataplane.sh" in str(e.value)
