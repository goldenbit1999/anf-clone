"""볼륨 NFS 서버 인스턴스 (볼륨 설계 결정 17·18, ADR D-12 = S2 T1n).

볼륨마다 knfsd를 자기 네트워크 네임스페이스(privileged 컨테이너)에서 하나씩 띄운다. knfsd의 서버 신원,
스레드, export 캐시가 netns마다 따로라서, NFSv4.1 클라이언트가 볼륨들을 연결 하나로 합치지 않고
FR-08에서 볼륨마다 처리량을 제한할 수 있다 (S2).

ONTAP 대응 [추론]: 인스턴스의 IP = data LIF, 인스턴스 = 그 LIF로 NFS를 제공하는 SVM의 NFS 서버.
ONTAP은 SVM 하나가 여러 볼륨을 서비스하지만 클론은 볼륨마다 하나를 둔다.
"""

import json
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
# 진입점이 서비스를 시작한 뒤(유예 기간 없이) 만드는 준비 표시. 0.5초 간격으로 60초까지 기다린다
READY_FILE = "/run/anf-ready"
READY_ATTEMPTS = 120
READY_RETRY_SECONDS = 0.5
_SETUP_HINT = "Run scripts/setup-wsl-dataplane.sh as root first."


class StartupError(Exception):
    """agent가 뜰 수 없는 호스트 상태. 메시지에 고칠 방법을 넣는다."""


class InstanceError(Exception):
    """볼륨 인스턴스가 서비스를 시작하지 못했다. 같은 요청을 다시 보내면 인스턴스를 다시 시작한다."""


def container_name(uuid: str) -> str:
    return "anf-nfs-" + uuid.replace("-", "")


class NfsInstances:
    def __init__(self, runner: Runner, ns: Path, sleep: Callable[[float], None] = time.sleep):
        self._run = runner.run
        self._ns = ns
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

    def ensure_shared_ns(self) -> None:
        """WSL의 /는 private 마운트라 컨테이너의 rslave 바인드가 거절된다. ns를 자기 자신에 바인드하고
        공유 마운트로 만든다. 그러면 호스트에서 나중에 ns 아래에 하는 마운트도 인스턴스에 보인다."""
        result = self._run(["findmnt", "-no", "PROPAGATION", "--mountpoint", str(self._ns)], check=False)
        if result.returncode != 0:
            self._run(["mount", "--bind", str(self._ns), str(self._ns)])
        if "shared" not in result.stdout.strip().split(","):
            self._run(["mount", "--make-rshared", str(self._ns)])

    def ensure(self, uuid: str, token: str, ip: str, protocol: str) -> None:
        """인스턴스가 서비스하고 있게 한다. 호스트에 볼륨이 마운트된 뒤에 부른다.
        `docker run`은 진입점이 knfsd를 띄우기 전에 돌아오므로 준비 표시를 기다린다."""
        name = container_name(uuid)
        state = self._state(name)
        if state == "stopped":  # 재시작 정책이 없다. WSL 재시작 뒤 agent가 다시 띄운다
            self._run(["docker", "start", name])
        elif state is None:
            self._run([
                "docker", "run", "-d", "--name", name, "--network", NETWORK, "--ip", ip, "--privileged",
                "--mount", f"type=bind,src={self._ns},dst=/export,bind-propagation=rslave",
                "-e", f"ANF_TOKEN={token}", "-e", f"ANF_FSID={uuid}", "-e", f"ANF_PROTO={protocol}", IMAGE,
            ])
        self._wait_ready(name)

    def remove(self, uuid: str) -> None:
        """멈추고 지운다. docker stop의 SIGTERM으로 진입점이 잠금 해제와 `rpc.nfsd 0`을 한다."""
        name = container_name(uuid)
        state = self._state(name)
        if state == "running":
            self._run(["docker", "stop", "-t", "30", name])
        if state is not None:
            self._run(["docker", "rm", name])

    def _wait_ready(self, name: str) -> None:
        for _ in range(READY_ATTEMPTS):
            if self._run(["docker", "exec", name, "test", "-e", READY_FILE], check=False).returncode == 0:
                return
            if self._state(name) != "running":
                logs = self._run(["docker", "logs", "--tail", "20", name], check=False)
                raise InstanceError(f"instance {name} exited before it was ready: {(logs.stdout + logs.stderr).strip()}")
            self._sleep(READY_RETRY_SECONDS)
        raise InstanceError(f"instance {name} was not ready after {READY_ATTEMPTS * READY_RETRY_SECONDS:.0f} s")

    def _state(self, name: str) -> str | None:
        result = self._run(["docker", "inspect", "-f", "{{.State.Running}}", name], check=False)
        if result.returncode != 0:
            return None
        return "running" if result.stdout.strip() == "true" else "stopped"
