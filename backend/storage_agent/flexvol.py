"""볼륨 관리자: ONTAP FlexVol을 dm-thin thin LV + ext4로 재현한다 (ADR D-11·D-12, 볼륨 설계 결정 5~10, 17, 18,
스냅샷 설계 결정 2·5~8·13·14).

ONTAP과의 대응:
- aggregate = 씬 풀 `anf/aggr0`. 스토리지 루트의 희소 파일 → 루프 장치 → VG `anf`
- FlexVol = thin LV `vol_<uuid 32자리>` + ext4. junction path, uuid, IP, 프로토콜은 LVM 태그에 둔다 (agent에는 DB가 없다)
- Snapshot copy = 읽기 전용 thin 스냅샷 LV `snap_<uuid 32자리>`. 이름, 볼륨, 만든 시각도 LVM 태그에 둔다.
  WAFL처럼 블록을 공유하고 바뀐 블록만 새로 쓴다(dm-thin). 공간은 볼륨 할당량이 아니라 씬 풀에서 나간다 (R-09)
- SVM 네임스페이스 = `<root>/ns`. 볼륨은 `ns/<token>`에, 스냅샷은 `ns/<token>/.snapshot/<이름>`에 마운트되고,
  그 볼륨의 NFS 인스턴스가 `/<token>`과 스냅샷마다 `/<token>/.snapshot/<이름>`을 export한다
- data LIF = 볼륨 인스턴스의 IP. agent가 VOLUME_IPS에서 골라 태그로 남긴다 (결정 18)

모든 작업은 단계마다 실제 상태를 보고 이미 된 것은 건너뛴다.
그래서 어느 단계에서 멈춰도 같은 요청을 다시 하면 이어서 끝난다 (결정 10).
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from storage_agent.nfs_instance import VOLUME_IPS, NfsInstances
from storage_agent.runner import CommandError

VG = "anf"
POOL = "aggr0"
DEFAULT_ROOT = Path("/var/lib/anf-clone")
SNAPSHOT_DIR = ".snapshot"
# 인스턴스를 지운 뒤에도 knfsd가 잠시 파일시스템을 잡고 있을 수 있다. 0.5초 간격으로 60초까지 다시 시도한다
UMOUNT_ATTEMPTS = 120
UMOUNT_RETRY_SECONDS = 0.5


class VolumeError(Exception):
    """요청이 현재 상태와 맞지 않는다 (같은 uuid의 다른 설정, 경로·이름 중복, aggregate 공간 부족, IP 소진)."""


@dataclass(frozen=True)
class _Restore:
    """끝나지 않은 되돌리기: 볼륨 LV의 `anf_rv_req`·`anf_rv_snap` 태그 (되돌리기 결정 4).
    고른 스냅샷의 쓰기 가능 스냅샷이 새 볼륨 LV `vol_<uuid>_new`이고, 볼륨 태그·진행 표시에 `anf_rv_new`를 더 갖는다.
    new_lv가 None이면 새 LV를 만들기 전이고, 볼륨 LV와 같으면 옛 LV를 지운 뒤다."""

    request: str  # 멱등 키 (anf-api 작업 ID)
    snapshot: str
    new_lv: str | None = None

    def tags(self) -> list[str]:
        return [f"anf_rv_req={self.request}", f"anf_rv_snap={self.snapshot}"]


@dataclass(frozen=True)
class _Volume:
    uuid: str
    token: str
    size: int
    lv: str
    ip: str
    protocol: str
    pending: _Restore | None = None  # 끝나지 않은 되돌리기
    restored: str | None = None  # 마지막으로 끝낸 되돌리기의 키 (`anf_rv_done`)

    @property
    def device(self) -> str:
        return f"/dev/{VG}/{self.lv}"

    def tags(self) -> list[str]:
        return [f"anf_path={self.token}", f"anf_uuid={self.uuid}", f"anf_ip={self.ip}", f"anf_proto={self.protocol}"]


@dataclass(frozen=True)
class _Snapshot:
    uuid: str
    name: str
    volume: str  # 볼륨 uuid
    lv: str
    create_time: str  # UTC ISO 8601
    thin_id: int = 0  # dm-thin 장치 id. 남은 것 중 최댓값 + 1이라 한 볼륨의 스냅샷끼리는 만든 순서다 (S5 L3)

    @property
    def device(self) -> str:
        return f"/dev/{VG}/{self.lv}"

    def record(self) -> dict:
        """ONTAP 스냅샷 레코드의 부분집합 (스냅샷 설계 §6.1)."""
        return {"uuid": self.uuid, "name": self.name, "create_time": self.create_time, "volume": {"uuid": self.volume}}


def lv_name(uuid: str) -> str:
    return "vol_" + uuid.replace("-", "")


def snapshot_lv_name(uuid: str) -> str:
    return "snap_" + uuid.replace("-", "")


def _tag_args(flag: str, tags: list[str]) -> list[str]:
    return [arg for tag in tags for arg in (flag, tag)]


class FlexVolManager:
    def __init__(
        self,
        runner,
        root: Path = DEFAULT_ROOT,
        aggregate_size: int = 1 << 40,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self._run = runner.run
        self._sleep = sleep
        self._clock = clock
        self._ns = Path(root) / "ns"
        self._image = Path(root) / "aggr0.img"
        self._aggregate_size = aggregate_size
        self.instances = NfsInstances(runner, self._ns, Path(root) / "exports", sleep)

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
        self._run(["vgchange", "-ay", VG])  # 스냅샷 LV도 활성화된다 (activation skip 끔, 결정 5)

    def recover(self) -> None:
        """agent 시작 때: aggregate를 붙이고, ns를 공유 마운트로 만들고, 파일시스템이 있는 볼륨과 그 스냅샷을
        마운트해 인스턴스를 띄운다. ns 바인드는 볼륨 마운트보다 먼저다. 나중에 바인드하면 그 아래의 기존 마운트를 가린다.
        인스턴스는 모두 띄운 뒤에 준비를 기다린다. 유예 기간을 기다리는 인스턴스가 여럿이어도 한 번만 기다리게 된다 (결정 14).
        끝나지 않은 되돌리기는 인스턴스를 띄우기 전에 끝낸다. 인스턴스가 멈춰 있으니 입력 차단은 건너뛴다 (되돌리기 결정 4)."""
        self.ensure_aggregate()
        self.instances.ensure_shared_ns()
        for vol in self._report()[1]:
            if vol.pending is not None:
                self._resume_restore(vol)
        _, volumes, snapshots = self._report()
        started = []
        for vol in volumes:
            if self._filesystem(vol) != "ext4":
                continue
            self._ensure_mounted(vol)
            self._ensure_snapshot_dir(vol)
            mine = [s for s in snapshots if s.volume == vol.uuid]
            for snap in mine:
                self._ensure_snapshot_mounted(vol, snap)
            self._write_exports(vol, mine)
            self.instances.start(vol.uuid, vol.token, vol.ip, vol.protocol)
            started.append(vol.uuid)
        for uuid in started:
            self.instances.wait_ready(uuid)

    # --- 볼륨 ---

    def create(self, uuid: str, junction_path: str, size: int, unix_permissions: int, protocol: str) -> None:
        """(1) LV → (2) 파일시스템 → (3) 마운트 → (4) 루트 초기화 → (5) `.snapshot` → (6) export 파일 → (7) 인스턴스.
        입력은 agent_app이 검사했다. 끝나지 않은 되돌리기가 있으면 그것부터 끝낸다 (되돌리기 결정 2·4)."""
        vol = self._ensure_lv(uuid, junction_path[1:], size, protocol)
        if vol.pending is not None:
            vol = self._resume_restore(vol)
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
        self._ensure_snapshot_dir(vol)
        self._write_exports(vol, [s for s in self._report()[2] if s.volume == uuid])
        self.instances.ensure(uuid, vol.token, vol.ip, vol.protocol)

    def delete(self, uuid: str) -> None:
        """인스턴스 제거 → 스냅샷(언마운트, LV) → 볼륨 언마운트 → 마운트 지점 → export 파일 → 볼륨 LV. 없는 볼륨은 성공이다.
        인스턴스의 knfsd가 파일시스템을 잡고 있으므로 인스턴스가 먼저다. 스냅샷 마운트는 볼륨 마운트 아래에 있으므로
        스냅샷이 볼륨보다 먼저다. ANF처럼 볼륨을 지우면 스냅샷도 지워진다 (스냅샷 결정 2·13)."""
        _, volumes, snapshots = self._report()
        vol = next((v for v in volumes if v.uuid == uuid), None)
        if vol is None:
            return
        self.instances.remove(uuid)
        mounted = self._mounted()
        for snap in snapshots:
            if snap.volume == uuid:
                smp = self._snapshot_mountpoint(vol, snap)
                if str(smp) in mounted:
                    self._umount(smp)
                self._run(["lvremove", "-y", f"{VG}/{snap.lv}"])
        mp = self._mountpoint(vol)
        if str(mp) in mounted:
            self._umount(mp)
        if mp.is_dir():
            mp.rmdir()
        self.instances.remove_exports(uuid)
        self._run(["lvremove", "-y", f"{VG}/{vol.lv}"])
        if vol.pending is not None and vol.pending.new_lv not in (None, vol.lv):  # 되돌리다 멈춘 새 볼륨 LV
            self._run(["lvremove", "-y", f"{VG}/{vol.pending.new_lv}"])

    def records(self, name: str | None = None) -> list[dict]:
        mounted = self._mounted()
        return [self._record(v, mounted) for v in self._report()[1] if name is None or v.lv == name]

    def record(self, uuid: str) -> dict | None:
        return next((r for r in self.records() if r["uuid"] == uuid), None)

    # --- 스냅샷 ---

    def create_snapshot(self, volume_uuid: str, uuid: str, name: str) -> None:
        """(1) 볼륨·이름 확인 → (2) 스냅샷 LV → (3) `.snapshot` → (4) 마운트 지점·마운트 → (5) export 파일.
        uuid는 anf-api가 정한 멱등 키다. 같은 uuid·이름이면 이어서 끝내고, 이름이 다른 스냅샷에 쓰였으면 실패한다 (결정 9)."""
        _, volumes, snapshots = self._report()
        vol = next((v for v in volumes if v.uuid == volume_uuid), None)
        if vol is None:
            raise VolumeError(f"volume {volume_uuid} not found")
        self._refuse_during_restore(vol)
        if str(self._mountpoint(vol)) not in self._mounted():
            raise VolumeError(f"volume {volume_uuid} is offline")
        mine = [s for s in snapshots if s.volume == volume_uuid]
        snap = next((s for s in mine if s.uuid == uuid), None)
        if snap is not None and snap.name != name:
            raise VolumeError(f"snapshot {uuid} already exists with the name {snap.name}")
        if any(s.name == name and s.uuid != uuid for s in mine):
            raise VolumeError("A snapshot with the specified name already exists.")  # ONTAP 525059
        if snap is None:
            snap = _Snapshot(uuid, name, volume_uuid, snapshot_lv_name(uuid),
                             self._clock().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
            # -kn: activation skip을 꺼서 vgchange -ay가 함께 활성화한다. -p r: 블록 장치부터 읽기 전용이다 (결정 5)
            self._run([
                "lvcreate", "-s", "-kn", "-p", "r", "-n", snap.lv,
                "--addtag", f"anf_snap_uuid={uuid}", "--addtag", f"anf_snap_name={name}",
                "--addtag", f"anf_snap_vol={volume_uuid}", "--addtag", f"anf_snap_time={snap.create_time}",
                f"{VG}/{vol.lv}",
            ])
            mine.append(snap)
        self._ensure_snapshot_dir(vol)
        self._ensure_snapshot_mounted(vol, snap)
        self._write_exports(vol, mine)

    def delete_snapshot(self, volume_uuid: str, uuid: str) -> None:
        """export 줄 제거 → 인스턴스 안 잠금 해제 → 언마운트 → 마운트 지점 → LV (결정 13). 없는 스냅샷은 성공이다.
        클라이언트가 스냅샷 안에서 파일을 열고 있어도 export를 빼고 knfsd 상태를 풀면 내릴 수 있다 (S4 E4)."""
        _, volumes, snapshots = self._report()
        snap = next((s for s in snapshots if s.uuid == uuid and s.volume == volume_uuid), None)
        if snap is None:
            return
        vol = next(v for v in volumes if v.uuid == volume_uuid)
        self._refuse_during_restore(vol)
        self._remove_snapshot(vol, snap, [s for s in snapshots if s.volume == volume_uuid and s.uuid != uuid])

    def snapshot_records(self, volume_uuid: str, name: str | None = None) -> list[dict] | None:
        """볼륨의 스냅샷 레코드(이름순). 볼륨이 없으면 None."""
        _, volumes, snapshots = self._report()
        if not any(v.uuid == volume_uuid for v in volumes):
            return None
        mine = [s for s in snapshots if s.volume == volume_uuid and (name is None or s.name == name)]
        return [s.record() for s in sorted(mine, key=lambda s: s.name)]

    def snapshot_record(self, volume_uuid: str, uuid: str) -> dict | None:
        return next((r for r in self.snapshot_records(volume_uuid) or [] if r["uuid"] == uuid), None)

    # --- 되돌리기 (되돌리기 설계 결정 3·4·8~10, §6.2) ---

    def restore(self, volume_uuid: str, snapshot_uuid: str, request_uuid: str) -> None:
        """볼륨을 스냅샷 시점으로 되돌린다 (ONTAP `restore_to`). request_uuid는 anf-api 작업 ID인 멱등 키다.
        (1) 진행 표시 → (2) 더 새 스냅샷 삭제 → (3) 고른 스냅샷의 쓰기 가능 스냅샷 = 새 볼륨 LV → (4) 창: 입력 차단,
        언마운트, 새 LV와 스냅샷 마운트, export, 차단 풀기 → (5) 옛 볼륨 LV 삭제 → (6) 이름 넘겨받기 → (7) 끝난 표시.
        끝나지 않은 되돌리기가 있으면 그것부터 끝낸다."""
        vol = self._volume(volume_uuid)
        if vol.pending is not None:
            pending = vol.pending
            vol = self._resume_restore(vol)
            if pending.request == request_uuid:
                self.instances.ensure(vol.uuid, vol.token, vol.ip, vol.protocol)
                return
        if vol.restored == request_uuid:  # 이미 끝냈다. 그 뒤에 클라이언트가 쓴 것을 지우지 않는다
            return
        if str(self._mountpoint(vol)) not in self._mounted():
            raise VolumeError(f"volume {volume_uuid} is offline")
        snap = next((s for s in self._report()[2] if s.volume == volume_uuid and s.uuid == snapshot_uuid), None)
        if snap is None:
            raise VolumeError(f"snapshot {snapshot_uuid} not found")
        pending = _Restore(request_uuid, snap.uuid)
        self._run(["lvchange", *_tag_args("--addtag", pending.tags()), f"{VG}/{vol.lv}"])
        self._resume_restore(replace(vol, pending=pending))
        self.instances.ensure(vol.uuid, vol.token, vol.ip, vol.protocol)

    def _resume_restore(self, vol: _Volume) -> _Volume:
        """진행 표시의 되돌리기를 남은 단계부터 끝내고 끝난 볼륨을 돌려준다. 새 LV가 없으면 만들기부터, 옛 LV가 있으면
        창부터(새 LV가 이미 마운트돼 있어도 다시 올린다), 옛 LV가 없으면 이름 넘겨받기부터다 (결정 4)."""
        pending = vol.pending
        mine = [s for s in self._report()[2] if s.volume == vol.uuid]
        old = None
        if pending.new_lv != vol.lv:  # 옛 볼륨 LV가 아직 있다
            new_lv = pending.new_lv
            if new_lv is None:
                target = next(s for s in mine if s.uuid == pending.snapshot)
                for newer in [s for s in mine if s.thin_id > target.thin_id]:  # 결정 8
                    mine.remove(newer)
                    self._remove_snapshot(vol, newer, mine)
                # merge가 아니라 교체다: merge하면 다른 스냅샷이 원본 표시를 잃어 다음 되돌리기에서 merge할 수 없다.
                # 고른 스냅샷은 그대로 남는다 (결정 9). 볼륨 태그를 처음부터 가지므로 옛 LV를 지워도 볼륨을 잃지 않는다
                new_lv = lv_name(vol.uuid) + "_new"
                self._run(["lvcreate", "-s", "-kn", "-p", "rw", "-n", new_lv,
                           *_tag_args("--addtag", vol.tags() + pending.tags() + ["anf_rv_new=1"]),
                           f"{VG}/{target.lv}"])
            self._block_and_unmount(vol)
            old, vol = vol, replace(vol, lv=new_lv)
        self._ensure_mounted(vol)
        self._ensure_snapshot_dir(vol)
        # 그 시점의 `.snapshot`에는 그 뒤에 지운 스냅샷의 빈 마운트 지점이 있을 수 있다. 남은 스냅샷에 맞춘다 (결정 10)
        names = {s.name for s in mine}
        stray = [p for p in (self._mountpoint(vol) / SNAPSHOT_DIR).iterdir() if p.name not in names]
        if stray:
            self._change_snapshot_dir(vol, lambda: [p.rmdir() for p in stray])
        for snap in mine:
            self._ensure_snapshot_mounted(vol, snap)
        self._write_exports(vol, mine)
        self.instances.unblock(vol.uuid)
        # 창 밖: 클라이언트는 이미 새 LV를 쓴다. 옛 LV의 끝난 표시는 옛 LV와 함께 사라진다
        if old is not None:
            self._run(["lvremove", "-y", f"{VG}/{old.lv}"])
        if vol.lv != lv_name(vol.uuid):
            self._run(["lvrename", f"{VG}/{vol.lv}", lv_name(vol.uuid)])  # 마운트된 채 바꿀 수 있다
        self._run(["lvchange", *_tag_args("--deltag", pending.tags() + ["anf_rv_new=1"]),
                   "--addtag", f"anf_rv_done={pending.request}", f"{VG}/{lv_name(vol.uuid)}"])
        return replace(vol, lv=lv_name(vol.uuid), pending=None, restored=pending.request)

    def _block_and_unmount(self, vol: _Volume) -> None:
        """창을 연다: 인스턴스 입력을 막고 export 캐시를 비운 뒤 스냅샷 → 볼륨 순서로 내린다. 클라이언트는 hard 마운트
        재전송으로 기다린다 (S5). 내리기 전에 knfsd가 잡은 잠금과 NFSv4 상태를 푼다."""
        self.instances.block(vol.uuid)
        mp = self._mountpoint(vol)
        mounted = self._mounted()
        for smp in sorted((m for m in mounted if mp in Path(m).parents), reverse=True):
            self.instances.unlock(vol.uuid, Path(smp).relative_to(self._ns).as_posix())
            self._umount(Path(smp))
        if str(mp) in mounted:
            self.instances.unlock(vol.uuid, vol.token)
            self._umount(mp)

    # --- 내부 ---

    def _volume(self, uuid: str) -> _Volume:
        vol = next((v for v in self._report()[1] if v.uuid == uuid), None)
        if vol is None:
            raise VolumeError(f"volume {uuid} not found")
        return vol

    @staticmethod
    def _refuse_during_restore(vol: _Volume) -> None:
        """끝나지 않은 되돌리기가 있으면 스냅샷을 바꾸지 않는다. 고른 스냅샷을 지우면 이어서 끝낼 때 merge가 끝난 것으로
        잘못 보고, 새 스냅샷은 merge 전에 지워야 할 더 새 스냅샷이 된다."""
        if vol.pending is not None:
            raise VolumeError(f"volume {vol.uuid} has an unfinished restore to snapshot {vol.pending.snapshot}; "
                              "send the restore again or POST the volume to finish it")

    def _remove_snapshot(self, vol: _Volume, snap: _Snapshot, others: list[_Snapshot]) -> None:
        """export 줄 제거 → 인스턴스 안 잠금 해제 → 언마운트 → 마운트 지점 → LV (스냅샷 결정 13).
        클라이언트가 스냅샷 안에서 파일을 열고 있어도 export를 빼고 knfsd 상태를 풀면 내릴 수 있다 (S4 E4)."""
        self._write_exports(vol, others)
        smp = self._snapshot_mountpoint(vol, snap)
        if str(smp) in self._mounted():
            self.instances.unlock(vol.uuid, f"{vol.token}/{SNAPSHOT_DIR}/{snap.name}")
            self._umount(smp)
        if smp.is_dir():
            self._change_snapshot_dir(vol, smp.rmdir)
        self._run(["lvremove", "-y", f"{VG}/{snap.lv}"])

    def _ensure_lv(self, uuid: str, token: str, size: int, protocol: str) -> _Volume:
        pool_size, volumes, _ = self._report()
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
        free = pool_size - sum(v.size for v in volumes)  # 스냅샷은 할당량이 없다 (thin 스냅샷)
        if size > free:
            raise VolumeError(f"aggregate {POOL} has {free} bytes left; the volume needs {size}")
        used = {v.ip for v in volumes}
        ip = next((ip for ip in VOLUME_IPS if ip not in used), None)
        if ip is None:
            raise VolumeError(f"all {len(VOLUME_IPS)} volume IPs are in use")
        vol = _Volume(uuid, token, size, lv_name(uuid), ip, protocol)
        self._run([
            "lvcreate", "--type", "thin", "-V", f"{size}b", "--thinpool", POOL, "-n", vol.lv,
            *_tag_args("--addtag", vol.tags()), VG,
        ])
        return vol

    def _report(self) -> tuple[int, list[_Volume], list[_Snapshot]]:
        """씬 풀 크기와 태그가 붙은 볼륨·스냅샷 목록. 스냅샷 LV는 원본의 태그를 물려받지 않는다."""
        out = self._run([
            "lvs", "--reportformat", "json", "--units", "b", "--nosuffix", "-o", "lv_name,lv_size,lv_tags,thin_id",
            VG,
        ]).stdout
        pool_size, found, snapshots = 0, [], []
        for row in json.loads(out)["report"][0]["lv"]:
            tags = dict(t.split("=", 1) for t in row["lv_tags"].split(",") if "=" in t)
            if row["lv_name"] == POOL:
                pool_size = int(row["lv_size"])
            elif "anf_uuid" in tags:
                pending = None
                if "anf_rv_req" in tags:
                    pending = _Restore(tags["anf_rv_req"], tags["anf_rv_snap"],
                                       row["lv_name"] if "anf_rv_new" in tags else None)
                found.append(_Volume(tags["anf_uuid"], tags["anf_path"], int(row["lv_size"]), row["lv_name"],
                                     tags["anf_ip"], tags["anf_proto"], pending, tags.get("anf_rv_done")))
            elif "anf_snap_uuid" in tags:
                snapshots.append(_Snapshot(tags["anf_snap_uuid"], tags["anf_snap_name"], tags["anf_snap_vol"],
                                           row["lv_name"], tags["anf_snap_time"], int(row["thin_id"])))
        # 되돌리는 동안에는 한 볼륨에 LV가 둘이다: 옛 볼륨 LV와 새 LV(anf_rv_new). 옛 LV가 있으면 그것이 볼륨이다
        volumes = []
        for vol in found:
            other = next((v.lv for v in found if v.uuid == vol.uuid and v is not vol), None)
            if vol.pending is not None and vol.pending.new_lv is not None:
                if other is None:
                    volumes.append(vol)
            elif other is not None:
                volumes.append(replace(vol, pending=replace(vol.pending, new_lv=other)))
            else:
                volumes.append(vol)
        return pool_size, volumes, snapshots

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

    def _snapshot_mountpoint(self, vol: _Volume, snap: _Snapshot) -> Path:
        return self._mountpoint(vol) / SNAPSHOT_DIR / snap.name

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

    def _ensure_snapshot_dir(self, vol: _Volume) -> None:
        """볼륨 루트의 `.snapshot`은 스냅샷이 없어도 있고 immutable이다. 그래야 root 클라이언트도 그 안에 파일을
        만들거나 `.snapshot`을 옮기지 못한다 (S4 E3). NFS로는 chattr를 할 수 없다."""
        snapdir = self._mountpoint(vol) / SNAPSHOT_DIR
        snapdir.mkdir(exist_ok=True)
        if "i" not in self._run(["lsattr", "-d", str(snapdir)]).stdout.split()[0]:
            self._run(["chattr", "+i", str(snapdir)])

    def _change_snapshot_dir(self, vol: _Volume, change: Callable[[], None]) -> None:
        """agent만 `.snapshot`의 immutable을 잠깐 풀어 마운트 지점을 넣고 뺀다. 실패해도 다시 잠근다."""
        snapdir = str(self._mountpoint(vol) / SNAPSHOT_DIR)
        self._run(["chattr", "-i", snapdir])
        try:
            change()
        finally:
            self._run(["chattr", "+i", snapdir])

    def _ensure_snapshot_mounted(self, vol: _Volume, snap: _Snapshot) -> None:
        smp = self._snapshot_mountpoint(vol, snap)
        if str(smp) in self._mounted():
            return
        if not smp.is_dir():
            self._change_snapshot_dir(vol, smp.mkdir)
        # noload: 읽기 전용 장치라 저널을 재생하지 않는다 (S1)
        self._run(["mount", "-t", "ext4", "-o", "ro,noload", snap.device, str(smp)])

    def _write_exports(self, vol: _Volume, snapshots: list[_Snapshot]) -> None:
        self.instances.write_exports(vol.uuid, vol.token, [(s.name, s.uuid) for s in snapshots])
