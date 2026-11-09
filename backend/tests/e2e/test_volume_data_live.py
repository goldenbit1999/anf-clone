"""볼륨 e2e (2/3): 클라이언트에서 관찰한 데이터 효과 (볼륨 설계 §8).

- AC-02 NFSv3: 두 클라이언트가 같은 파일을 쓰고 읽는다. 다른 버전은 거절
- AC-03 NFSv4.1: 마운트·쓰기·읽기. 다른 버전은 거절. 인스턴스가 유예 기간 없이 서비스한다
- AC-04 할당량을 넘는 쓰기는 ENOSPC
- AC-09 삭제 뒤 마운트 실패와 공간 회수, 같은 경로·IP 재사용
- AC-15 NFSv4.1 볼륨마다 따로 있는 서버(IP, 연결)
- 반복 시험: 새 인스턴스를 연달아 만들고 바로 첫 쓰기를 잰다 (라운드 수 ANF_E2E_REPEAT, 기본 6)

실행 (WSL, root, 저장소 루트):
    wsl -d Ubuntu -u root -e bash -c 'cd /mnt/c/<repo> && PYTHONDONTWRITEBYTECODE=1 \
        ANF_E2E_API_URL=http://127.0.0.1:8080 /home/<user>/.venvs/anf-clone/bin/python -m pytest \
        -p no:cacheprovider backend/tests/e2e/test_volume_data_live.py -v -s'
볼륨 e2e 세 파일을 한 번에: 파일 대신 `-m dataplane backend/tests/e2e`.
"""

import ipaddress
import os
import re
import time
import uuid

import pytest

import live_api
from live_api import call, poll
from dataplane_live import (
    ACCT, agent_call, agent_job, create_volume, default_rule, delete_volume, error_of, fsid_of, GIB,
    instance_name, instance_ok, instance_status, lv_name, lvs_volumes, mount_ip, note, NS, one_shot, out,
    POOL, setup_pool, sh, SKIP_UNLESS_ROOT, thin_data_percent, token, vol_url, VOLUME_IPS,
)

pytestmark = [pytest.mark.e2e, pytest.mark.dataplane, live_api.SKIP_UNLESS_LIVE, SKIP_UNLESS_ROOT]

# 새 볼륨의 첫 NFSv4.1 쓰기 한도. 정상은 1초 안팎이고, 유예 기간에 걸리면 90초 넘게 막힌다 (1회차 AC-03)
FIRST_IO_SECONDS = 10


# --- AC-02 ---


def test_ac02_nfsv3_mount_two_clients(agent, api, clients):
    api()
    setup_pool()
    tok = token("ac02")
    v = create_volume("vol2", tok)
    ip = mount_ip(v)
    a, b = clients(), clients()
    content = f"from-a-{uuid.uuid4().hex}"

    a.mount(ip, tok, "3")
    w = a.run(f"echo {content} > /m/shared.txt && sync && stat -c %a /m && grep ' /m ' /proc/mounts")
    note("AC-02 client A write", **out(w))
    assert w.returncode == 0, out(w)
    assert w.stdout.splitlines()[0] == "770"
    assert "vers=3" in w.stdout and f"addr={ip}" in w.stdout

    b.mount(ip, tok, "3")
    rd = b.run("cat /m/shared.txt && stat -c %a /m")
    note("AC-02 client B read", **out(rd))
    assert rd.returncode == 0, out(rd)
    assert rd.stdout.splitlines() == [content, "770"]

    v41 = one_shot(ip, tok, "4.1")
    note("AC-02 vers=4.1 on NFSv3 volume", **out(v41))
    assert v41.returncode != 0

    for c in (a, b):
        c.run("umount /m")
    delete_volume("vol2")


# --- AC-03 ---


def test_ac03_nfsv41_volume(agent, api, clients):
    api()
    setup_pool()
    tok = token("ac03")
    v = create_volume("vol3", tok, protocols=["NFSv4.1"])
    p = v["properties"]
    note("AC-03 GET", protocolTypes=p["protocolTypes"], rules=p["exportPolicy"]["rules"])
    assert p["protocolTypes"] == ["NFSv4.1"]
    assert p["exportPolicy"] == {"rules": [default_rule(False, True)]}
    ip = mount_ip(v)

    a, b = clients(), clients()
    a.mount(ip, tok, "4.1")
    t0 = time.monotonic()
    w = a.run("echo v41-data > /m/f && sync && cat /m/f && grep ' /m ' /proc/mounts")
    seconds, st = round(time.monotonic() - t0, 2), instance_status(fsid_of(v))
    note("AC-03 write/read", seconds=seconds, instance=st, **out(w))
    assert w.returncode == 0, out(w)
    # Succeeded 뒤 첫 쓰기가 NFSv4 유예 기간(90초)에 막히지 않아야 한다 (1회차 FAIL: nfsdcld 준비 전에 rpc.nfsd)
    assert instance_ok(st) and seconds < FIRST_IO_SECONDS, (seconds, st)
    assert w.stdout.splitlines()[0] == "v41-data"
    assert "vers=4.1" in w.stdout and f"addr={ip}" in w.stdout
    b.mount(ip, tok, "4.1")
    rd = b.run("cat /m/f")
    assert rd.returncode == 0 and rd.stdout == "v41-data\n", out(rd)

    for vers in ("3", "4.0"):
        r = one_shot(ip, tok, vers)
        note(f"AC-03 vers={vers} on NFSv4.1 volume", **out(r))
        assert r.returncode != 0

    for c in (a, b):
        c.run("umount /m")
    delete_volume("vol3")


# --- AC-04 ---


@pytest.mark.parametrize("protocol,vers", [("NFSv3", "3"), ("NFSv4.1", "4.1")])
def test_ac04_quota_full_write_fails(agent, api, clients, protocol, vers):
    api()
    setup_pool()
    tok = token(f"ac04{vers.replace('.', '')}")
    v = create_volume("vol4", tok, GIB, [protocol])
    c = clients()
    c.mount(mount_ip(v), tok, vers)

    keep = f"keep-{uuid.uuid4().hex}"
    assert c.run(f"echo {keep} > /m/keep && sync").returncode == 0
    df = c.run("df -B1 /m | tail -1")
    size = int(df.stdout.split()[1])
    t0 = time.monotonic()
    dd = c.run("dd if=/dev/zero of=/m/big bs=1M count=1229 conv=fsync", timeout=600)
    dd_seconds = round(time.monotonic() - t0, 1)
    after = c.run("ls -l /m/big; df -B1 /m | tail -1; cat /m/keep")
    host = sh("stat", "-c", "size=%s blocks512=%b", str(NS / tok / "big"))  # 서버 쪽 실제 파일
    note(f"AC-04 {protocol}", df_before=df.stdout.strip(), df_size_bytes=size, dd=out(dd), dd_seconds=dd_seconds,
         after=out(after), host_file=host.stdout.strip())
    assert 0.9 * GIB <= size <= GIB
    assert dd.returncode != 0
    assert "No space left on device" in dd.stderr
    assert after.stdout.splitlines()[-1] == keep

    c.run("umount /m")
    delete_volume("vol4")


# --- AC-09 ---


def test_ac09_delete_volume(agent, api, clients):
    api()
    setup_pool()
    tok = token("ac09")
    thin0 = thin_data_percent()
    v = create_volume("v09", tok)
    ip, fsid = mount_ip(v), fsid_of(v)
    pre = clients()  # 삭제 전에 마운트해 둔 클라이언트
    pre.mount(ip, tok, "3", opts="soft,timeo=20,retrans=1")
    w = pre.run("dd if=/dev/urandom of=/m/data bs=1M count=200 conv=fsync 2>&1 && echo hello > /m/f && sync")
    assert w.returncode == 0, out(w)
    thin1 = thin_data_percent()

    t0 = time.monotonic()
    d = call("DELETE", vol_url(ACCT, POOL, "v09"))
    lro_headers = sorted(h for h in d.headers if h in ("azure-asyncoperation", "location"))
    assert d.status == 202 and d.raw == b"", (d.status, d.raw)
    final, seen = poll(d.headers["azure-asyncoperation"], 150)
    delete_seconds = round(time.monotonic() - t0, 1)
    g = call("GET", vol_url(ACCT, POOL, "v09"))
    d2 = call("DELETE", vol_url(ACCT, POOL, "v09"))
    d2_headers = sorted(h for h in d2.headers if h in ("azure-asyncoperation", "location"))
    note("AC-09 DELETE", status=d.status, lro_headers=lro_headers, seen=seen, final=final,
         delete_seconds=delete_seconds, get_after=error_of(g), second_delete=d2.status, second_headers=d2_headers)
    assert lro_headers == ["azure-asyncoperation", "location"]
    assert final["status"] == "Succeeded" and final["properties"]["action"] == "DELETE"
    assert g.status == 404
    assert d2.status == 204 and d2.raw == b"" and d2_headers == []

    mount_after = one_shot(ip, tok, "3")
    inspect = sh("docker", "inspect", instance_name(fsid))
    thin2 = thin_data_percent()
    note("AC-09 after delete", new_mount=out(mount_after), instance_inspect_rc=inspect.returncode,
         lv_present=lv_name(fsid) in lvs_volumes(), ns_entry=(NS / tok).exists(),
         thin_data_percent={"before_create": thin0, "after_write_200MiB": thin1, "after_delete": thin2})
    assert mount_after.returncode != 0
    assert inspect.returncode != 0
    assert lv_name(fsid) not in lvs_volumes()
    assert not (NS / tok).exists()

    seen_by_pre = pre.run("timeout 60 cat /m/f; echo rc=$?; timeout 60 ls /m; echo rc=$?", timeout=200)
    note("AC-09 pre-mounted client after delete", **out(seen_by_pre))

    used = {r["data_lif"]["ip"]["address"] for r in agent_call("GET", "/api/storage/volumes")[1]["records"]}
    v2 = create_volume("v09", tok)
    again = one_shot(mount_ip(v2), tok, "3", "ls -A /m; echo listed")
    seen_by_pre2 = pre.run("timeout 60 ls /m; echo rc=$?", timeout=200)
    note("AC-09 recreate", ip_before=ip, ip_after=mount_ip(v2), lowest_free=min(set(VOLUME_IPS) - used,
         key=ipaddress.ip_address), fsid_before=fsid, fsid_after=fsid_of(v2), mount=out(again),
         pre_mounted_client=out(seen_by_pre2))
    assert mount_ip(v2) == ip
    assert fsid_of(v2) != fsid
    # 새 볼륨에는 옛 데이터가 없고 `.snapshot`만 있다 (스냅샷 설계 결정 8: 스냅샷이 없어도 `.snapshot`이 있다)
    assert again.returncode == 0 and again.stdout == ".snapshot\nlisted\n", out(again)

    pre.remove()
    delete_volume("v09")


# --- AC-15 ---


def test_ac15_each_nfsv41_volume_has_its_own_server(agent, api, clients):
    api()
    setup_pool()
    t1, t2 = token("ac15a"), token("ac15b")
    v1 = create_volume("v15a", t1, protocols=["NFSv4.1"])
    v2 = create_volume("v15b", t2, protocols=["NFSv4.1"])
    ip1, ip2 = mount_ip(v1), mount_ip(v2)
    c = clients()
    c.mount(ip1, t1, "4.1", "/m1")
    c.mount(ip2, t2, "4.1", "/m2")
    t0 = time.monotonic()
    io = c.run("echo a > /m1/a && echo b > /m2/b && sync && cat /m1/a /m2/b")
    seconds = round(time.monotonic() - t0, 2)
    graces = [instance_status(fsid_of(v1)), instance_status(fsid_of(v2))]
    note("AC-15 first I/O", seconds=seconds, instances=graces)
    mounts = c.run("grep -E ' /m[12] ' /proc/mounts")
    ss = sh("nsenter", "-t", c.pid(), "-n", "ss", "-tn")
    # clientaddr=가 아니라 서버 주소 addr=를 읽는다
    addr = {line.split()[1]: re.search(r",addr=([0-9.]+)", line).group(1) for line in mounts.stdout.splitlines()}
    conns = [line for line in ss.stdout.splitlines() if ":2049" in line]
    note("AC-15", ips=[ip1, ip2], io=out(io), proc_mounts=mounts.stdout, mount_addr=addr, ss=ss.stdout)
    assert ip1 != ip2
    assert io.returncode == 0 and io.stdout == "a\nb\n"
    # 1회차에 3번 중 2번 첫 쓰기가 90~102초 막혔다 (NFSv4 유예 기간). AC-03과 같은 판정이다
    assert all(instance_ok(g) for g in graces) and seconds < FIRST_IO_SECONDS, (seconds, graces)
    assert addr == {"/m1": ip1, "/m2": ip2}
    assert any(f"{ip1}:2049" in line for line in conns) and any(f"{ip2}:2049" in line for line in conns)

    c.run("umount /m1; umount /m2")
    delete_volume("v15a")
    delete_volume("v15b")


# --- AC-03·AC-15 보조: 새 인스턴스가 유예 기간 없이 바로 OPEN을 받는가 ---


def test_nfsv41_new_instances_skip_grace_repeated(agent):
    """agent로 NFSv4.1 볼륨 두 개를 연달아 만들고(AC-15와 같은 순서) 각각 첫 쓰기 시간을 잰다. 반복 횟수는 ANF_E2E_REPEAT."""
    rounds = int(os.environ.get("ANF_E2E_REPEAT", "6"))
    samples = []
    for n in range(rounds):
        made = []
        for k in range(2):
            vid = str(uuid.uuid4())
            tok = token(f"g{n}{k}")
            t0 = time.monotonic()
            st, reply = agent_call("POST", "/api/storage/volumes", {
                "uuid": vid, "name": lv_name(vid), "size": GIB,
                "nas": {"path": f"/{tok}", "unix_permissions": 770, "protocols": ["nfs4.1"]}})
            assert st == 202 and agent_job(reply["job"]["_links"]["self"]["href"])["state"] == "success"
            made.append((vid, tok, round(time.monotonic() - t0, 2)))
        # 두 번째 볼륨은 job이 끝난 직후 바로 마운트한다
        for vid, tok, create_seconds in reversed(made):
            ip = agent_call("GET", f"/api/storage/volumes/{vid}")[1]["data_lif"]["ip"]["address"]
            t0 = time.monotonic()
            w = one_shot(ip, tok, "4.1", "timeout -s KILL 20 sh -c 'echo x > /m/f'")
            seconds = round(time.monotonic() - t0, 2)
            samples.append({"round": n, "volume": tok, "create_seconds": create_seconds, **instance_status(vid),
                            "write_rc": w.returncode, "seconds": seconds, "stderr": w.stderr.strip()})
        for vid, _, _ in made:
            st, reply = agent_call("DELETE", f"/api/storage/volumes/{vid}")
            assert agent_job(reply["job"]["_links"]["self"]["href"], 180)["state"] == "success"
    bad = [s for s in samples if not instance_ok(s) or s["write_rc"] != 0 or s["seconds"] >= FIRST_IO_SECONDS]
    note("NFSv4.1 grace repeat", rounds=rounds, samples=samples, bad=len(bad))
    assert bad == []
