"""스냅샷 실환경 검증 도구 (스냅샷 설계 §8). test_snapshot_*_live.py가 쓰는 도우미 모듈이다.

볼륨 e2e 도우미(dataplane_live.py)의 픽스처(agent, api, clients)와 관찰 도구를 그대로 쓰고,
여기에는 스냅샷 ARM 경로, 스냅샷 LV·마운트·export 관찰, 쓰기 시도 목록만 더한다.
dataplane_live.dataplane()의 LV 목록에는 스냅샷 LV(snap_<uuid 32자리>)도 들어 있다.
"""

import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path

from live_api import LOC, V, call, poll
from dataplane_live import ACCT, NS, POLL, POOL, instance_name, sh, vol_path

SNAPSHOT_TYPE = "Microsoft.NetApp/netAppAccounts/capacityPools/volumes/snapshots"
EXPORTS = Path("/var/lib/anf-clone/exports")
ISO_UTC = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"
# 녹화 R1의 문구 (설계 §4.3)
NOT_FOUND = ("The requested snapshot '{snap}' was not found on the volume '{a}/{p}/{v}'. Please check the requested "
             "snapshot. Please note: The snapshot may no longer be available based on configured snapshot policies.")
THIN_POOL_DM = "anf-aggr0-tpool"

# AC-04: 스냅샷 안에서는 모두 실패해야 한다. {s}는 스냅샷 이름
SNAPSHOT_WRITES = [
    ("append", "echo x >> /m/.snapshot/{s}/a"),
    ("overwrite (dd conv=notrunc)", "dd if=/dev/zero of=/m/.snapshot/{s}/a bs=1 count=1 conv=notrunc"),
    ("touch new file", "touch /m/.snapshot/{s}/new"),
    ("rm", "rm /m/.snapshot/{s}/a"),
    ("mv inside snapshot", "mv /m/.snapshot/{s}/a /m/.snapshot/{s}/b"),
    ("mkdir", "mkdir /m/.snapshot/{s}/x"),
    ("chmod", "chmod 777 /m/.snapshot/{s}/a"),
]
# AC-04: .snapshot 자체도 바꿀 수 없다 (결정 8, chattr +i). 마지막 둘은 기준 밖의 보조 시도다
SNAPDIR_WRITES = [
    ("create file in .snapshot", "touch /m/.snapshot/f"),
    ("mkdir in .snapshot", "mkdir /m/.snapshot/x"),
    ("mv .snapshot", "mv /m/.snapshot /m/x"),
    ("chmod .snapshot", "chmod 700 /m/.snapshot"),
    ("rmdir .snapshot/{s}", "rmdir /m/.snapshot/{s}"),
    ("(extra) mv .snapshot/{s} out", "mv /m/.snapshot/{s} /m/moved"),
    ("(extra) rm -rf .snapshot", "rm -rf /m/.snapshot"),
]


# --- ARM 스냅샷 ---


def snap_path(vol: str, name: str, acct=ACCT, pool=POOL) -> str:
    return f"{vol_path(acct, pool, vol)}/snapshots/{name}"


def snap_url(vol: str, name: str, acct=ACCT, pool=POOL) -> str:
    return f"{snap_path(vol, name, acct, pool)}?{V}"


def snap_list_url(vol: str, acct=ACCT, pool=POOL) -> str:
    return f"{vol_path(acct, pool, vol)}/snapshots?{V}"


def create_snapshot(vol: str, name: str, acct=ACCT, pool=POOL, timeout=POLL) -> tuple[dict, dict]:
    """PUT → 201 → Succeeded. 반환: (GET 본문, 작업 종결 본문)."""
    r = call("PUT", snap_url(vol, name, acct, pool), {"location": LOC})
    assert r.status == 201, r.raw
    final, seen = poll(r.headers["azure-asyncoperation"], timeout)
    assert final["status"] == "Succeeded", (final, seen)
    g = call("GET", snap_url(vol, name, acct, pool))
    assert g.status == 200, g.raw
    return g.json(), final


def delete_snapshot(vol: str, name: str, acct=ACCT, pool=POOL, timeout=POLL) -> dict:
    d = call("DELETE", snap_url(vol, name, acct, pool))
    assert d.status in (202, 204), d.raw
    if d.status == 204:
        return {}
    final, seen = poll(d.headers["azure-asyncoperation"], timeout)
    assert final["status"] == "Succeeded", (final, seen)
    return final


def op_seconds(final: dict) -> float:
    """작업 상태 본문의 startTime → endTime (초)."""
    start, end = (datetime.fromisoformat(final[k].replace("Z", "+00:00")) for k in ("startTime", "endTime"))
    return round((end - start).total_seconds(), 3)


# --- 데이터 플레인 관찰 (root) ---


def snap_lv_name(snapshot_id: str) -> str:
    return "snap_" + snapshot_id.replace("-", "")


def snap_lvs() -> dict:
    """스냅샷 LV: 이름 → {attr, origin, tags}. 태그 anf_snap_uuid가 있는 LV만."""
    r = sh("lvs", "--reportformat", "json", "-o", "lv_name,lv_attr,origin,lv_tags", "anf")
    assert r.returncode == 0, r.stderr
    rows = json.loads(r.stdout)["report"][0]["lv"]
    found = {}
    for row in rows:
        tags = dict(t.split("=", 1) for t in row["lv_tags"].split(",") if "=" in t)
        if "anf_snap_uuid" in tags:
            found[row["lv_name"]] = {"attr": row["lv_attr"], "origin": row["origin"], "tags": tags}
    return found


def vol_snap_lvs(fsid: str) -> list[str]:
    """볼륨 하나의 스냅샷 LV 이름 (태그 anf_snap_vol). 다른 시험이 남긴 LV와 섞이지 않게 볼륨으로 거른다."""
    return sorted(n for n, x in snap_lvs().items() if x["tags"].get("anf_snap_vol") == fsid)


def lv_attrs(*names: str) -> dict:
    r = sh("lvs", "--noheadings", "-o", "lv_name,lv_attr", *[f"anf/{n}" for n in names])
    return dict(line.split() for line in r.stdout.splitlines() if line.strip())


def thin_used_bytes() -> int:
    """씬 풀(aggregate)에서 실제로 쓴 바이트: dmsetup status의 사용 블록 수 × 청크 크기."""
    status = sh("dmsetup", "status", THIN_POOL_DM).stdout.split()
    used = int(status[5].split("/")[0])
    chunk = int(sh("lvs", "--noheadings", "--units", "b", "--nosuffix", "-o", "chunk_size", "anf/aggr0").stdout)
    return used * chunk


def exports_file(fsid: str) -> str | None:
    path = EXPORTS / fsid.replace("-", "") / "volume.exports"
    return path.read_text() if path.exists() else None


def instance_etab(fsid: str) -> str:
    """인스턴스 안 knfsd에 적용된 export 표 (mountd의 etab)."""
    r = sh("docker", "exec", instance_name(fsid), "cat", "/var/lib/nfs/etab")
    return r.stdout if r.returncode == 0 else f"rc={r.returncode} {r.stderr.strip()}"


def exported_paths(text: str | None) -> list[str]:
    return sorted(line.split()[0] for line in (text or "").splitlines() if line.strip())


def snap_mounts(token_: str) -> list[str]:
    prefix = f"{NS / token_ / '.snapshot'}/"
    return sorted(t for t in sh("findmnt", "-rn", "-o", "TARGET").stdout.splitlines() if t.startswith(prefix))


def host_files(root: Path) -> dict:
    """root 아래 파일의 sha256 (호스트에서 스냅샷 마운트를 직접 읽는다)."""
    files = {}
    for dirpath, _, names in os.walk(root):
        for n in names:
            p = Path(dirpath) / n
            files[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return files


def lsattr_d(path: Path) -> str:
    return sh("lsattr", "-d", str(path)).stdout.split()[0]


def umount_retry(path: Path, attempts=120) -> int:
    """인스턴스를 멈춘 뒤에도 knfsd가 잠시 파일시스템을 잡는다. 성공한 시도 번호, 실패하면 0."""
    for n in range(1, attempts + 1):
        if sh("umount", str(path)).returncode == 0:
            return n
        time.sleep(0.5)
    return 0


def wait_instance_ready(fsid: str, timeout=150) -> float:
    """준비 표시(/run/anf-ready)가 생길 때까지 기다린 초. 제한 시간을 넘기면 -1."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if sh("docker", "exec", instance_name(fsid), "test", "-e", "/run/anf-ready").returncode == 0:
            return round(time.monotonic() - t0, 1)
        time.sleep(0.5)
    return -1.0


def instance_log_lines(fsid: str, *needles: str) -> list[str]:
    logs = sh("docker", "logs", instance_name(fsid))
    return [x for x in (logs.stdout + logs.stderr).splitlines() if any(n in x for n in needles)]
