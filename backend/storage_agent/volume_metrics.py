"""storage agent의 `/metrics` 수집기 (메트릭 설계 §2.1, 결정 3~9, 스파이크 S8).

값은 스크레이프 때 읽는다. 읽기만 하고 tc·export·LVM 상태를 바꾸지 않는다.
- 사용량: 볼륨 마운트의 `statvfs` (클라이언트 `df`와 같다. 스냅샷 공간은 빠진다, 결정 7)
- 처리량·요청 수: 볼륨 인스턴스 netns의 `/proc/<pid>/net/rpc/nfsd`. `io`·`rpc`·`proc4ops`는 netns별이고
  `proc3`는 모든 netns의 합이라 쓰지 않는다 (S8 Q1). 인스턴스가 다시 뜨면 0부터 다시 센다(보정하지 않는다)
- 한도·스냅샷 수: LVM 태그, aggregate: `dmsetup status` (볼륨 관리자)
- 인스턴스 pid: Docker API 소켓 (`docker inspect` CLI는 호출마다 약 150 ms, S8 Q6)

한 볼륨의 읽기 실패는 그 볼륨만 빠지고 `anf_agent_scrape_errors_total`이 는다.
"""

import http.client
import json
import logging
import os
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily

from storage_agent.nfs_instance import container_name

log = logging.getLogger(__name__)

MIB = 1 << 20
LABELS = ["volume_uuid", "creation_token", "protocol"]
OP_READ, OP_WRITE = 25, 38  # NFSv4 연산 번호 (RFC 8881 §16.2)
DOCKER_SOCKET = "/var/run/docker.sock"


@dataclass(frozen=True)
class NfsdStats:
    read_bytes: int  # `io` 줄: 클라이언트가 읽은·쓴 데이터 바이트 (fio 바이트와 같다, S8 Q2)
    write_bytes: int
    requests: int  # `rpc` 줄의 호출 수. v3는 프로시저 호출, v4.1은 COMPOUND (결정 4)
    read_ops: int  # `proc4ops`의 READ·WRITE. v4.1 볼륨에서만 뜻이 있다
    write_ops: int


def parse_nfsd(text: str) -> NfsdStats:
    lines = {key: values for key, *values in (line.split() for line in text.splitlines() if line.strip())}
    read, write = (int(n) for n in lines["io"])
    ops = [int(n) for n in lines["proc4ops"][1:]]  # 첫 값은 연산 개수다
    return NfsdStats(read, write, int(lines["rpc"][0]), ops[OP_READ], ops[OP_WRITE])


class _SocketHTTPConnection(http.client.HTTPConnection):
    def __init__(self, connect: Callable[[], socket.socket]):
        super().__init__("localhost")
        self._connect = connect

    def connect(self):
        self.sock = self._connect()


def _docker_socket() -> socket.socket:
    sock = socket.socket(socket.AF_UNIX)
    sock.settimeout(5)
    sock.connect(DOCKER_SOCKET)
    return sock


def docker_pid(name: str, connect: Callable[[], socket.socket] = _docker_socket) -> int | None:
    """컨테이너 init 프로세스의 호스트 pid. 컨테이너가 없거나 멈췄으면 None."""
    conn = _SocketHTTPConnection(connect)
    try:
        conn.request("GET", f"/containers/{name}/json")
        response = conn.getresponse()
        body = response.read()
    finally:
        conn.close()
    if response.status == 404:
        return None
    if response.status != 200:
        raise RuntimeError(f"Docker API GET /containers/{name}/json: {response.status} {body[:200]!r}")
    return json.loads(body)["State"]["Pid"] or None


class VolumeCollector:
    """prometheus_client의 사용자 정의 collector. 레지스트리가 스크레이프마다 collect()를 부른다."""

    def __init__(self, manager, pid_of: Callable[[str], int | None] = docker_pid,
                 read_text: Callable[[str], str] = lambda path: Path(path).read_text(),
                 statvfs: Callable = lambda path: os.statvfs(path),
                 clock: Callable[[], float] = time.perf_counter):
        self._manager = manager
        self._pid_of = pid_of
        self._read_text = read_text
        self._statvfs = statvfs
        self._clock = clock
        self._errors = 0
        self._lock = threading.Lock()  # 스크레이프가 겹쳐도(스레드) 오류 수를 잃지 않는다

    def collect(self):
        start = self._clock()

        def gauge(name, doc):
            return GaugeMetricFamily(name, doc, labels=LABELS)

        def counter(name, doc, extra=()):
            return CounterMetricFamily(name, doc, labels=LABELS + list(extra))

        size = gauge("anf_volume_size_bytes", "Size of the volume file system (statvfs).")
        used = gauge("anf_volume_used_bytes", "Bytes used in the active file system, without snapshots (statvfs).")
        inodes = gauge("anf_volume_inodes", "Inodes of the volume file system (statvfs).")
        inodes_used = gauge("anf_volume_inodes_used", "Inodes in use (statvfs).")
        snapshots = gauge("anf_volume_snapshots", "Snapshots of the volume.")
        limit = gauge("anf_volume_throughput_limit_bytes_per_second", "Throughput limit of the volume (QoS).")
        reads = counter("anf_volume_read_bytes_total", "Data bytes read by NFS clients (knfsd io).")
        writes = counter("anf_volume_write_bytes_total", "Data bytes written by NFS clients (knfsd io).")
        requests = counter("anf_volume_nfs_requests_total", "NFS RPC calls; COMPOUNDs for NFSv4.1 (knfsd rpc).")
        operations = counter("anf_volume_nfs_operations_total", "NFSv4.1 READ and WRITE operations (knfsd proc4ops).",
                             ["op"])
        errors = 0

        try:
            volumes = self._manager.inventory()
        except Exception as exc:
            log.warning("metrics: cannot list volumes: %s", exc)
            errors, volumes = errors + 1, []
        for v in volumes:
            labels = [v.uuid, v.token, v.protocol]
            snapshots.add_metric(labels, v.snapshots)
            if v.qos is not None:
                limit.add_metric(labels, v.qos * MIB)
            try:
                if v.mountpoint is not None:
                    st = self._statvfs(v.mountpoint)
                    size.add_metric(labels, st.f_blocks * st.f_frsize)
                    used.add_metric(labels, (st.f_blocks - st.f_bfree) * st.f_frsize)
                    inodes.add_metric(labels, st.f_files)
                    inodes_used.add_metric(labels, st.f_files - st.f_ffree)
                pid = self._pid_of(container_name(v.uuid))
                if pid is not None:  # 인스턴스가 내려가 있으면 knfsd 계열이 없다
                    stats = parse_nfsd(self._read_text(f"/proc/{pid}/net/rpc/nfsd"))
                    reads.add_metric(labels, stats.read_bytes)
                    writes.add_metric(labels, stats.write_bytes)
                    requests.add_metric(labels, stats.requests)
                    if v.protocol == "nfs4.1":
                        operations.add_metric(labels + ["read"], stats.read_ops)
                        operations.add_metric(labels + ["write"], stats.write_ops)
            except Exception as exc:
                log.warning("metrics: cannot read volume %s: %s", v.uuid, exc)
                errors += 1

        aggregate = []
        try:
            usage = self._manager.aggregate_usage()
            for name, value, doc in [
                ("anf_aggregate_data_used_bytes", usage.data_used, "Data space used in the thin pool (aggregate)."),
                ("anf_aggregate_data_size_bytes", usage.data_size, "Data space of the thin pool (aggregate)."),
                ("anf_aggregate_metadata_used_bytes", usage.metadata_used, "Metadata space used in the thin pool."),
                ("anf_aggregate_metadata_size_bytes", usage.metadata_size, "Metadata space of the thin pool."),
            ]:
                aggregate.append(GaugeMetricFamily(name, doc, value=value))
        except Exception as exc:
            log.warning("metrics: cannot read the aggregate: %s", exc)
            errors += 1

        with self._lock:
            self._errors += errors
            total = self._errors
        yield from [size, used, inodes, inodes_used, snapshots, limit, reads, writes, requests, operations, *aggregate]
        yield GaugeMetricFamily("anf_agent_scrape_duration_seconds", "Time this scrape took.",
                                value=self._clock() - start)
        yield CounterMetricFamily("anf_agent_scrape_errors_total", "Sources that could not be read.", value=total)
