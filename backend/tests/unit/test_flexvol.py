"""storage agent의 볼륨 관리자: 명령 순서, 멱등, 단계별 복구, IP 태그 (볼륨 설계 결정 5~10, 17, 18, §6.2),
스냅샷 (스냅샷 설계 결정 2·5~8·13·14, §6.2).

가짜 호스트가 LVM·마운트·볼륨 인스턴스 상태를 들고 명령에 따라 바꾼다. 실행기와 인스턴스 관리자를 함께
흉내 내서, 컨테이너 시작·제거와 export 파일 쓰기가 LVM·마운트 명령과 같은 기록에 순서대로 남는다. 출력 형식은
WSL Ubuntu 24.04(LVM 2.03.16)에서 확인한 것을 따른다. 실제 동작은 통합 테스트가 확인한다.
"""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from storage_agent.flexvol import UMOUNT_ATTEMPTS, FlexVolManager, VolumeError
from storage_agent.nfs_instance import VOLUME_IPS
from storage_agent.runner import CommandError, Result

GIB = 1 << 30
U1 = "11111111-2222-3333-4444-555555555555"
U2 = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
U3 = "99999999-8888-7777-6666-555555555555"
LV1 = "vol_11111111222233334444555555555555"
S1 = "5a000000-0000-4000-8000-000000000001"
S2 = "5a000000-0000-4000-8000-000000000002"
SLV1 = "snap_5a000000000040008000000000000001"
SLV2 = "snap_5a000000000040008000000000000002"
NOW = datetime(2026, 11, 8, 23, 7, 12, 345678, tzinfo=timezone.utc)
QUERIES = {"lvs", "vgs", "blkid", "findmnt", "lsattr"}


class FakeHost:
    """가짜 호스트. 커널(LVM·마운트) 명령과 볼륨 인스턴스(컨테이너)를 함께 흉내 낸다."""

    POOL_SIZE = 10 * GIB

    def __init__(self):
        self.calls: list[list[str]] = []
        self.ns: Path | None = None  # make_manager가 정한다
        self.loop = None  # 이미지가 붙은 루프 장치
        self.vg = False  # 이미지 안에 VG `anf`가 있음
        self.pool = False
        # LV 이름 → {"size", "tags", "fs", "tree"}. tree는 파일시스템 안의 디렉터리(마운트 지점 기준 상대 경로)다.
        # 마운트하면 마운트 지점 아래에 만들고, 내리면 기억한 뒤 지운다
        self.lvs: dict[str, dict] = {}
        self.mounts: dict[str, str] = {}  # 마운트 지점 → 장치 (마운트한 순서)
        self.immutable: set[str] = set()  # chattr +i 된 경로
        self.shared_ns = False
        self.instances: dict[str, tuple] = {}  # 돌고 있는 인스턴스: uuid → (token, ip, protocol)
        self.exports: dict[str, tuple] = {}  # export 파일: 볼륨 uuid → (token, 스냅샷 이름들)
        self.held: set[str] = set()  # 클라이언트가 열고 있는 ns 기준 경로. 인스턴스 안 unlock으로 풀린다
        self.fail: dict[str, str] = {}  # 프로그램(또는 "instance") → stderr (다음 한 번 실패)
        self.busy = 0  # 인스턴스가 없어도 umount가 busy인 남은 횟수

    # --- 실행기 ---

    def run(self, argv, check=True, input=None):
        self.calls.append(argv)
        if argv[0] in self.fail:
            result = Result(5, "", self.fail.pop(argv[0]))
        else:
            result = getattr(self, "_" + argv[0].replace(".", "_"))(argv[1:])
        if check and result.returncode != 0:
            raise CommandError(argv, result)
        return result

    # --- 인스턴스 관리자 ---

    def ensure_shared_ns(self):
        if not self.shared_ns:
            self.calls.append(["shared-ns"])
            self.shared_ns = True

    def ensure(self, uuid, token, ip, protocol):
        self.start(uuid, token, ip, protocol)
        self.wait_ready(uuid)

    def start(self, uuid, token, ip, protocol):
        if uuid in self.instances:
            return
        if "instance" in self.fail:
            raise CommandError(["docker", "run"], Result(125, "", self.fail.pop("instance")))
        # 인스턴스는 호스트 마운트와 export 파일 뒤에 시작한다 (볼륨 결정 17, 스냅샷 결정 7)
        assert token in {Path(t).name for t in self.mounts}, "instance started before the host mount"
        assert uuid in self.exports, "instance started before its exports file was written"
        self.calls.append(["instance-start", uuid])
        self.instances[uuid] = (token, ip, protocol)

    def wait_ready(self, uuid):
        self.calls.append(["instance-ready", uuid])

    def remove(self, uuid):
        if self.instances.pop(uuid, None) is not None:
            self.calls.append(["instance-remove", uuid])

    def write_exports(self, uuid, token, snapshots):
        names = sorted(name for name, _ in snapshots)
        self.calls.append(["exports", uuid, *names])
        self.exports[uuid] = (token, names)

    def remove_exports(self, uuid):
        self.calls.append(["exports-remove", uuid])
        self.exports.pop(uuid, None)

    def unlock(self, uuid, path):
        if uuid in self.instances:
            self.calls.append(["unlock", uuid, path])
            self.held.discard(path)

    # --- 흉내 ---

    def reboot(self):
        # WSL 재시작: 루프 장치, 마운트, 공유 마운트가 사라지고 인스턴스 컨테이너가 멈춘다. 이미지 파일은 남는다
        for target in reversed(list(self.mounts)):
            self._detach(target)
        self.loop = None
        self.shared_ns = False
        self.instances.clear()
        self.calls.clear()

    def _detach(self, target):
        root = Path(target)
        tree = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_dir())
        self.lvs[self.mounts.pop(target).removeprefix("/dev/anf/")]["tree"] = tree
        for child in root.iterdir():
            shutil.rmtree(child)

    def _exported_snapshot(self, target):
        """target이 돌고 있는 인스턴스의 export 파일에 있는 스냅샷 마운트인가."""
        path = Path(target)
        if path.parent.name != ".snapshot":
            return False
        token = path.parent.parent.name
        return any(uuid in self.instances and t == token and path.name in names
                   for uuid, (t, names) in self.exports.items())

    @staticmethod
    def ok(stdout=""):
        return Result(0, stdout, "")

    def _losetup(self, args):
        if args[0] == "-j":
            return self.ok(f"{self.loop}: [2080]:131 ({args[1]})\n" if self.loop else "")
        assert args[:2] == ["--find", "--show"]
        self.loop = "/dev/loop7"
        return self.ok("/dev/loop7\n")

    def _vgs(self, args):
        assert args == ["anf"]
        return self.ok() if self.vg and self.loop else Result(5, "", '  Volume group "anf" not found\n')

    def _vgcreate(self, args):
        assert args == ["anf", self.loop]
        self.vg = True
        return self.ok()

    def _vgchange(self, args):
        assert args == ["-ay", "anf"]
        return self.ok()

    def _lvs(self, args):
        if args == ["anf/aggr0"]:
            return self.ok() if self.pool else Result(5, "", "  Failed to find logical volume\n")
        assert args[-1] == "anf"
        rows = [{"lv_name": "aggr0", "lv_size": str(self.POOL_SIZE), "lv_tags": ""}] if self.pool else []
        rows += [
            {"lv_name": name, "lv_size": str(lv["size"]), "lv_tags": ",".join(sorted(lv["tags"]))}
            for name, lv in self.lvs.items()
        ]
        return self.ok(json.dumps({"report": [{"lv": rows}]}))

    def _lvcreate(self, args):
        if args[0] == "-s":  # thin 스냅샷: 원본의 파일시스템을 갖고, 원본의 태그는 물려받지 않는다 (WSL 확인)
            assert args[1:4] == ["-kn", "-p", "r"] and args[4] == "-n"
            origin = self.lvs[args[-1].removeprefix("anf/")]
            tags = [value for flag, value in zip(args[6:-1:2], args[7:-1:2]) if flag == "--addtag"]
            self.lvs[args[5]] = {"size": origin["size"], "tags": tags, "fs": origin["fs"], "tree": []}
            return self.ok()
        assert args[-1] == "anf"
        pairs = list(zip(args[:-1:2], args[1:-1:2]))
        opts = dict(pairs)
        if opts["--type"] == "thin-pool":
            self.pool = True
        else:
            assert opts["--type"] == "thin" and opts["--thinpool"] == "aggr0"
            tags = [value for flag, value in pairs if flag == "--addtag"]
            self.lvs[opts["-n"]] = {"size": int(opts["-V"].removesuffix("b")), "tags": tags, "fs": None, "tree": []}
        return self.ok()

    def _blkid(self, args):
        lv = self.lvs.get(args[-1].removeprefix("/dev/anf/"))
        return self.ok(lv["fs"] + "\n") if lv and lv["fs"] else Result(2, "", "")

    def _mkfs_ext4(self, args):
        lv = self.lvs[args[-1].removeprefix("/dev/anf/")]
        lv["fs"], lv["tree"] = "ext4", ["lost+found"]
        return self.ok()

    def _findmnt(self, args):
        return self.ok("".join(f"{target}\n" for target in self.mounts))

    def _mount(self, args):
        device, target = args[-2], args[-1]
        assert Path(target).is_dir()
        for rel in self.lvs[device.removeprefix("/dev/anf/")]["tree"]:
            (Path(target) / rel).mkdir()
        self.mounts[target] = device
        return self.ok()

    def _umount(self, args):
        target = args[0]
        # 볼륨 인스턴스의 knfsd가 export한 파일시스템, 클라이언트가 연 파일, 하위 마운트가 있으면 내릴 수 없다
        exported = Path(target).name in {token for token, _, _ in self.instances.values()}
        held = Path(target).relative_to(self.ns).as_posix() in self.held
        nested = any(t.startswith(target + "/") or t.startswith(target + "\\") for t in self.mounts)
        if exported or held or nested or self._exported_snapshot(target) or self.busy:
            self.busy = max(self.busy - 1, 0)
            return Result(32, "", f"umount: {target}: target is busy.\n")
        self._detach(target)
        return self.ok()

    def _chmod(self, args):
        return self.ok()

    def _chattr(self, args):
        flag, path = args
        assert flag in ("+i", "-i")
        (self.immutable.add if flag == "+i" else self.immutable.discard)(path)
        return self.ok()

    def _lsattr(self, args):
        assert args[0] == "-d"
        flags = "----i---------e-------" if args[1] in self.immutable else "--------------e-------"
        return self.ok(f"{flags} {args[1]}\n")

    def _lvremove(self, args):
        assert args[0] == "-y"
        del self.lvs[args[1].removeprefix("anf/")]
        return self.ok()


def changes(host):
    """상태를 바꾸는 명령만 (조회 명령 제외)."""
    return [c for c in host.calls if c[0] not in QUERIES and c[:2] != ["losetup", "-j"]]


def make_manager(host, tmp_path):
    m = FlexVolManager(host, root=tmp_path / "root", aggregate_size=1 << 20, sleep=lambda s: None, clock=lambda: NOW)
    m.instances = host  # 컨테이너 대신 가짜 호스트가 볼륨 인스턴스를 흉내 낸다
    host.ns = tmp_path / "root" / "ns"
    return m


def mountpoint(tmp_path, token):
    return str(tmp_path / "root" / "ns" / token)


def snapdir(tmp_path, token="vol1"):
    return str(Path(mountpoint(tmp_path, token)) / ".snapshot")


def snapmount(tmp_path, name, token="vol1"):
    return str(Path(snapdir(tmp_path, token)) / name)


@pytest.fixture
def host():
    return FakeHost()


@pytest.fixture
def mgr(host, tmp_path):
    m = make_manager(host, tmp_path)
    m.ensure_aggregate()
    host.calls.clear()
    return m


def create(mgr, uuid=U1, path="/vol1", size=GIB, protocol="nfs3"):
    mgr.create(uuid, path, size, 770, protocol)


# --- aggregate ---


def test_aggregate_from_scratch(host, tmp_path):
    make_manager(host, tmp_path).ensure_aggregate()
    img = tmp_path / "root" / "aggr0.img"
    assert img.stat().st_size == 1 << 20
    assert (tmp_path / "root" / "ns").is_dir()
    assert changes(host) == [
        ["losetup", "--find", "--show", str(img)],
        ["vgcreate", "anf", "/dev/loop7"],
        ["lvcreate", "--type", "thin-pool", "-l", "100%FREE", "-n", "aggr0", "anf"],
        ["vgchange", "-ay", "anf"],
    ]


def test_aggregate_already_ready_only_activates(host, mgr):
    mgr.ensure_aggregate()
    assert changes(host) == [["vgchange", "-ay", "anf"]]


def test_aggregate_after_reboot_reattaches_without_recreating(host, mgr, tmp_path):
    img = tmp_path / "root" / "aggr0.img"
    img.write_bytes(b"x")  # 이미지 내용을 다시 만들지 않는지 본다
    host.reboot()
    mgr.ensure_aggregate()
    assert img.read_bytes() == b"x"
    assert changes(host) == [["losetup", "--find", "--show", str(img)], ["vgchange", "-ay", "anf"]]


# --- 생성 ---


def test_create_new_volume(host, mgr, tmp_path):
    create(mgr, protocol="nfs4.1")
    mp = mountpoint(tmp_path, "vol1")
    device = f"/dev/anf/{LV1}"
    assert changes(host) == [
        ["lvcreate", "--type", "thin", "-V", f"{GIB}b", "--thinpool", "aggr0", "-n", LV1,
         "--addtag", "anf_path=vol1", "--addtag", f"anf_uuid={U1}",
         "--addtag", "anf_ip=172.30.0.129", "--addtag", "anf_proto=nfs4.1", "anf"],
        ["mkfs.ext4", "-q", "-m", "0", "-U", U1, device],
        ["mount", "-t", "ext4", "-o", "nodelalloc", device, mp],
        ["chmod", "0770", mp],
        # 스냅샷이 없어도 .snapshot이 있고 클라이언트가 바꿀 수 없다 (스냅샷 결정 8)
        ["chattr", "+i", snapdir(tmp_path)],
        ["exports", U1],
        ["instance-start", U1],
        ["instance-ready", U1],
    ]
    assert sorted(p.name for p in Path(mp).iterdir()) == [".snapshot"]  # lost+found는 지웠다
    assert host.instances[U1] == ("vol1", "172.30.0.129", "nfs4.1")
    assert mgr.record(U1) == {
        "uuid": U1, "name": LV1, "size": GIB, "nas": {"path": "/vol1", "protocols": ["nfs4.1"]},
        "state": "online", "data_lif": {"ip": {"address": "172.30.0.129"}},
    }


def test_create_again_only_reapplies_exports(host, mgr):
    # 이미 된 단계는 건너뛴다. 클라이언트가 바꿨을 수 있는 루트 권한도 다시 바꾸지 않는다.
    # export 파일은 적용이 실패했을 수 있으므로 늘 다시 쓴다. 인스턴스는 준비만 확인한다
    create(mgr)
    host.calls.clear()
    create(mgr)
    assert changes(host) == [["exports", U1], ["instance-ready", U1]]
    assert list(host.lvs) == [LV1]


def test_create_resumes_after_mkfs_failure(host, mgr):
    host.fail["mkfs.ext4"] = "mkfs.ext4: Device or resource busy"
    with pytest.raises(CommandError):
        create(mgr)
    host.calls.clear()
    create(mgr)
    assert [c[0] for c in changes(host)] == [
        "mkfs.ext4", "mount", "chmod", "chattr", "exports", "instance-start", "instance-ready"]
    assert list(host.lvs) == [LV1]
    assert mgr.record(U1)["data_lif"] == {"ip": {"address": "172.30.0.129"}}  # 다시 해도 같은 IP


def test_create_finishes_initialization_after_failure(host, mgr, tmp_path):
    lost_found = Path(mountpoint(tmp_path, "vol1")) / "lost+found"
    host.fail["chmod"] = "chmod: Input/output error"
    with pytest.raises(CommandError):
        create(mgr)
    assert lost_found.is_dir()
    host.calls.clear()
    create(mgr)
    assert [c[0] for c in changes(host)] == ["chmod", "chattr", "exports", "instance-start", "instance-ready"]
    assert not lost_found.exists()


def test_create_makes_snapshot_dir_immutable_after_failure(host, mgr, tmp_path):
    host.fail["chattr"] = "chattr: Operation not supported"
    with pytest.raises(CommandError):
        create(mgr)
    host.calls.clear()
    create(mgr)
    assert changes(host)[0] == ["chattr", "+i", snapdir(tmp_path)]
    assert snapdir(tmp_path) in host.immutable


def test_create_resumes_after_instance_failure(host, mgr):
    host.fail["instance"] = "docker: Error response from daemon"
    with pytest.raises(CommandError):
        create(mgr)
    host.calls.clear()
    create(mgr)
    assert changes(host) == [["exports", U1], ["instance-start", U1], ["instance-ready", U1]]


@pytest.mark.parametrize("path, size, protocol", [
    ("/other", GIB, "nfs3"), ("/vol1", 2 * GIB, "nfs3"), ("/vol1", GIB, "nfs4.1"),
])
def test_same_uuid_with_different_settings_fails(host, mgr, path, size, protocol):
    create(mgr)
    host.calls.clear()
    with pytest.raises(VolumeError):
        create(mgr, U1, path, size, protocol)
    assert changes(host) == []


@pytest.mark.parametrize("path", ["/vol1", "/VOL1"])
def test_path_used_by_another_volume_fails(host, mgr, path):
    create(mgr)
    host.calls.clear()
    with pytest.raises(VolumeError):
        create(mgr, U2, path)
    assert changes(host) == []


def test_volumes_cannot_exceed_aggregate(host, mgr):
    # 과할당하지 않는다: 할당량 합이 aggregate 크기를 넘으면 실패
    create(mgr, size=6 * GIB)
    host.calls.clear()
    with pytest.raises(VolumeError):
        create(mgr, U2, "/vol2", 5 * GIB)
    assert changes(host) == []
    create(mgr, U2, "/vol2", 4 * GIB)


def test_volume_ips_are_allocated_lowest_first_and_reused(host, mgr):
    create(mgr)
    create(mgr, U2, "/vol2")
    assert mgr.record(U2)["data_lif"] == {"ip": {"address": "172.30.0.130"}}
    mgr.delete(U1)
    create(mgr, U3, "/vol3")
    assert mgr.record(U3)["data_lif"] == {"ip": {"address": "172.30.0.129"}}


def test_no_free_volume_ip_fails(host, mgr):
    for i, ip in enumerate(VOLUME_IPS):
        host.lvs[f"vol_x{i}"] = {"size": 1, "fs": None, "tree": [],
                                 "tags": [f"anf_path=t{i}", f"anf_uuid=u{i}", f"anf_ip={ip}", "anf_proto=nfs3"]}
    with pytest.raises(VolumeError):
        create(mgr)
    assert changes(host) == []


def test_incomplete_volume_has_no_instance(host, mgr):
    host.fail["mkfs.ext4"] = "boom"
    with pytest.raises(CommandError):
        create(mgr)
    assert host.instances == {}


# --- 삭제 ---


def test_delete_volume(host, mgr, tmp_path):
    create(mgr)
    create(mgr, U2, "/vol2")
    host.calls.clear()
    mgr.delete(U1)
    mp = mountpoint(tmp_path, "vol1")
    # 인스턴스를 먼저 내려야 knfsd가 파일시스템을 놓아 언마운트된다
    assert changes(host) == [
        ["instance-remove", U1], ["umount", mp], ["exports-remove", U1], ["lvremove", "-y", f"anf/{LV1}"]]
    assert not Path(mp).exists()
    assert mgr.record(U1) is None
    assert list(host.instances) == [U2]
    assert list(host.exports) == [U2]


def test_delete_waits_until_the_file_system_is_released(host, mgr):
    # 인스턴스를 지운 뒤에도 잠시 busy일 수 있다 (S2: 1분 안쪽, 볼륨 세션: 25초)
    create(mgr)
    host.calls.clear()
    host.busy = 3
    mgr.delete(U1)
    assert [c[0] for c in changes(host)] == [
        "instance-remove", "umount", "umount", "umount", "umount", "exports-remove", "lvremove"]


def test_delete_gives_up_when_still_busy(host, mgr):
    create(mgr)
    host.calls.clear()
    host.busy = 10**6
    with pytest.raises(CommandError):
        mgr.delete(U1)
    assert [c[0] for c in changes(host)].count("umount") == UMOUNT_ATTEMPTS
    assert LV1 in host.lvs  # 다시 DELETE하면 이어서 지운다


def test_delete_missing_volume_succeeds(host, mgr):
    mgr.delete(U1)
    assert changes(host) == []


def test_delete_resumes_after_failure(host, mgr):
    create(mgr)
    host.fail["lvremove"] = "lvremove: device busy"
    with pytest.raises(CommandError):
        mgr.delete(U1)
    host.calls.clear()
    mgr.delete(U1)
    assert changes(host) == [["exports-remove", U1], ["lvremove", "-y", f"anf/{LV1}"]]
    assert host.lvs == {}


def test_delete_volume_deletes_its_snapshots_first(host, mgr, tmp_path):
    # 볼륨 DELETE는 스냅샷도 지운다 (결정 2). 스냅샷 마운트가 볼륨 아래에 있으므로 스냅샷이 먼저다 (결정 13)
    create(mgr)
    create(mgr, U2, "/vol2")
    mgr.create_snapshot(U1, S1, "s1")
    mgr.create_snapshot(U1, S2, "s2")
    mgr.create_snapshot(U2, "5a000000-0000-4000-8000-000000000003", "s1")
    host.calls.clear()
    mgr.delete(U1)
    assert changes(host) == [
        ["instance-remove", U1],
        ["umount", snapmount(tmp_path, "s1")], ["lvremove", "-y", f"anf/{SLV1}"],
        ["umount", snapmount(tmp_path, "s2")], ["lvremove", "-y", f"anf/{SLV2}"],
        ["umount", mountpoint(tmp_path, "vol1")], ["exports-remove", U1], ["lvremove", "-y", f"anf/{LV1}"],
    ]
    assert mgr.snapshot_records(U1) is None
    assert [r["name"] for r in mgr.snapshot_records(U2)] == ["s1"]


# --- 스냅샷 생성 (결정 5~9) ---


def test_create_snapshot(host, mgr, tmp_path):
    create(mgr)
    host.calls.clear()
    mgr.create_snapshot(U1, S1, "daily.2026-11-08_0010")
    sm = snapmount(tmp_path, "daily.2026-11-08_0010")
    assert changes(host) == [
        # 읽기 전용 thin 스냅샷. activation skip을 꺼서 시작 복구의 vgchange -ay가 함께 활성화한다 (결정 5)
        ["lvcreate", "-s", "-kn", "-p", "r", "-n", SLV1,
         "--addtag", f"anf_snap_uuid={S1}", "--addtag", "anf_snap_name=daily.2026-11-08_0010",
         "--addtag", f"anf_snap_vol={U1}", "--addtag", "anf_snap_time=2026-11-08T23:07:12Z", f"anf/{LV1}"],
        # agent만 잠깐 +i를 풀고 마운트 지점을 만든다 (결정 8)
        ["chattr", "-i", snapdir(tmp_path)],
        ["chattr", "+i", snapdir(tmp_path)],
        ["mount", "-t", "ext4", "-o", "ro,noload", f"/dev/anf/{SLV1}", sm],
        ["exports", U1, "daily.2026-11-08_0010"],
    ]
    assert Path(sm).is_dir()
    assert snapdir(tmp_path) in host.immutable
    assert mgr.snapshot_records(U1) == [{
        "uuid": S1, "name": "daily.2026-11-08_0010", "create_time": "2026-11-08T23:07:12Z", "volume": {"uuid": U1},
    }]


def test_create_snapshot_again_only_reapplies_exports(host, mgr):
    create(mgr)
    mgr.create_snapshot(U1, S1, "s1")
    host.calls.clear()
    mgr.create_snapshot(U1, S1, "s1")
    assert changes(host) == [["exports", U1, "s1"]]
    assert [r["uuid"] for r in mgr.snapshot_records(U1)] == [S1]


def test_create_snapshot_resumes_after_mount_failure(host, mgr):
    create(mgr)
    host.fail["mount"] = "mount: wrong fs type"
    with pytest.raises(CommandError):
        mgr.create_snapshot(U1, S1, "s1")
    host.calls.clear()
    mgr.create_snapshot(U1, S1, "s1")
    assert [c[0] for c in changes(host)] == ["mount", "exports"]
    assert [lv for lv in host.lvs if lv.startswith("snap_")] == [SLV1]


def test_snapshot_dir_is_immutable_again_when_mkdir_fails(host, mgr, tmp_path, monkeypatch):
    create(mgr)

    def broken_mkdir(self, *args, **kwargs):
        raise OSError("No space left on device")

    monkeypatch.setattr(Path, "mkdir", broken_mkdir)
    with pytest.raises(OSError):
        mgr.create_snapshot(U1, S1, "s1")
    assert snapdir(tmp_path) in host.immutable


def test_snapshot_name_used_by_another_snapshot_fails(host, mgr):
    # ONTAP 525059 문구 (결정 9)
    create(mgr)
    mgr.create_snapshot(U1, S1, "s1")
    host.calls.clear()
    with pytest.raises(VolumeError, match="A snapshot with the specified name already exists."):
        mgr.create_snapshot(U1, S2, "s1")
    assert changes(host) == []


def test_same_name_on_another_volume_is_allowed(host, mgr):
    create(mgr)
    create(mgr, U2, "/vol2")
    mgr.create_snapshot(U1, S1, "s1")
    mgr.create_snapshot(U2, S2, "s1")
    assert [r["uuid"] for r in mgr.snapshot_records(U2)] == [S2]


def test_same_snapshot_uuid_with_another_name_fails(host, mgr):
    create(mgr)
    mgr.create_snapshot(U1, S1, "s1")
    host.calls.clear()
    with pytest.raises(VolumeError):
        mgr.create_snapshot(U1, S1, "s2")
    assert changes(host) == []


def test_snapshot_of_a_missing_volume_fails(host, mgr):
    with pytest.raises(VolumeError, match="not found"):
        mgr.create_snapshot(U1, S1, "s1")
    assert changes(host) == []


def test_snapshot_of_an_offline_volume_fails(host, mgr):
    # 마운트되지 않은 볼륨에는 .snapshot이 없다. 빈 마운트 지점 아래에 디렉터리를 만들지 않는다
    host.fail["mkfs.ext4"] = "boom"
    with pytest.raises(CommandError):
        create(mgr)
    host.calls.clear()
    with pytest.raises(VolumeError, match="offline"):
        mgr.create_snapshot(U1, S1, "s1")
    assert changes(host) == []


# --- 스냅샷 삭제 (결정 13) ---


def test_delete_snapshot_while_a_client_reads_it(host, mgr, tmp_path):
    create(mgr)
    mgr.create_snapshot(U1, S1, "s1")
    mgr.create_snapshot(U1, S2, "s2")
    host.held.add("vol1/.snapshot/s1")
    host.calls.clear()
    mgr.delete_snapshot(U1, S1)
    # export 줄을 빼고 → 인스턴스 안에서 잠금을 풀어야 → umount된다 (S4 E4·F1)
    assert changes(host) == [
        ["exports", U1, "s2"],
        ["unlock", U1, "vol1/.snapshot/s1"],
        ["umount", snapmount(tmp_path, "s1")],
        ["chattr", "-i", snapdir(tmp_path)],
        ["chattr", "+i", snapdir(tmp_path)],
        ["lvremove", "-y", f"anf/{SLV1}"],
    ]
    assert not Path(snapmount(tmp_path, "s1")).exists()
    assert snapmount(tmp_path, "s2") in host.mounts
    assert [r["uuid"] for r in mgr.snapshot_records(U1)] == [S2]


def test_delete_snapshot_waits_until_released(host, mgr):
    create(mgr)
    mgr.create_snapshot(U1, S1, "s1")
    host.calls.clear()
    host.busy = 2
    mgr.delete_snapshot(U1, S1)
    assert [c[0] for c in changes(host)].count("umount") == 3


def test_delete_missing_snapshot_succeeds(host, mgr):
    # ONTAP은 1638600이지만 볼륨 DELETE처럼 성공으로 둔다 (R-04)
    create(mgr)
    host.calls.clear()
    mgr.delete_snapshot(U1, S1)
    mgr.delete_snapshot(U2, S1)
    assert changes(host) == []


def test_delete_snapshot_resumes_after_failure(host, mgr):
    create(mgr)
    mgr.create_snapshot(U1, S1, "s1")
    host.fail["lvremove"] = "lvremove: device busy"
    with pytest.raises(CommandError):
        mgr.delete_snapshot(U1, S1)
    host.calls.clear()
    mgr.delete_snapshot(U1, S1)
    assert changes(host) == [["exports", U1], ["lvremove", "-y", f"anf/{SLV1}"]]


def test_delete_snapshot_of_another_volume_does_nothing(host, mgr):
    create(mgr)
    create(mgr, U2, "/vol2")
    mgr.create_snapshot(U1, S1, "s1")
    host.calls.clear()
    mgr.delete_snapshot(U2, S1)
    assert changes(host) == []


# --- 시작 복구 ---


def test_recover_after_reboot(host, mgr, tmp_path):
    create(mgr)
    create(mgr, U2, "/vol2", protocol="nfs4.1")
    host.fail["mkfs.ext4"] = "boom"
    with pytest.raises(CommandError):
        create(mgr, U3, "/vol3")
    host.reboot()
    mgr.recover()
    programs = [c[0] for c in changes(host)]
    # ns 공유 마운트 → (볼륨마다) 마운트 → export 파일 → 인스턴스 시작. 모두 띄운 뒤에 준비를 기다린다 (결정 14)
    assert programs == ["losetup", "vgchange", "shared-ns", "mount", "exports", "instance-start",
                        "mount", "exports", "instance-start", "instance-ready", "instance-ready"]
    assert host.instances == {U1: ("vol1", "172.30.0.129", "nfs3"), U2: ("vol2", "172.30.0.130", "nfs4.1")}
    assert set(host.mounts) == {mountpoint(tmp_path, "vol1"), mountpoint(tmp_path, "vol2")}


def test_recover_mounts_snapshots_before_the_instance_starts(host, mgr, tmp_path):
    create(mgr)
    mgr.create_snapshot(U1, S1, "s1")
    mgr.create_snapshot(U1, S2, "s2")
    host.reboot()
    mgr.recover()
    assert changes(host)[3:] == [
        ["mount", "-t", "ext4", "-o", "nodelalloc", f"/dev/anf/{LV1}", mountpoint(tmp_path, "vol1")],
        ["mount", "-t", "ext4", "-o", "ro,noload", f"/dev/anf/{SLV1}", snapmount(tmp_path, "s1")],
        ["mount", "-t", "ext4", "-o", "ro,noload", f"/dev/anf/{SLV2}", snapmount(tmp_path, "s2")],
        ["exports", U1, "s1", "s2"],
        ["instance-start", U1],
        ["instance-ready", U1],
    ]


def test_recover_finishes_a_snapshot_that_lost_its_mountpoint(host, mgr, tmp_path):
    # 스냅샷 LV를 만든 뒤 마운트 지점을 만들기 전에 멈췄다
    create(mgr)
    host.fail["chattr"] = "chattr: Input/output error"
    with pytest.raises(CommandError):
        mgr.create_snapshot(U1, S1, "s1")
    host.reboot()
    mgr.recover()
    assert snapmount(tmp_path, "s1") in host.mounts
    assert snapdir(tmp_path) in host.immutable


def test_recover_makes_old_volumes_get_a_snapshot_dir(host, mgr, tmp_path):
    # 스냅샷 기능 전에 만든 볼륨에는 .snapshot이 없다
    create(mgr)
    host.immutable.discard(snapdir(tmp_path))
    Path(snapdir(tmp_path)).rmdir()
    host.reboot()
    mgr.recover()
    assert Path(snapdir(tmp_path)).is_dir()
    assert snapdir(tmp_path) in host.immutable


# --- 조회 ---


def test_records(host, mgr):
    create(mgr)
    create(mgr, U2, "/vol2", 2 * GIB)
    mgr.create_snapshot(U1, S1, "s1")  # 스냅샷은 볼륨 목록에 나오지 않는다
    assert [r["uuid"] for r in mgr.records()] == [U1, U2]
    assert mgr.records(name=LV1) == [mgr.record(U1)]
    assert mgr.records(name="vol_nope") == []
    assert mgr.record(U3) is None


def test_unmounted_volume_is_offline(host, mgr):
    host.fail["mkfs.ext4"] = "boom"
    with pytest.raises(CommandError):
        create(mgr)
    assert mgr.record(U1)["state"] == "offline"


def test_snapshot_records(host, mgr):
    create(mgr)
    create(mgr, U2, "/vol2")
    mgr.create_snapshot(U1, S2, "weekly")
    mgr.create_snapshot(U1, S1, "daily")
    assert [r["name"] for r in mgr.snapshot_records(U1)] == ["daily", "weekly"]  # 이름순
    assert mgr.snapshot_records(U1, name="weekly") == [mgr.snapshot_record(U1, S2)]
    assert mgr.snapshot_records(U1, name="nope") == []
    assert mgr.snapshot_records(U2) == []
    assert mgr.snapshot_records(U3) is None  # 볼륨이 없다
    assert mgr.snapshot_record(U2, S1) is None  # 다른 볼륨의 스냅샷
    assert mgr.snapshot_record(U1, "5a000000-0000-4000-8000-000000000009") is None
