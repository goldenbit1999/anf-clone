"""볼륨 관리자: ONTAP FlexVol을 dm-thin thin LV + ext4로 재현한다 (ADR D-11·D-12, 볼륨 설계 결정 5~10, 17, 18).

ONTAP과의 대응:
- aggregate = 씬 풀 `anf/aggr0`. 스토리지 루트의 희소 파일 → 루프 장치 → VG `anf`
- FlexVol = thin LV `vol_<uuid 32자리>` + ext4. junction path, uuid, IP, 프로토콜은 LVM 태그에 둔다 (agent에는 DB가 없다)
- SVM 네임스페이스 = `<root>/ns`. 볼륨은 `ns/<token>`에 마운트되고, 그 볼륨의 NFS 인스턴스가 `/<token>`으로 export한다
- data LIF = 볼륨 인스턴스의 IP. agent가 VOLUME_IPS에서 골라 태그로 남긴다 (결정 18)

모든 작업은 단계마다 실제 상태를 보고 이미 된 것은 건너뛴다.
그래서 어느 단계에서 멈춰도 같은 요청을 다시 하면 이어서 끝난다 (결정 10).
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from storage_agent.nfs_instance import VOLUME_IPS, NfsInstances
from storage_agent.runner import CommandError

VG = "anf"
POOL = "aggr0"
DEFAULT_ROOT = Path("/var/lib/anf-clone")
# 인스턴스를 지운 뒤에도 knfsd가 잠시 파일시스템을 잡고 있을 수 있다. 0.5초 간격으로 60초까지 다시 시도한다
UMOUNT_ATTEMPTS = 120
UMOUNT_RETRY_SECONDS = 0.5


class VolumeError(Exception):
    """요청이 현재 상태와 맞지 않는다 (같은 uuid의 다른 설정, 경로 중복, aggregate 공간 부족, IP 소진)."""


@dataclass(frozen=True)
class _Volume:
    uuid: str
    token: str
    size: int
    lv: str
    ip: str
    protocol: str

    @property
    def device(self) -> str:
        return f"/dev/{VG}/{self.lv}"


def lv_name(uuid: str) -> str:
    return "vol_" + uuid.replace("-", "")


class FlexVolManager:
    def __init__(
        self,
        runner,
        root: Path = DEFAULT_ROOT,
        aggregate_size: int = 1 << 40,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._run = runner.run
        self._sleep = sleep
        self._ns = Path(root) / "ns"
        self._image = Path(root) / "aggr0.img"
        self._aggregate_size = aggregate_size
        self.instances = NfsInstances(runner, self._ns, sleep)

    # --- aggregate와 시작 복구 ---

    def ensure_aggregate(self) -> None:
        self._ns.mkdir(parents=True, exist_ok=True)
        if not self._image.exists():
            with open(self._image, "xb") as f:
                f.truncate(self._aggregate_size)  # 희소 파일: 실제 디스크는 쓴 만큼만 쓴다
        attached = self._run(["losetup", "-j", str(self._image)]).stdout
        if attached:
            device = attached.splitlines()[0].split(":", 1)[0]
        else:  # 첫 실행이거나 WSL이 재시작돼 루프 장치가 사라졌다
            device = self._run(["losetup", "--find", "--show", str(self._image)]).stdout.strip()
        if self._run(["vgs", VG], check=False).returncode != 0:
            self._run(["vgcreate", VG, device])
        if self._run(["lvs", f"{VG}/{POOL}"], check=False).returncode != 0:
            self._run(["lvcreate", "--type", "thin-pool", "-l", "100%FREE", "-n", POOL, VG])
        self._run(["vgchange", "-ay", VG])

    def recover(self) -> None:
        """agent 시작 때: aggregate를 붙이고, ns를 공유 마운트로 만들고, 파일시스템이 있는 볼륨을 마운트해 인스턴스를 띄운다.
        ns 바인드는 볼륨 마운트보다 먼저다. 나중에 바인드하면 그 아래의 기존 마운트를 가린다."""
        self.ensure_aggregate()
        self.instances.ensure_shared_ns()
        for vol in self._report()[1]:
            if self._filesystem(vol) == "ext4":
                self._ensure_mounted(vol)
                self.instances.ensure(vol.uuid, vol.token, vol.ip, vol.protocol)

    # --- 볼륨 ---

    def create(self, uuid: str, junction_path: str, size: int, unix_permissions: int, protocol: str) -> None:
        """(1) LV → (2) 파일시스템 → (3) 마운트 → (4) 루트 초기화 → (5) 인스턴스. 입력은 agent_app이 검사했다."""
        vol = self._ensure_lv(uuid, junction_path[1:], size, protocol)
        fs = self._filesystem(vol)
        if fs is None:
            self._run(["mkfs.ext4", "-q", "-m", "0", "-U", uuid, vol.device])
        elif fs != "ext4":
            raise VolumeError(f"{vol.device} holds a {fs} file system, not ext4")
        mp = self._ensure_mounted(vol)
        # lost+found가 있으면 mkfs 직후이고 초기화 전이다. 초기화가 끝난 볼륨의 권한은 다시 바꾸지 않는다
        lost_found = mp / "lost+found"
        if lost_found.is_dir():
            self._run(["chmod", f"{unix_permissions:04d}", str(mp)])
            lost_found.rmdir()
        self.instances.ensure(uuid, vol.token, vol.ip, vol.protocol)

    def delete(self, uuid: str) -> None:
        """인스턴스 제거 → 언마운트 → 마운트 지점 제거 → LV 제거. 없는 볼륨은 성공이다.
        인스턴스의 knfsd가 파일시스템을 잡고 있으므로 인스턴스가 먼저다."""
        vol = next((v for v in self._report()[1] if v.uuid == uuid), None)
        if vol is None:
            return
        self.instances.remove(uuid)
        mp = self._mountpoint(vol)
        if str(mp) in self._mounted():
            self._umount(mp)
        if mp.is_dir():
            mp.rmdir()
        self._run(["lvremove", "-y", f"{VG}/{vol.lv}"])

    def records(self, name: str | None = None) -> list[dict]:
        mounted = self._mounted()
        return [self._record(v, mounted) for v in self._report()[1] if name is None or v.lv == name]

    def record(self, uuid: str) -> dict | None:
        return next((r for r in self.records() if r["uuid"] == uuid), None)

    # --- 내부 ---

    def _ensure_lv(self, uuid: str, token: str, size: int, protocol: str) -> _Volume:
        pool_size, volumes = self._report()
        for vol in volumes:
            if vol.uuid == uuid:
                if (vol.token, vol.size, vol.protocol) != (token, size, protocol):
                    raise VolumeError(
                        f"volume {uuid} already exists with path /{vol.token}, size {vol.size}, "
                        f"protocol {vol.protocol}"
                    )
                return vol
        for vol in volumes:
            if vol.token.lower() == token.lower():
                raise VolumeError(f"junction path /{token} is already used by volume {vol.uuid}")
        free = pool_size - sum(v.size for v in volumes)
        if size > free:
            raise VolumeError(f"aggregate {POOL} has {free} bytes left; the volume needs {size}")
        used = {v.ip for v in volumes}
        ip = next((ip for ip in VOLUME_IPS if ip not in used), None)
        if ip is None:
            raise VolumeError(f"all {len(VOLUME_IPS)} volume IPs are in use")
        vol = _Volume(uuid, token, size, lv_name(uuid), ip, protocol)
        self._run([
            "lvcreate", "--type", "thin", "-V", f"{size}b", "--thinpool", POOL, "-n", vol.lv,
            "--addtag", f"anf_path={token}", "--addtag", f"anf_uuid={uuid}",
            "--addtag", f"anf_ip={ip}", "--addtag", f"anf_proto={protocol}", VG,
        ])
        return vol

    def _report(self) -> tuple[int, list[_Volume]]:
        """씬 풀 크기와 태그가 붙은 볼륨 목록."""
        out = self._run([
            "lvs", "--reportformat", "json", "--units", "b", "--nosuffix", "-o", "lv_name,lv_size,lv_tags", VG,
        ]).stdout
        pool_size, volumes = 0, []
        for row in json.loads(out)["report"][0]["lv"]:
            tags = dict(t.split("=", 1) for t in row["lv_tags"].split(",") if "=" in t)
            if row["lv_name"] == POOL:
                pool_size = int(row["lv_size"])
            elif "anf_uuid" in tags:
                volumes.append(_Volume(tags["anf_uuid"], tags["anf_path"], int(row["lv_size"]), row["lv_name"],
                                       tags["anf_ip"], tags["anf_proto"]))
        return pool_size, volumes

    def _filesystem(self, vol: _Volume) -> str | None:
        argv = ["blkid", "-o", "value", "-s", "TYPE", vol.device]
        result = self._run(argv, check=False)
        if result.returncode == 2:  # 서명 없음: 아직 mkfs 전
            return None
        if result.returncode != 0:
            raise CommandError(argv, result)
        return result.stdout.strip()

    def _mountpoint(self, vol: _Volume) -> Path:
        return self._ns / vol.token

    def _record(self, vol: _Volume, mounted: set[str]) -> dict:
        """ONTAP 볼륨 레코드의 부분집합. 마운트돼 있으면 online이다. data_lif는 클론 확장이다 (결정 18)."""
        state = "online" if str(self._mountpoint(vol)) in mounted else "offline"
        return {
            "uuid": vol.uuid, "name": vol.lv, "size": vol.size,
            "nas": {"path": f"/{vol.token}", "protocols": [vol.protocol]},
            "state": state, "data_lif": {"ip": {"address": vol.ip}},
        }

    def _mounted(self) -> set[str]:
        return set(self._run(["findmnt", "-rn", "-o", "TARGET"]).stdout.splitlines())

    def _umount(self, mp: Path) -> None:
        for attempt in range(UMOUNT_ATTEMPTS):
            result = self._run(["umount", str(mp)], check=attempt == UMOUNT_ATTEMPTS - 1)
            if result.returncode == 0:
                return
            self._sleep(UMOUNT_RETRY_SECONDS)

    def _ensure_mounted(self, vol: _Volume) -> Path:
        mp = self._mountpoint(vol)
        if str(mp) not in self._mounted():
            mp.mkdir(parents=True, exist_ok=True)
            # nodelalloc: 할당량을 넘는 쓰기가 클라이언트에 오류로 돌아간다 (S1, 결정 6)
            self._run(["mount", "-t", "ext4", "-o", "nodelalloc", vol.device, str(mp)])
        return mp
