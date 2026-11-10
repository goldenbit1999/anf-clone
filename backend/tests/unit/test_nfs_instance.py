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
    htb_rate_bits,
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


# --- 되돌리기 창: 인스턴스 입력 차단 (되돌리기 설계 결정 3·13) ---

PID = ["docker", "inspect", "-f", "{{.State.Pid}}", NAME]
RULE = ["INPUT", "-i", "eth0", "-j", "DROP"]


def iptables(op):
    return ["nsenter", "-t", "4242", "-n", "iptables", op, *RULE]


def test_block_drops_input_in_the_instance_netns_and_flushes_exports(runner, instances):
    # 클라이언트는 hard 마운트 재전송으로 기다린다. export 캐시를 비워야 언마운트된다 (S5)
    runner.respond("docker inspect -f {{.State.Pid}}", 0, "4242\n")
    runner.respond("nsenter -t 4242 -n iptables -C", 1)  # 아직 규칙이 없다
    assert instances.block(U) is True
    assert runner.calls == [PID, iptables("-C"), iptables("-I"), ["docker", "exec", NAME, "exportfs", "-f"]]


def test_block_again_does_not_add_a_second_rule(runner, instances):
    runner.respond("docker inspect -f {{.State.Pid}}", 0, "4242\n")
    assert instances.block(U) is True
    assert iptables("-I") not in runner.calls


@pytest.mark.parametrize("inspect", [(1, ""), (0, "0\n")])
def test_block_without_a_running_instance_does_nothing(runner, instances, inspect):
    runner.respond("docker inspect -f {{.State.Pid}}", *inspect)
    assert instances.block(U) is False
    assert runner.calls == [PID]


def test_unblock_removes_every_copy_of_the_rule(runner, instances):
    runner.respond("docker inspect -f {{.State.Pid}}", 0, "4242\n")
    runner.sequence("nsenter -t 4242 -n iptables -C", (0, ""), (0, ""), (1, ""))
    instances.unblock(U)
    assert runner.calls == [PID, iptables("-C"), iptables("-D"), iptables("-C"), iptables("-D"), iptables("-C")]


@pytest.mark.parametrize("inspect", [(1, ""), (0, "0\n")])
def test_unblock_without_a_running_instance_does_nothing(runner, instances, inspect):
    # 멈춘 인스턴스의 netns와 규칙은 컨테이너와 함께 사라졌다
    runner.respond("docker inspect -f {{.State.Pid}}", *inspect)
    instances.unblock(U)
    assert runner.calls == [PID]


# --- 처리량 한도: 인스턴스 netns 안의 IFB + HTB (처리량 설계 결정 9·10·12·13, §6.2) ---

NETNS = ["nsenter", "-t", "4242", "-n"]
# 새 netns: ifb0이 없고, eth0에는 veth 기본 qdisc만 있다 (WSL에서 본 `tc -j` 출력)
FRESH_ETH0 = json.dumps([{"kind": "noqueue", "handle": "0:", "root": True, "options": {}}])
HTB_ROOT = {"kind": "htb", "handle": "1:", "root": True, "options": {"r2q": 10, "default": "0x1"}}
LEAF = {"kind": "fq_codel", "handle": "10:", "parent": "1:1", "options": {"limit": 10240}}
CLSACT = {"kind": "clsact", "handle": "ffff:", "parent": "ffff:fff1", "options": {}}
MATCHALL = json.dumps([{"protocol": "all", "pref": 49152, "kind": "matchall", "chain": 0},
                       {"protocol": "all", "pref": 49152, "kind": "matchall", "chain": 0,
                        "options": {"handle": 1, "actions": [{"kind": "mirred", "to_dev": "ifb0"}]}}])


def netns(*argv):
    return [*NETNS, *argv]


def class_replace(bits):
    return netns("tc", "class", "replace", "dev", "ifb0", "parent", "1:", "classid", "1:1",
                 "htb", "rate", f"{bits}bit", "ceil", f"{bits}bit")


QUERIES = [netns("ip", "link", "show", "ifb0"), netns("tc", "-j", "qdisc", "show", "dev", "ifb0"),
           netns("tc", "-j", "qdisc", "show", "dev", "eth0"),
           netns("tc", "-j", "filter", "show", "dev", "eth0", "ingress"),
           netns("tc", "-j", "filter", "show", "dev", "eth0", "egress")]


@pytest.mark.parametrize("mibps, bits", [(10, 87710247), (0.062, 543804), (6.312, 55362708), (4500, 39469611041)])
def test_htb_rate_corrects_for_header_bytes(mibps, bits):
    # 데이터/wire 이론 상한 1448/1514 = 0.9564로 나눈다. 그래서 데이터가 한도를 넘지 않는다 (결정 12, S7 Q7)
    assert htb_rate_bits(mibps) == bits


def test_limit_builds_ifb_htb_and_filters_inside_the_instance_netns(runner, instances):
    # ifb0과 HTB를 먼저 만들고 필터는 나중이다. 없는 장치로 redirect하면 트래픽이 버려진다 (S7 L6)
    runner.respond("docker inspect -f {{.State.Pid}}", 0, "4242\n")
    runner.respond("nsenter -t 4242 -n ip link show ifb0", 1)
    runner.respond("nsenter -t 4242 -n tc -j qdisc show dev ifb0", 0, json.dumps(
        [{"kind": "fq_codel", "handle": "0:", "root": True, "options": {}}]))  # 새 IFB의 기본 qdisc
    runner.respond("nsenter -t 4242 -n tc -j qdisc show dev eth0", 0, FRESH_ETH0)
    runner.respond("nsenter -t 4242 -n tc -j filter show", 0, "[]")
    instances.limit(U, 10)
    assert [c for c in runner.calls if c not in QUERIES] == [
        PID,
        netns("ip", "link", "add", "ifb0", "type", "ifb"),
        netns("ip", "link", "set", "ifb0", "up"),
        netns("tc", "qdisc", "add", "dev", "ifb0", "root", "handle", "1:", "htb", "default", "1"),
        class_replace(87710247),
        netns("tc", "qdisc", "add", "dev", "ifb0", "parent", "1:1", "handle", "10:", "fq_codel"),
        netns("tc", "qdisc", "add", "dev", "eth0", "clsact"),
        netns("tc", "filter", "add", "dev", "eth0", "ingress", "matchall", "action", "mirred", "egress",
              "redirect", "dev", "ifb0"),
        netns("tc", "filter", "add", "dev", "eth0", "egress", "matchall", "action", "mirred", "egress",
              "redirect", "dev", "ifb0"),
    ]


def test_limit_again_only_replaces_the_class_rate(runner, instances):
    # 이미 걸린 인스턴스: 장치·qdisc·필터는 그대로 두고 rate만 바꾼다. HTB 루트에 replace는 실패한다 (S7 N8)
    runner.respond("docker inspect -f {{.State.Pid}}", 0, "4242\n")
    runner.respond("nsenter -t 4242 -n tc -j qdisc show dev ifb0", 0, json.dumps([HTB_ROOT, LEAF]))
    runner.respond("nsenter -t 4242 -n tc -j qdisc show dev eth0", 0,
                   json.dumps([json.loads(FRESH_ETH0)[0], CLSACT]))
    runner.respond("nsenter -t 4242 -n tc -j filter show", 0, MATCHALL)
    instances.limit(U, 30)
    assert [c for c in runner.calls if c not in QUERIES] == [
        PID, netns("ip", "link", "set", "ifb0", "up"), class_replace(htb_rate_bits(30))]


def test_limit_adds_only_what_is_missing(runner, instances):
    # 중간에 멈춘 걸기: HTB 루트는 있고 leaf·필터 하나가 없다
    runner.respond("docker inspect -f {{.State.Pid}}", 0, "4242\n")
    runner.respond("nsenter -t 4242 -n tc -j qdisc show dev ifb0", 0, json.dumps([HTB_ROOT]))
    runner.respond("nsenter -t 4242 -n tc -j qdisc show dev eth0", 0,
                   json.dumps([json.loads(FRESH_ETH0)[0], CLSACT]))
    runner.respond("nsenter -t 4242 -n tc -j filter show dev eth0 ingress", 0, MATCHALL)
    runner.respond("nsenter -t 4242 -n tc -j filter show dev eth0 egress", 0, "[]")
    instances.limit(U, 10)
    assert [c for c in runner.calls if c not in QUERIES] == [
        PID, netns("ip", "link", "set", "ifb0", "up"), class_replace(87710247),
        netns("tc", "qdisc", "add", "dev", "ifb0", "parent", "1:1", "handle", "10:", "fq_codel"),
        netns("tc", "filter", "add", "dev", "eth0", "egress", "matchall", "action", "mirred", "egress",
              "redirect", "dev", "ifb0"),
    ]


def test_limit_without_a_limit_does_nothing(runner, instances):
    # 한도 태그가 없는 볼륨은 제한하지 않는다. 걸린 tc를 지우는 경로는 없다 (결정 11)
    instances.limit(U, None)
    assert runner.calls == []


@pytest.mark.parametrize("inspect", [(1, ""), (0, "0\n")])
def test_limit_without_a_running_instance_fails(runner, instances, inspect):
    runner.respond("docker inspect -f {{.State.Pid}}", *inspect)
    with pytest.raises(InstanceError, match="not running"):
        instances.limit(U, 10)


def test_ensure_applies_the_limit_after_start_and_before_ready(runner, instances):
    # knfsd가 서비스하기 전에 제한이 걸린다. 준비 뒤에 걸면 그사이 제한 없이 흐른다 (결정 10, S7 L1·L2·L5)
    runner.respond("docker inspect -f {{.State.Pid}}", 0, "4242\n")
    runner.respond("docker inspect", 0, "false\n")
    runner.respond("nsenter -t 4242 -n tc -j qdisc show dev ifb0", 0, json.dumps([HTB_ROOT, LEAF]))
    runner.respond("nsenter -t 4242 -n tc -j qdisc show dev eth0", 0, json.dumps([CLSACT]))
    runner.respond("nsenter -t 4242 -n tc -j filter show", 0, MATCHALL)
    instances.ensure(U, "vol1", "172.30.0.129", "nfs4.1", 10)
    order = [c for c in runner.calls if c in (["docker", "start", NAME], class_replace(87710247), READY_CHECK)]
    assert order == [["docker", "start", NAME], class_replace(87710247), READY_CHECK]


# --- ns 공유 마운트 ---


def test_shared_ns_from_plain_directory(runner, instances):
    # WSL의 /는 private라 rslave 바인드가 거절된다. ns를 자기 자신에 바인드하고 공유로 만든다.
    # 바인드는 private로 한 번 떼어 낸 뒤 rshared로 만든다: 자기 peer group을 받는다 (FR-11 data-plane 결정 1)
    runner.respond("findmnt", 1)
    instances.ensure_shared_ns()
    assert runner.calls[1:] == [["mount", "--bind", str(NS), str(NS)], ["mount", "--make-private", str(NS)],
                                ["mount", "--make-rshared", str(NS)]]


def test_shared_ns_new_bind_leaves_the_peer_group_of_a_shared_root(runner, instances):
    # systemd 호스트(GitHub 러너 포함)는 /가 shared라 새 바인드가 /의 peer group을 물려받아 이미 shared로 보인다.
    # 그대로 두면 ns 아래 마운트가 가려진 원래 디렉터리에도 복제돼 호스트 마운트 표에 두 번 나온다 (S3 Q7)
    runner.sequence("findmnt", (1, ""), (0, "shared\n"))
    instances.ensure_shared_ns()
    mounts = [c for c in runner.calls if c[0] == "mount"]
    assert mounts == [["mount", "--bind", str(NS), str(NS)], ["mount", "--make-private", str(NS)],
                      ["mount", "--make-rshared", str(NS)]]


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
    runner.respond("sysctl -n fs.leases-enable", 0, "0\n")
    instances.check_host()
    assert ["sysctl", "-n", "fs.leases-enable"] in runner.calls
    # 모듈이 저절로 올라가면 호스트 netns에 ifb0·ifb1이 덤으로 생긴다. 이미 올라와 있으면 modprobe는 아무것도 하지 않는다
    # (처리량 결정 14, S7 N1)
    assert ["modprobe", "ifb", "numifbs=0"] in runner.calls


def test_check_host_fails_when_ifb_cannot_be_loaded(runner, instances):
    runner.respond("docker network inspect", 0, GOOD_NETWORK)
    runner.respond("sysctl -n fs.leases-enable", 0, "0\n")
    runner.respond("modprobe", 1)
    with pytest.raises(StartupError, match="ifb"):
        instances.check_host()


@pytest.mark.parametrize("prefix, returncode, stdout, words", [
    ("docker info", 1, "", "Docker"),
    ("docker image inspect", 1, "", "anf-nfs-server"),
    ("docker network inspect", 1, "", "anf-vnet"),
    ("docker network inspect", 0, json.dumps([{"Subnet": "172.30.0.0/24", "IPRange": ""}]), "ip-range"),
    # NFSv4 위임이 켜져 있으면 되돌린 뒤 v4.1 클라이언트가 옛 캐시를 읽는다 (되돌리기 설계 결정 1, S5 B2)
    ("sysctl -n fs.leases-enable", 0, "1\n", "fs.leases-enable"),
])
def test_check_host_fails_with_a_hint(runner, instances, prefix, returncode, stdout, words):
    runner.respond("docker network inspect", 0, GOOD_NETWORK)
    runner.respond("sysctl -n fs.leases-enable", 0, "0\n")
    runner.respond(prefix, returncode, stdout)
    with pytest.raises(StartupError) as e:
        instances.check_host()
    assert words in str(e.value)
    assert "setup-wsl-dataplane.sh" in str(e.value)
