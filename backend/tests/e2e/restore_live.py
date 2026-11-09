"""스냅샷에서 새 볼륨 실환경 검증 도구 (복원 설계 §8). test_restore_new_volume_*_live.py가 쓰는 도우미 모듈이다.

볼륨·스냅샷·되돌리기 e2e 도우미(dataplane_live.py, snapshot_live.py, revert_live.py)를 그대로 쓰고, 여기에는
`snapshotId`가 있는 볼륨 PUT, 다른 풀의 스냅샷 목록, 새 볼륨 LV의 진행 표시(`anf_cl_*`)·origin 관찰,
base 스냅샷 안의 쓰기 시도 목록만 더한다.
"""

import time

from live_api import call, poll
from dataplane_live import ACCT, GIB, POLL, POOL, lv_name, lvs_volumes, sh, vol_body, vol_url
from snapshot_live import snap_list_url

# AC-03: base 스냅샷 안에서는 모두 실패해야 한다. {s}는 스냅샷 이름, K는 기록의 파일이다 (revert_live.STEPS)
BASE_WRITES = [
    ("append", "echo x >> /m/.snapshot/{s}/K"),
    ("overwrite (dd conv=notrunc)", "dd if=/dev/zero of=/m/.snapshot/{s}/K bs=1 count=1 conv=notrunc"),
    ("truncate (>)", "echo y > /m/.snapshot/{s}/K"),
    ("touch new file", "touch /m/.snapshot/{s}/new"),
    ("rm", "rm /m/.snapshot/{s}/K"),
    ("mv inside snapshot", "mv /m/.snapshot/{s}/K /m/.snapshot/{s}/K2"),
    ("mkdir", "mkdir /m/.snapshot/{s}/x"),
    ("chmod", "chmod 777 /m/.snapshot/{s}/K"),
]
# 기준 밖의 보조 시도: 새 볼륨의 `.snapshot` 자체 (결정 8의 chattr +i)
SNAPDIR_WRITES = [
    ("rmdir .snapshot/{s}", "rmdir /m/.snapshot/{s}"),
    ("touch in .snapshot", "touch /m/.snapshot/f"),
    ("mkdir in .snapshot", "mkdir /m/.snapshot/x"),
]
WRITE_REFUSALS = ("Read-only file system", "Permission denied")


def restore_body(token_: str, snapshot_id, size: int = GIB, protocols=None, **extra) -> dict:
    return vol_body(token_, size, protocols, snapshotId=snapshot_id, **extra)


def put_restore(name: str, token_: str, snapshot_id, size: int = GIB, protocols=None, acct=ACCT, pool=POOL,
                **extra):
    return call("PUT", vol_url(acct, pool, name), restore_body(token_, snapshot_id, size, protocols, **extra))


def restore_volume(name: str, token_: str, snapshot_id: str, size: int = GIB, protocols=None, acct=ACCT, pool=POOL,
                   timeout=POLL, **extra) -> tuple:
    """snapshotId PUT → 201 → Succeeded. 반환: (PUT 응답, 종결 본문, 관찰한 status 순서, GET 본문)."""
    r = put_restore(name, token_, snapshot_id, size, protocols, acct, pool, **extra)
    assert r.status == 201, r.raw
    final, seen = poll(r.headers["azure-asyncoperation"], timeout)
    assert final["status"] == "Succeeded", (final, seen)
    g = call("GET", vol_url(acct, pool, name))
    assert g.status == 200, g.raw
    return r, final, seen, g.json()


def listing_in(vol: str, acct=ACCT, pool=POOL) -> dict:
    """ARM 스냅샷 목록(다른 풀도): 이름 → 본문."""
    r = call("GET", snap_list_url(vol, acct, pool))
    assert r.status == 200, r.raw
    return {s["name"].split("/")[-1]: s for s in r.json()["value"]}


def state_in(name: str, acct=ACCT, pool=POOL) -> str:
    return call("GET", vol_url(acct, pool, name)).json()["properties"]["provisioningState"]


# --- 데이터 플레인 관찰 (root) ---


def cl_tags(fsid: str) -> list[str]:
    """새 볼륨 LV의 진행 표시 (결정 10). 끝나면 비어 있다."""
    lv = lvs_volumes().get(lv_name(fsid))
    return sorted(t for t in (lv["tags"].split(",") if lv else []) if t.startswith("anf_cl_"))


def lv_origin(fsid: str) -> str:
    return sh("lvs", "--noheadings", "-o", "origin", f"anf/{lv_name(fsid)}").stdout.strip()


def lv_attr(fsid: str) -> str:
    return sh("lvs", "--noheadings", "-o", "lv_attr", f"anf/{lv_name(fsid)}").stdout.strip()


def ext4_uuid(lv: str) -> str:
    return sh("blkid", "-o", "value", "-s", "UUID", f"/dev/anf/{lv}").stdout.strip()


def df_bytes(c, path: str = "/m") -> tuple[int, int, int]:
    """클라이언트 df: (크기, 사용, 남음) 바이트."""
    r = c.run(f"df -B1 {path} | tail -1")
    assert r.returncode == 0, r.stderr
    size, used, avail = (int(x) for x in r.stdout.split()[1:4])
    return size, used, avail


def try_writes(c, snap: str, writes=BASE_WRITES) -> list[dict]:
    rows = []
    for label, cmd in writes:
        r = c.run(cmd.format(s=snap))
        rows.append({"op": label.format(s=snap), "rc": r.returncode, "stderr": r.stderr.strip()})
    return rows


def wait_for(predicate, timeout: float, interval: float = 0.2):
    """predicate()가 참 값을 돌려줄 때까지 기다린다. 반환: (값, 걸린 초). 시간을 넘기면 (None, 초)."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        v = predicate()
        if v:
            return v, round(time.monotonic() - t0, 2)
        time.sleep(interval)
    return None, round(time.monotonic() - t0, 2)
