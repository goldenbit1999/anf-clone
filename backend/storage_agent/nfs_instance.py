"""볼륨 NFS 서버 인스턴스 (볼륨 설계 결정 17·18, ADR D-12 = S2 T1n, 스냅샷 설계 결정 1·6·7, 처리량 설계 결정 9·10).

볼륨마다 knfsd를 자기 네트워크 네임스페이스(privileged 컨테이너)에서 하나씩 띄운다. knfsd의 서버 신원,
스레드, export 캐시가 netns마다 따로라서, NFSv4.1 클라이언트가 볼륨들을 연결 하나로 합치지 않고
FR-08에서 볼륨마다 처리량을 제한할 수 있다 (S2).

export 표는 볼륨마다 파일 하나다(`<exports>/<uuid 32자리>/volume.exports`). agent가 볼륨과 스냅샷 상태로
다시 쓰고, 인스턴스는 그 디렉터리를 `/etc/exports.d`로 읽기 전용 바인드해 `exportfs -ra`로 적용한다.
그래서 인스턴스가 재시작해도 스냅샷 export가 돌아온다 (S4 E5·F1).

ONTAP 대응 [추론]: 인스턴스의 IP = data LIF, 인스턴스 = 그 LIF로 NFS를 제공하는 SVM의 NFS 서버.
ONTAP은 SVM 하나가 여러 볼륨을 서비스하지만 클론은 볼륨마다 하나를 둔다.
"""

import json
import os
import shutil
import time
from collections.abc import Callable
from pathlib import Path

from storage_agent.runner import Runner

IMAGE = "anf-nfs-server"
NETWORK = "anf-vnet"
SUBNET = "172.30.0.0/24"
IP_RANGE = "172.30.0.0/25"  # Docker가 클라이언트 컨테이너에 주는 범위 (.2~.127)
# 볼륨 인스턴스의 고정 IP. agent가 LV 태그로 정한다 (결정 18)
VOLUME_IPS = [f"172.30.0.{i}" for i in range(129, 255)]
# 진입점이 서비스를 시작한 뒤 만드는 준비 표시. 0.5초 간격으로 150초까지 기다린다.
# 되찾을 NFSv4 클라이언트 기록이 있으면 진입점이 유예 기간(grace 45초)이 끝날 때까지 기다리기 때문이다 (스냅샷 결정 1)
READY_FILE = "/run/anf-ready"
READY_ATTEMPTS = 300
READY_RETRY_SECONDS = 0.5
EXPORTS_FILE = "volume.exports"
# ANF 기본 export 규칙: 모든 클라이언트, 읽기·쓰기, root 허용. 클라이언트는 `*`로 쓴다(`0.0.0.0/0`은
# mountd에서 어떤 클라이언트와도 맞지 않았다). mp: 마운트 지점이 아니면(호스트 마운트 전) export하지 않는다.
# crossmnt: 클라이언트가 볼륨 안의 스냅샷 마운트로 넘어간다
VOLUME_OPTIONS = "rw,sync,no_subtree_check,no_root_squash,secure,crossmnt,mp"
# 스냅샷은 자기 fsid로 따로 export한다. thin 스냅샷의 ext4 UUID가 원본과 같아서 부모의 crossmnt만으로는
# 파일 핸들이 겹쳐 Stale file handle이 된다 (S4 E1·E2)
SNAPSHOT_OPTIONS = "ro,sync,no_subtree_check,no_root_squash,secure,mp"
_SETUP_HINT = "Run scripts/setup-wsl-dataplane.sh as root first."
# HTB는 헤더를 포함한 wire 바이트를 센다. MTU 1500, TCP 타임스탬프의 MSS 1448에서 데이터/wire 이론 상한이
# 1448/1514 = 0.9564라서, 이 값으로 나누면 어떤 I/O 모양에서도 데이터가 한도를 넘지 않는다 (처리량 결정 12, S7 Q7)
DATA_PER_WIRE = 0.9564
IFB = "ifb0"  # 인스턴스 netns 안의 IFB. netns마다 따로라 모든 인스턴스가 같은 이름을 쓴다 (처리량 결정 9, S7 N4)
_REDIRECT = ["matchall", "action", "mirred", "egress", "redirect", "dev", IFB]


def htb_rate_bits(mibps: float) -> int:
    """볼륨 한도(MiB/s)를 걸 HTB rate(bit/s 정수)."""
    return round(mibps * 1048576 * 8 / DATA_PER_WIRE)


class StartupError(Exception):
    """agent가 뜰 수 없는 호스트 상태. 메시지에 고칠 방법을 넣는다."""


class InstanceError(Exception):
    """볼륨 인스턴스가 서비스를 시작하지 못했다. 같은 요청을 다시 보내면 인스턴스를 다시 시작한다."""


def container_name(uuid: str) -> str:
    return "anf-nfs-" + uuid.replace("-", "")


class NfsInstances:
    def __init__(self, runner: Runner, ns: Path, exports: Path, sleep: Callable[[float], None] = time.sleep):
        self._run = runner.run
        self._ns = ns
        self._exports = exports
        self._sleep = sleep

    def check_host(self) -> None:
        """agent 시작 검사 (§6.1): Docker, 이미지, anf-vnet 주소 범위."""
        if self._run(["docker", "info", "-f", "{{.ServerVersion}}"], check=False).returncode != 0:
            raise StartupError(f"Docker Engine is not available. {_SETUP_HINT}")
        if self._run(["docker", "image", "inspect", "-f", "{{.Id}}", IMAGE], check=False).returncode != 0:
            raise StartupError(f"Image '{IMAGE}' is missing. {_SETUP_HINT}")
        result = self._run(["docker", "network", "inspect", NETWORK, "-f", "{{json .IPAM.Config}}"], check=False)
        if result.returncode != 0:
            raise StartupError(f"Docker network '{NETWORK}' is missing. {_SETUP_HINT}")
        configs = json.loads(result.stdout)
        if not any(c.get("Subnet") == SUBNET and c.get("IPRange") == IP_RANGE for c in configs):
            raise StartupError(
                f"Docker network '{NETWORK}' must have subnet {SUBNET} and ip-range {IP_RANGE} "
                f"(volume IPs are .129-.254), but has {configs}. {_SETUP_HINT}")
        # knfsd의 NFSv4 위임은 VFS lease 위에서 돈다. 켜져 있으면 되돌린 뒤 v4.1 클라이언트의 열린 파일이
        # 16~32 s 동안 되돌리기 전 캐시를 읽는다. netns별 설정이 없어 커널 전역으로 끈다 (되돌리기 설계 결정 1, S5 B2)
        if self._run(["sysctl", "-n", "fs.leases-enable"], check=False).stdout.strip() != "0":
            raise StartupError(
                "NFSv4 delegations must be off: fs.leases-enable must be 0, or NFSv4.1 clients read stale "
                f"data after a snapshot revert. {_SETUP_HINT}")
        # 처리량 한도의 IFB. 저절로 올라가면 호스트 netns에 ifb0·ifb1이 덤으로 생긴다. 이미 올라와 있으면 modprobe는
        # 아무것도 하지 않는다 (처리량 결정 14, S7 N1)
        result = self._run(["modprobe", "ifb", "numifbs=0"], check=False)
        if result.returncode != 0:
            raise StartupError(f"Kernel module 'ifb' could not be loaded: {result.stderr.strip()}")

    def ensure_shared_ns(self) -> None:
        """WSL의 /는 private 마운트라 컨테이너의 rslave 바인드가 거절된다. ns를 자기 자신에 바인드하고
        공유 마운트로 만든다. 그러면 호스트에서 나중에 ns 아래에 하는 마운트도 인스턴스에 보인다."""
        result = self._run(["findmnt", "-no", "PROPAGATION", "--mountpoint", str(self._ns)], check=False)
        if result.returncode != 0:
            self._run(["mount", "--bind", str(self._ns), str(self._ns)])
        if "shared" not in result.stdout.strip().split(","):
            self._run(["mount", "--make-rshared", str(self._ns)])

    def ensure(self, uuid: str, token: str, ip: str, protocol: str, qos: float | None = None) -> None:
        """인스턴스가 서비스하고 있게 한다. 호스트에 볼륨이 마운트되고 export 파일을 쓴 뒤에 부른다.
        한도는 시작과 준비 사이에 건다: knfsd가 서비스하기 전이다 (처리량 결정 10)."""
        self.start(uuid, token, ip, protocol)
        self.limit(uuid, qos)
        self.wait_ready(uuid)

    def limit(self, uuid: str, qos: float | None) -> None:
        """인스턴스 netns의 송수신을 한도(MiB/s) 하나로 묶는다 (처리량 결정 9·10·12·13, §6.2). eth0의 clsact가
        양방향을 ifb0으로 보내고, ifb0의 HTB 클래스 1:1과 leaf fq_codel을 지난다. 그래서 읽기와 쓰기가 한도를 나눠 쓴다.
        멱등이다: 있는 것은 그대로 두고 클래스 rate만 맞춘다. ifb0과 HTB가 먼저, 필터가 나중이다.
        한도가 없으면 아무것도 하지 않는다. 명령은 호스트의 ip·tc를 nsenter로 netns 안에서 쓴다 (이미지에 없다)."""
        if qos is None:
            return
        pid = self._pid(uuid)
        if pid is None:
            raise InstanceError(f"instance {container_name(uuid)} is not running; cannot apply the throughput limit")

        def netns(*argv, check=True):
            return self._run(["nsenter", "-t", pid, "-n", *argv], check=check)

        def shown(*argv) -> list[dict]:
            return json.loads(netns("tc", "-j", *argv).stdout or "[]")

        if netns("ip", "link", "show", IFB, check=False).returncode != 0:
            netns("ip", "link", "add", IFB, "type", "ifb")
        netns("ip", "link", "set", IFB, "up")
        qdiscs = shown("qdisc", "show", "dev", IFB)
        if not any(q["kind"] == "htb" and q["handle"] == "1:" and q.get("root") for q in qdiscs):
            netns("tc", "qdisc", "add", "dev", IFB, "root", "handle", "1:", "htb", "default", "1")
        rate = f"{htb_rate_bits(qos)}bit"
        netns("tc", "class", "replace", "dev", IFB, "parent", "1:", "classid", "1:1", "htb", "rate", rate, "ceil", rate)
        if not any(q["kind"] == "fq_codel" and q.get("parent") == "1:1" for q in qdiscs):
            netns("tc", "qdisc", "add", "dev", IFB, "parent", "1:1", "handle", "10:", "fq_codel")
        if not any(q["kind"] == "clsact" for q in shown("qdisc", "show", "dev", "eth0")):
            netns("tc", "qdisc", "add", "dev", "eth0", "clsact")
        for direction in ("ingress", "egress"):
            if not any(f["kind"] == "matchall" for f in shown("filter", "show", "dev", "eth0", direction)):
                netns("tc", "filter", "add", "dev", "eth0", direction, *_REDIRECT)

    def start(self, uuid: str, token: str, ip: str, protocol: str) -> None:
        """돌고 있지 않으면 띄운다. `docker run`은 진입점이 knfsd를 띄우기 전에 돌아온다 (준비는 wait_ready)."""
        name = container_name(uuid)
        state = self._state(name)
        if state == "stopped":  # 재시작 정책이 없다. WSL 재시작 뒤 agent가 다시 띄운다
            self._run(["docker", "start", name])
        elif state is None:
            self._run([
                "docker", "run", "-d", "--name", name, "--network", NETWORK, "--ip", ip, "--privileged",
                "--mount", f"type=bind,src={self._ns},dst=/export,bind-propagation=rslave",
                "--mount", f"type=bind,src={self._exports_dir(uuid)},dst=/etc/exports.d,readonly",
                "-e", f"ANF_TOKEN={token}", "-e", f"ANF_PROTO={protocol}", IMAGE,
            ])

    def wait_ready(self, uuid: str) -> None:
        name = container_name(uuid)
        for _ in range(READY_ATTEMPTS):
            if self._run(["docker", "exec", name, "test", "-e", READY_FILE], check=False).returncode == 0:
                return
            if self._state(name) != "running":
                logs = self._run(["docker", "logs", "--tail", "20", name], check=False)
                raise InstanceError(f"instance {name} exited before it was ready: {(logs.stdout + logs.stderr).strip()}")
            self._sleep(READY_RETRY_SECONDS)
        raise InstanceError(f"instance {name} was not ready after {READY_ATTEMPTS * READY_RETRY_SECONDS:.0f} s")

    def remove(self, uuid: str) -> None:
        """멈추고 지운다. docker stop의 SIGTERM으로 진입점이 잠금 해제와 `rpc.nfsd 0`을 한다."""
        name = container_name(uuid)
        state = self._state(name)
        if state == "running":
            self._run(["docker", "stop", "-t", "30", name])
        if state is not None:
            self._run(["docker", "rm", name])

    # --- export 표 (스냅샷 결정 6·7) ---

    def write_exports(self, uuid: str, token: str, snapshots: list[tuple[str, str]]) -> None:
        """볼륨 줄과 스냅샷(이름, uuid)마다 한 줄을 파일에 쓰고, 인스턴스가 돌고 있으면 적용한다.
        `exportfs -ra`는 파일에서 빠진 줄을 unexport한다. 적용이 실패했을 수 있으므로 내용이 같아도 늘 적용한다."""
        lines = [f"/{token} *({VOLUME_OPTIONS},fsid={uuid})\n"]
        lines += [f"/{token}/.snapshot/{name} *({SNAPSHOT_OPTIONS},fsid={snap})\n" for name, snap in sorted(snapshots)]
        directory = self._exports_dir(uuid)
        directory.mkdir(parents=True, exist_ok=True)
        tmp = directory / (EXPORTS_FILE + ".tmp")  # exports.d는 *.exports만 읽는다
        tmp.write_text("".join(lines))
        os.replace(tmp, directory / EXPORTS_FILE)  # 진입점이 반쯤 쓴 파일을 읽지 않게 바꿔 넣는다
        if self._state(container_name(uuid)) == "running":
            self._run(["docker", "exec", container_name(uuid), "exportfs", "-ra"])

    def remove_exports(self, uuid: str) -> None:
        shutil.rmtree(self._exports_dir(uuid), ignore_errors=True)

    def unlock(self, uuid: str, path: str) -> None:
        """인스턴스의 knfsd가 `ns` 아래 path의 파일시스템에 잡은 잠금과 NFSv4 상태를 푼다. 경로는 인자로 넘긴다(셸 해석 없음)."""
        name = container_name(uuid)
        if self._state(name) == "running":
            self._run(["docker", "exec", name, "sh", "-c", 'echo "$1" > /proc/fs/nfsd/unlock_filesystem', "unlock",
                       f"/export/{path}"])

    # --- 되돌리기 창 (되돌리기 설계 결정 3·13) ---

    def block(self, uuid: str) -> bool:
        """인스턴스 netns로 들어오는 요청을 막고 knfsd의 export 캐시를 비운다. 그동안 클라이언트는 hard 마운트
        재전송으로 기다리고, 창이 닫히면 이어 간다 (S5: 오류 0, 2~5 s 멈춤). 인스턴스가 돌지 않으면 False."""
        pid = self._pid(uuid)
        if pid is None:
            return False
        if self._iptables(pid, "-C", check=False).returncode != 0:  # 다시 해도 규칙은 하나다
            self._iptables(pid, "-I")
        self._run(["docker", "exec", container_name(uuid), "exportfs", "-f"])
        return True

    def unblock(self, uuid: str) -> None:
        pid = self._pid(uuid)
        if pid is None:  # 멈춘 인스턴스의 netns는 규칙과 함께 사라졌다
            return
        while self._iptables(pid, "-C", check=False).returncode == 0:
            self._iptables(pid, "-D")

    def _iptables(self, pid: str, op: str, check: bool = True):
        # 호스트의 iptables로 인스턴스 netns에 들어간다. 이미지에 iptables가 없어도 된다 (결정 13)
        return self._run(["nsenter", "-t", pid, "-n", "iptables", op, "INPUT", "-i", "eth0", "-j", "DROP"],
                         check=check)

    def _pid(self, uuid: str) -> str | None:
        result = self._run(["docker", "inspect", "-f", "{{.State.Pid}}", container_name(uuid)], check=False)
        pid = result.stdout.strip()
        return pid if result.returncode == 0 and pid not in ("", "0") else None

    def _exports_dir(self, uuid: str) -> Path:
        return self._exports / uuid.replace("-", "")

    def _state(self, name: str) -> str | None:
        result = self._run(["docker", "inspect", "-f", "{{.State.Running}}", name], check=False)
        if result.returncode != 0:
            return None
        return "running" if result.stdout.strip() == "true" else "stopped"
