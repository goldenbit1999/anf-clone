"""storage agent의 볼륨 관리자: 명령 순서, 멱등, 단계별 복구, IP 태그 (볼륨 설계 결정 5~10, 17, 18, §6.2).

가짜 호스트가 LVM·마운트·볼륨 인스턴스 상태를 들고 명령에 따라 바꾼다. 실행기와 인스턴스 관리자를 함께
흉내 내서, 컨테이너 시작·제거가 LVM·마운트 명령과 같은 기록에 순서대로 남는다. 출력 형식은
WSL Ubuntu 24.04(LVM 2.03.16)에서 확인한 것을 따른다. 실제 동작은 통합 테스트가 확인한다.
"""

import json
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
QUERIES = {"lvs", "vgs", "blkid", "findmnt"}


class FakeHost:
    """가짜 호스트. 커널(LVM·마운트) 명령과 볼륨 인스턴스(컨테이너)를 함께 흉내 낸다."""

    POOL_SIZE = 10 * GIB

    def __init__(self):
        self.calls: list[list[str]] = []
        self.loop = None  # 이미지가 붙은 루프 장치
        self.vg = False  # 이미지 안에 VG `anf`가 있음
        self.pool = False
        self.lvs: dict[str, dict] = {}  # LV 이름 → {"size", "tags", "fs", "lost_found"}
        self.mounts: dict[str, str] = {}  # 마운트 지점 → 장치
        self.shared_ns = False
        self.instances: dict[str, tuple] = {}  # 돌고 있는 인스턴스: uuid → (token, ip, protocol)
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
        if uuid in self.instances:
            return
        if "instance" in self.fail:
            raise CommandError(["docker", "run"], Result(125, "", self.fail.pop("instance")))
        # 인스턴스는 호스트 마운트 뒤에 시작한다 (결정 17)
        assert token in {Path(t).name for t in self.mounts}, "instance started before the host mount"
        self.calls.append(["instance-start", uuid])
        self.instances[uuid] = (token, ip, protocol)

    def remove(self, uuid):
        if self.instances.pop(uuid, None) is not None:
            self.calls.append(["instance-remove", uuid])

    # --- 흉내 ---

    def reboot(self):
        # WSL 재시작: 루프 장치, 마운트, 공유 마운트가 사라지고 인스턴스 컨테이너가 멈춘다. 이미지 파일은 남는다
        for target in list(self.mounts):
            self._detach(target)
        self.loop = None
        self.shared_ns = False
        self.instances.clear()
        self.calls.clear()

    def _detach(self, target):
        # 파일시스템 내용은 lost+found 유무로만 흉내 낸다. 언마운트하면 마운트 지점은 빈 디렉터리다
        lost_found = Path(target) / "lost+found"
        self.lvs[self.mounts.pop(target).removeprefix("/dev/anf/")]["lost_found"] = lost_found.is_dir()
        if lost_found.is_dir():
            lost_found.rmdir()

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
            {"lv_name": name, "lv_size": str(lv["size"]), "lv_tags": ",".join(lv["tags"])}
            for name, lv in self.lvs.items()
        ]
        return self.ok(json.dumps({"report": [{"lv": rows}]}))

    def _lvcreate(self, args):
        assert args[-1] == "anf"
        pairs = list(zip(args[:-1:2], args[1:-1:2]))
        opts = dict(pairs)
        if opts["--type"] == "thin-pool":
            self.pool = True
        else:
            assert opts["--type"] == "thin" and opts["--thinpool"] == "aggr0"
            tags = [value for flag, value in pairs if flag == "--addtag"]
            self.lvs[opts["-n"]] = {"size": int(opts["-V"].removesuffix("b")), "tags": tags, "fs": None}
        return self.ok()

    def _blkid(self, args):
        lv = self.lvs.get(args[-1].removeprefix("/dev/anf/"))
        return self.ok(lv["fs"] + "\n") if lv and lv["fs"] else Result(2, "", "")

    def _mkfs_ext4(self, args):
        lv = self.lvs[args[-1].removeprefix("/dev/anf/")]
        lv["fs"], lv["lost_found"] = "ext4", True
        return self.ok()

    def _findmnt(self, args):
        return self.ok("".join(f"{target}\n" for target in self.mounts))

    def _mount(self, args):
        device, target = args[-2], args[-1]
        assert Path(target).is_dir()
        if self.lvs[device.removeprefix("/dev/anf/")]["lost_found"]:
            (Path(target) / "lost+found").mkdir()
        self.mounts[target] = device
        return self.ok()

    def _umount(self, args):
        # 볼륨 인스턴스의 knfsd가 파일시스템을 잡고 있는 동안은 내릴 수 없다 (실환경 확인)
        exported = Path(args[0]).name in {token for token, _, _ in self.instances.values()}
        if exported or self.busy:
            self.busy = max(self.busy - 1, 0)
            return Result(32, "", f"umount: {args[0]}: target is busy.\n")
        self._detach(args[0])
        return self.ok()

    def _chmod(self, args):
        return self.ok()

    def _lvremove(self, args):
        assert args[0] == "-y"
        del self.lvs[args[1].removeprefix("anf/")]
        return self.ok()


def changes(host):
    """상태를 바꾸는 명령만 (조회 명령 제외)."""
    return [c for c in host.calls if c[0] not in QUERIES and c[:2] != ["losetup", "-j"]]


def make_manager(host, tmp_path):
    m = FlexVolManager(host, root=tmp_path / "root", aggregate_size=1 << 20, sleep=lambda s: None)
    m.instances = host  # 컨테이너 대신 가짜 호스트가 볼륨 인스턴스를 흉내 낸다
    return m


def mountpoint(tmp_path, token):
    return str(tmp_path / "root" / "ns" / token)


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
        ["instance-start", U1],
    ]
    assert not (Path(mp) / "lost+found").exists()
    assert host.instances[U1] == ("vol1", "172.30.0.129", "nfs4.1")
    assert mgr.record(U1) == {
        "uuid": U1, "name": LV1, "size": GIB, "nas": {"path": "/vol1", "protocols": ["nfs4.1"]},
        "state": "online", "data_lif": {"ip": {"address": "172.30.0.129"}},
    }


def test_create_again_changes_nothing(host, mgr):
    # 이미 된 단계는 건너뛴다. 클라이언트가 바꿨을 수 있는 루트 권한도 다시 바꾸지 않는다
    create(mgr)
    host.calls.clear()
    create(mgr)
    assert changes(host) == []
    assert list(host.lvs) == [LV1]


def test_create_resumes_after_mkfs_failure(host, mgr):
    host.fail["mkfs.ext4"] = "mkfs.ext4: Device or resource busy"
    with pytest.raises(CommandError):
        create(mgr)
    host.calls.clear()
    create(mgr)
    assert [c[0] for c in changes(host)] == ["mkfs.ext4", "mount", "chmod", "instance-start"]
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
    assert [c[0] for c in changes(host)] == ["chmod", "instance-start"]
    assert not lost_found.exists()


def test_create_resumes_after_instance_failure(host, mgr):
    host.fail["instance"] = "docker: Error response from daemon"
    with pytest.raises(CommandError):
        create(mgr)
    host.calls.clear()
    create(mgr)
    assert changes(host) == [["instance-start", U1]]


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
        host.lvs[f"vol_x{i}"] = {"size": 1, "fs": None,
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
    assert changes(host) == [["instance-remove", U1], ["umount", mp], ["lvremove", "-y", f"anf/{LV1}"]]
    assert not Path(mp).exists()
    assert mgr.record(U1) is None
    assert list(host.instances) == [U2]


def test_delete_waits_until_the_file_system_is_released(host, mgr):
    # 인스턴스를 지운 뒤에도 잠시 busy일 수 있다 (S2: 1분 안쪽, 볼륨 세션: 25초)
    create(mgr)
    host.calls.clear()
    host.busy = 3
    mgr.delete(U1)
    assert [c[0] for c in changes(host)] == ["instance-remove", "umount", "umount", "umount", "umount", "lvremove"]


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
    assert changes(host) == [["lvremove", "-y", f"anf/{LV1}"]]
    assert host.lvs == {}


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
    # ns 공유 마운트 → 볼륨 마운트 → 인스턴스 (결정 10, 17)
    assert programs == ["losetup", "vgchange", "shared-ns", "mount", "instance-start", "mount", "instance-start"]
    assert host.instances == {U1: ("vol1", "172.30.0.129", "nfs3"), U2: ("vol2", "172.30.0.130", "nfs4.1")}
    assert set(host.mounts) == {mountpoint(tmp_path, "vol1"), mountpoint(tmp_path, "vol2")}


# --- 조회 ---


def test_records(host, mgr):
    create(mgr)
    create(mgr, U2, "/vol2", 2 * GIB)
    assert [r["uuid"] for r in mgr.records()] == [U1, U2]
    assert mgr.records(name=LV1) == [mgr.record(U1)]
    assert mgr.records(name="vol_nope") == []
    assert mgr.record(U3) is None


def test_unmounted_volume_is_offline(host, mgr):
    host.fail["mkfs.ext4"] = "boom"
    with pytest.raises(CommandError):
        create(mgr)
    assert mgr.record(U1)["state"] == "offline"
