"""storage agent `/metrics` 수집기: knfsd 통계 파싱, 볼륨·aggregate 메트릭, 실패 격리, Docker API pid 조회
(메트릭 설계 §2.1, 결정 3~9).

볼륨 관리자, /proc 파일, statvfs, Docker 소켓은 가짜다. 실제 값이 클라이언트 I/O와 맞는지는
`backend/tests/e2e/test_metrics_data_live.py`가 확인한다.
"""

import logging
import socket
from types import SimpleNamespace

import pytest
from prometheus_client import CollectorRegistry, generate_latest
from prometheus_client.parser import text_string_to_metric_families

from storage_agent.flexvol import AggregateUsage, VolumeInfo
from storage_agent.nfs_instance import container_name
from storage_agent.runner import CommandError, Result
from storage_agent.volume_metrics import NfsdStats, VolumeCollector, docker_pid, parse_nfsd

U1 = "11111111-2222-3333-4444-555555555555"
U2 = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
U3 = "99999999-8888-7777-6666-555555555555"
MIB = 1 << 20
USAGE = AggregateUsage(data_used=1863 * 524288, data_size=1 << 40, metadata_used=3415 * 4096,
                       metadata_size=32768 * 4096)


def nfsd_text(read=0, write=0, calls=0, v4_read=0, v4_write=0) -> str:
    """`/proc/<pid>/net/rpc/nfsd`의 모양 (WSL 커널 6.18에서 본 그대로). proc4ops는 연산 개수 뒤에 연산 번호 순서다."""
    ops = [0] * 76
    ops[25], ops[38], ops[53] = v4_read, v4_write, calls  # READ, WRITE, SEQUENCE
    proc3 = " ".join(["0"] * 22)
    return "\n".join([
        f"rc 0 {write} {calls}",
        "fh 0 0 0 0 0",
        f"io {read} {write}",
        "th 12 0 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000",
        "ra 0 0 0 0 0 0 0 0 0 0 0 0",
        f"net {calls} 0 {calls} 2",
        f"rpc {calls} 0 0 0 0",
        f"proc3 22 {proc3}",
        f"proc4 2 0 {calls}",
        "proc4ops 76 " + " ".join(map(str, ops)),
        "wdeleg_getattr 0",
        "",
    ])


def test_parse_nfsd_reads_io_rpc_and_the_v4_read_write_operations():
    text = nfsd_text(read=268435456, write=4096, calls=61249, v4_read=61245, v4_write=1)
    assert parse_nfsd(text) == NfsdStats(read_bytes=268435456, write_bytes=4096, requests=61249,
                                         read_ops=61245, write_ops=1)


class FakeManager:
    def __init__(self, volumes):
        self.volumes = volumes
        self.broken: set[str] = set()  # 실패할 메서드 이름

    def inventory(self):
        if "inventory" in self.broken:
            raise CommandError(["lvs"], Result(5, "", "  Volume group \"anf\" not found\n"))
        return self.volumes

    def aggregate_usage(self):
        if "aggregate_usage" in self.broken:
            raise CommandError(["dmsetup"], Result(1, "", "Device does not exist.\n"))
        return USAGE


V1 = VolumeInfo(U1, "vol1", "nfs3", None, "/ns/vol1", 2)
V2 = VolumeInfo(U2, "vol2", "nfs4.1", 12.5, "/ns/vol2", 0)
V3 = VolumeInfo(U3, "vol3", "nfs3", 0.062, None, 1)  # 마운트되지 않았고 인스턴스도 없다
STATVFS = {
    "/ns/vol1": SimpleNamespace(f_frsize=4096, f_blocks=250_000, f_bfree=190_000, f_files=65_536, f_ffree=65_500),
    "/ns/vol2": SimpleNamespace(f_frsize=4096, f_blocks=500_000, f_bfree=500_000, f_files=131_072, f_ffree=131_061),
}
PIDS = {container_name(U1): 4101, container_name(U2): 4202}
PROC = {
    "/proc/4101/net/rpc/nfsd": nfsd_text(read=1 * MIB, write=256 * MIB, calls=270),
    "/proc/4202/net/rpc/nfsd": nfsd_text(read=64 * MIB, write=0, calls=1030, v4_read=1024, v4_write=0),
}


def make_collector(manager, proc=None, clock=None):
    proc = PROC if proc is None else proc

    def read_text(path):
        value = proc[path]
        if isinstance(value, Exception):
            raise value
        return value

    return VolumeCollector(manager, pid_of=PIDS.get, read_text=read_text, statvfs=STATVFS.__getitem__,
                           clock=clock or iter([10.0, 10.25]).__next__)


def scrape(collector) -> dict:
    """노출 형식으로 내보내고 다시 읽어 {(샘플 이름, 라벨): 값}으로 돌려준다."""
    registry = CollectorRegistry()
    registry.register(collector)
    text = generate_latest(registry).decode()
    return {(s.name, tuple(sorted(s.labels.items()))): s.value
            for family in text_string_to_metric_families(text) for s in family.samples}


def vol(volume: VolumeInfo, **extra) -> tuple:
    labels = {"volume_uuid": volume.uuid, "creation_token": volume.token, "protocol": volume.protocol, **extra}
    return tuple(sorted(labels.items()))


def test_scrape_reports_usage_counters_and_limits_per_volume():
    samples = scrape(make_collector(FakeManager([V1, V2, V3])))

    # 사용량 (statvfs = 클라이언트 df): 크기 = blocks × frsize, used = (blocks − bfree) × frsize
    assert samples[("anf_volume_size_bytes", vol(V1))] == 250_000 * 4096
    assert samples[("anf_volume_used_bytes", vol(V1))] == 60_000 * 4096
    assert samples[("anf_volume_inodes", vol(V1))] == 65_536
    assert samples[("anf_volume_inodes_used", vol(V1))] == 36
    assert samples[("anf_volume_used_bytes", vol(V2))] == 0
    assert samples[("anf_volume_snapshots", vol(V1))] == 2
    assert samples[("anf_volume_snapshots", vol(V2))] == 0
    # 한도는 MiB/s 태그 × 1,048,576. 한도 없는 볼륨에는 계열이 없다
    assert samples[("anf_volume_throughput_limit_bytes_per_second", vol(V2))] == 12.5 * MIB
    assert ("anf_volume_throughput_limit_bytes_per_second", vol(V1)) not in samples
    # knfsd 카운터 (인스턴스 netns별)
    assert samples[("anf_volume_read_bytes_total", vol(V1))] == 1 * MIB
    assert samples[("anf_volume_write_bytes_total", vol(V1))] == 256 * MIB
    assert samples[("anf_volume_nfs_requests_total", vol(V1))] == 270
    assert samples[("anf_volume_read_bytes_total", vol(V2))] == 64 * MIB
    assert samples[("anf_volume_nfs_requests_total", vol(V2))] == 1030
    # READ·WRITE 연산 수는 NFSv4.1 볼륨만 (v3의 proc3는 모든 netns의 합이다, 결정 5)
    assert samples[("anf_volume_nfs_operations_total", vol(V2, op="read"))] == 1024
    assert samples[("anf_volume_nfs_operations_total", vol(V2, op="write"))] == 0
    assert not [key for key in samples if key[0] == "anf_volume_nfs_operations_total" and dict(key[1])["volume_uuid"] == U1]
    # aggregate
    assert samples[("anf_aggregate_data_used_bytes", ())] == USAGE.data_used
    assert samples[("anf_aggregate_data_size_bytes", ())] == USAGE.data_size
    assert samples[("anf_aggregate_metadata_used_bytes", ())] == USAGE.metadata_used
    assert samples[("anf_aggregate_metadata_size_bytes", ())] == USAGE.metadata_size
    # 수집기 자신
    assert samples[("anf_agent_scrape_duration_seconds", ())] == 0.25
    assert samples[("anf_agent_scrape_errors_total", ())] == 0


def test_a_volume_without_a_mount_or_instance_has_only_tag_series():
    samples = scrape(make_collector(FakeManager([V1, V2, V3])))
    v3 = {name for name, labels in samples if dict(labels).get("volume_uuid") == U3}
    assert v3 == {"anf_volume_snapshots", "anf_volume_throughput_limit_bytes_per_second"}
    assert samples[("anf_agent_scrape_errors_total", ())] == 0  # 내려간 인스턴스는 오류가 아니다


def test_one_volume_that_cannot_be_read_does_not_hide_the_others(caplog):
    # 인스턴스가 pid를 알려 준 뒤 사라졌다
    proc = {**PROC, "/proc/4101/net/rpc/nfsd": FileNotFoundError(2, "No such file or directory")}
    collector = make_collector(FakeManager([V1, V2]), proc=proc, clock=iter([0.0, 0.1, 1.0, 1.1]).__next__)
    with caplog.at_level(logging.WARNING, logger="storage_agent.volume_metrics"):
        samples = scrape(collector)

    assert ("anf_volume_read_bytes_total", vol(V1)) not in samples
    assert samples[("anf_volume_read_bytes_total", vol(V2))] == 64 * MIB
    assert samples[("anf_aggregate_data_used_bytes", ())] == USAGE.data_used
    assert samples[("anf_agent_scrape_errors_total", ())] == 1
    assert [r.getMessage() for r in caplog.records if U1 in r.getMessage()]
    # 오류 카운터는 누적이다
    assert scrape(collector)[("anf_agent_scrape_errors_total", ())] == 2


def test_inventory_failure_still_reports_the_aggregate():
    manager = FakeManager([V1])
    manager.broken = {"inventory"}
    samples = scrape(make_collector(manager))
    assert not [key for key in samples if key[0].startswith("anf_volume_")]
    assert samples[("anf_aggregate_data_used_bytes", ())] == USAGE.data_used
    assert samples[("anf_agent_scrape_errors_total", ())] == 1


def test_aggregate_failure_still_reports_the_volumes():
    manager = FakeManager([V1])
    manager.broken = {"aggregate_usage"}
    samples = scrape(make_collector(manager))
    assert samples[("anf_volume_used_bytes", vol(V1))] == 60_000 * 4096
    assert not [key for key in samples if key[0].startswith("anf_aggregate_")]
    assert samples[("anf_agent_scrape_errors_total", ())] == 1


# --- Docker API pid (메트릭 결정 8: `docker inspect` CLI는 호출마다 약 150 ms) ---


def fake_docker(status: int, body: bytes):
    """응답을 미리 넣어 둔 소켓 쌍. 클라이언트가 요청을 쓰면 버퍼에 있던 응답을 읽는다."""
    server, client = socket.socketpair()
    head = f"HTTP/1.1 {status} X\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n"
    server.sendall(head.encode() + body)
    return server, lambda: client


def test_docker_pid_reads_the_container_state():
    server, connect = fake_docker(200, b'{"Id": "abc", "State": {"Status": "running", "Pid": 4321}}')
    assert docker_pid("anf-nfs-1111", connect=connect) == 4321
    assert server.recv(65536).startswith(b"GET /containers/anf-nfs-1111/json HTTP/1.1\r\n")
    server.close()


@pytest.mark.parametrize("status, body", [
    (200, b'{"State": {"Status": "exited", "Pid": 0}}'),  # 멈춘 컨테이너
    (404, b'{"message": "No such container: anf-nfs-1111"}'),
])
def test_docker_pid_is_none_without_a_running_container(status, body):
    server, connect = fake_docker(status, body)
    assert docker_pid("anf-nfs-1111", connect=connect) is None
    server.close()


def test_docker_pid_fails_on_other_errors():
    server, connect = fake_docker(500, b'{"message": "boom"}')
    with pytest.raises(RuntimeError, match="500"):
        docker_pid("anf-nfs-1111", connect=connect)
    server.close()
