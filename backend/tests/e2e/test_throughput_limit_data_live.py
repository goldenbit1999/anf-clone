"""처리량 한도 e2e (2/2): 클라이언트가 잰 데이터 처리량 (처리량 설계 §8).

- AC-01 (b) Auto 볼륨(Ultra 40 GiB = 5 MiB/s) v3·v4.1: 순차 쓰기·읽기, netns HTB rate
- AC-02 Manual 볼륨 10 MiB/s (v4.1)·20 MiB/s (v3): 순차 쓰기·읽기
- AC-03 같은 볼륨의 읽기 job + 쓰기 job 합 (v3, v4.1)
- AC-04 I/O 중 한도 변경: PATCH 10 → 30 → 5와 재PUT(Updating) → 10, 1초 창
- AC-05 4,500 MiB/s 볼륨 B와 10 MiB/s 볼륨 A를 같은 클라이언트에서: 차이와 독립성
- AC-06 1 GiB Premium Auto (0.062 MiB/s): 작은 I/O가 오류 없이 되고, 큰 직접 쓰기가 상한 아래다
- AC-07 (a)~(e) 수명 주기 뒤에도 한도가 걸려 있다 ((f)는 계약 파일)
- AC-09 Auto → Manual 전환 전후 잰 값이 같고, 그 뒤 PATCH가 한도를 바꾼다

측정 방법은 throughput_live.py에 있다. ANF_E2E_FIO_RUNS(기본 5)로 회수를 바꾼다. 이 파일은 30분 넘게 걸린다.

실행 (WSL, root, 저장소 루트):
    wsl -d Ubuntu -u root -e bash -c 'cd /mnt/c/<repo> && PYTHONDONTWRITEBYTECODE=1 \
        ANF_E2E_API_URL=http://127.0.0.1:8080 /home/<user>/.venvs/anf-clone/bin/python -m pytest \
        -p no:cacheprovider backend/tests/e2e/test_throughput_limit_data_live.py -v -s'
"""

import statistics
import time

import pytest

import live_api
from live_api import TIB, call, create_account, create_pool, poll, pool_url
from dataplane_live import (
    ACCT, delete_volume, fsid_of, GIB, instance_name, mount_ip, note, sh, SKIP_UNLESS_ROOT, token, vol_body,
    vol_url,
)
from restore_live import restore_volume
from revert_live import fast_poll, instance_pid, post_revert
from snapshot_live import create_snapshot
from throughput_live import (
    HIGH, LOW, RUNS, SECONDS, Sampler, drop_caches, fio, htb_sent, ifb_tx_bytes, in_background, limits, make,
    matches, measure, measure_mixed, patch_volume, pool_props, tc_state, within,
)

pytestmark = [pytest.mark.e2e, pytest.mark.dataplane, live_api.SKIP_UNLESS_LIVE, SKIP_UNLESS_ROOT]


def band(mibps: float) -> float:
    """두 측정값의 차이 허용 폭: 허용 오차 띠의 너비(한도의 11%)."""
    return (HIGH - LOW) * mibps


def mounts(c) -> list[str]:
    return sorted(line for line in c.run("cat /proc/mounts").stdout.splitlines() if " nfs" in line)


# --- AC-01 (b) ---


def test_ac01b_auto_volume_data(agent, api, clients):
    api()
    create_account(ACCT)
    create_pool(ACCT, "ua", TIB, "Ultra")  # Auto: 40 GiB × 128 MiB/s/TiB = 5.0
    c = clients()
    results = {}
    for name, protocols, vers in (("a3", None, "3"), ("a41", ["NFSv4.1"], "4.1")):
        tok = token(f"d1{name}")
        *_, v = make(name, tok, "ua", 40 * GIB, protocols)
        c.mount(mount_ip(v), tok, vers, f"/{name}")
        results[name] = {"actual": v["properties"]["actualThroughputMibps"], "tc": tc_state(fsid_of(v)),
                         "write": measure(c, "write", f"/{name}/f", 5.0),
                         "read": measure(c, "read", f"/{name}/f", 5.0)}
        note("AC-01b", volume=name, vers=vers, **results[name])
    c.remove()
    for name in results:
        delete_volume(name, pool="ua")
    for name, x in results.items():
        assert x["actual"] == 5.0 and matches(x["tc"], 5.0), (name, x)
        assert within(x["write"]["ratio"]) and within(x["read"]["ratio"]), (name, x)


# --- AC-02, AC-03 ---


def test_ac02_ac03_manual_volume_data_and_shared_read_write(agent, api, clients):
    api()
    create_account(ACCT)
    create_pool(ACCT, "um", 40 * TIB, "Ultra", qos_type="Manual")
    c = clients()
    results = {}
    for name, protocols, vers, mibps in (("m41", ["NFSv4.1"], "4.1", 10), ("m3", None, "3", 20)):
        tok = token(f"d2{name}")
        *_, v = make(name, tok, "um", 2 * GIB, protocols, throughputMibps=mibps)
        fsid = fsid_of(v)
        c.mount(mount_ip(v), tok, vers, f"/{name}")
        x = {"limit": mibps, "tc": tc_state(fsid), "write": measure(c, "write", f"/{name}/f", mibps),
             "read": measure(c, "read", f"/{name}/f", mibps),
             "mixed": measure_mixed(c, f"/{name}/f", f"/{name}/g", mibps)}
        # 판정 밖의 기록: ifb0 송신 바이트와 HTB Sent 바이트가 같은 값인가 (설계 §6.3)
        x["counters"] = {"ifb0_tx": ifb_tx_bytes(instance_pid(fsid)), "htb_sent": htb_sent(fsid)}
        results[name] = x
        note("AC-02/03", volume=name, vers=vers, **x)
    c.remove()
    for name in results:
        delete_volume(name, pool="um")
    for name, x in results.items():
        assert matches(x["tc"], x["limit"]), (name, x["tc"])
        assert within(x["write"]["ratio"]) and within(x["read"]["ratio"]), (name, x)
        assert within(x["mixed"]["ratio"]), (name, x["mixed"])


# --- AC-04 ---

CHANGES = [("PATCH", 30), ("PATCH", 5), ("PUT", 10)]
SETTLE = 12  # 바꾼 뒤 다음 변경까지 (s)
# 하한을 보는 창: Succeeded 뒤 1~5 s에 시작하는 1초 창들의 중앙값. 한도를 올리면 흐름이 새 한도까지 오르는 데
# 1 s 안팎 걸리고(러너에서 첫 창이 30의 0.880), 공유 러너에서는 한 창이 떨어지기도 한다(FR-11 검증 1회차 AC-01).
# 5 s에서 끊는 것은 전의 2 s 창과 같은 이유다: WSL의 30 MiB/s 쓰기는 몇 초 뒤 서버 쪽에서 약 12 MiB/s로 떨어질 때가
# 있다(+6.5 s부터 본 실행이 있다, 제한기 원인이 아니다). 상한은 전처럼 Succeeded 뒤 2 s의 모든 창에 건다
SETTLED = (1, 5)


def test_ac04_limit_changes_during_io(agent, api, clients):
    api()
    create_account(ACCT)
    create_pool(ACCT, "uc", 40 * TIB, "Ultra", qos_type="Manual")
    c = clients()
    results = {}
    for name, protocols, vers, rw in (("w41", ["NFSv4.1"], "4.1", "write"), ("r3", None, "3", "read")):
        tok, size = token(f"d4{name}"), 2 * GIB
        *_, v = make(name, tok, "uc", size, protocols, throughputMibps=10)
        fsid = fsid_of(v)
        c.mount(mount_ip(v), tok, vers, f"/{name}")
        assert fio(c, "write", f"/{name}/f", 150)["error"] == 0  # 시간 기반 I/O가 늘리지 않을 파일
        drop_caches(c)
        mounts_before = mounts(c)
        s = Sampler(fsid)
        s.start()
        t_start = time.monotonic()  # 창 시각과 같은 시계 (Sampler)
        wait = in_background(fio, c, rw, f"/{name}/f", 150, runtime=12 + len(CHANGES) * (SETTLE + 4) + 10,
                             timeout=300)
        time.sleep(12)
        changes = []
        for how, mibps in CHANGES:
            if how == "PATCH":
                r = patch_volume(name, "uc", {"throughputMibps": mibps})
            else:
                r = call("PUT", vol_url(ACCT, "uc", name), vol_body(tok, size, protocols, throughputMibps=mibps))
            assert r.status in (200, 202), r.raw
            _, final, seen = fast_poll(r.headers["azure-asyncoperation"])  # 돌려주는 시각은 벽시계다
            t_ok = time.monotonic()  # Succeeded를 본 직후
            changes.append({"how": how, "mibps": mibps, "status": r.status,
                            "state": r.json()["properties"]["provisioningState"], "seen": seen,
                            "final": final["status"], "action": final["properties"]["action"], "t_ok": t_ok})
            time.sleep(SETTLE)
        t_last = time.monotonic()
        io = wait()
        windows = s.stop()
        active = [w for w in windows if t_start + 3 <= w[0] <= t_last - 1]
        previous = 10  # 만들 때의 한도
        for ch in changes:
            ch["previous"], previous = previous, ch["mibps"]
            ch["windows_2s"] = [w for w in windows if ch["t_ok"] <= w[0] <= ch["t_ok"] + 2]
            settled = [d for t, d in windows if ch["t_ok"] + SETTLED[0] <= t <= ch["t_ok"] + SETTLED[1]]
            ch["settled_median"] = statistics.median(settled) if settled else None
            ch["settled_ratio"] = None if not settled else round(ch["settled_median"] / ch["mibps"], 4)
        results[name] = {"rw": rw, "vers": vers, "changes": changes, "fio": io, "lowest_active_window": min(
            active, key=lambda w: w[1]), "remounted": mounts(c) != mounts_before, "tc_end": tc_state(fsid),
            "windows": windows}
        note("AC-04", volume=name, **results[name])
    c.remove()
    for name in results:
        delete_volume(name, pool="uc")
    for name, x in results.items():
        assert x["fio"]["error"] == 0 and not x["remounted"], (name, x["fio"])
        assert x["lowest_active_window"][1] >= 0.5 * min(m for _, m in CHANGES), (name, x["lowest_active_window"])
        for ch in x["changes"]:
            want = (202, "Patching", "PATCH") if ch["how"] == "PATCH" else (200, "Updating", "UPDATE")
            assert (ch["status"], ch["state"], ch["action"]) == want and ch["final"] == "Succeeded", (name, ch)
            # 상한: Succeeded 뒤 2 s의 창이 모두 새 한도의 101% 이하다. 내린 경우는 이것으로 곧바로 바뀐 것도 보인다
            assert ch["windows_2s"] and all(w[1] <= ch["mibps"] * HIGH for w in ch["windows_2s"]), (name, ch)
            # 올린 경우 곧바로 바뀐 것: 첫 창이 이미 옛 한도의 101%를 넘는다
            assert ch["mibps"] < ch["previous"] or ch["windows_2s"][0][1] > ch["previous"] * HIGH, (name, ch)
            # 하한: 1~5 s 창의 중앙값이 새 한도의 90~101%다 (SETTLED)
            assert ch["settled_ratio"] is not None and within(ch["settled_ratio"]), (name, ch)
        assert matches(x["tc_end"], 10), (name, x["tc_end"])


# --- AC-05 ---


def test_ac05_unlimited_volume_next_to_a_limited_one(agent, api, clients):
    """A(10)와 B(4,500)를 같은 클라이언트가 함께 읽는다. B는 서버 캐시에서 읽어 디스크 쓰기를 만들지 않는다
    (4,500 MiB/s 쓰기를 6회 돌리면 수십 GB를 쓴다)."""
    api()
    create_account(ACCT)
    create_pool(ACCT, "ub", 40 * TIB, "Ultra", qos_type="Manual")
    ta, tb = token("d5a"), token("d5b")
    *_, a = make("va", ta, "ub", GIB, throughputMibps=10)
    *_, b = make("vb", tb, "ub", 4 * GIB, throughputMibps=4500)
    c = clients()
    c.mount(mount_ip(a), ta, "3", "/a")
    c.mount(mount_ip(b), tb, "3", "/b")
    tc = {"a": tc_state(fsid_of(a)), "b": tc_state(fsid_of(b))}
    assert fio(c, "write", "/a/f", 150)["error"] == 0
    alone = measure(c, "read", "/a/f", 10)
    assert fio(c, "write", "/b/f", 1024)["error"] == 0
    together = []
    for _ in range(RUNS + 1):
        drop_caches(c)
        wait_b = in_background(fio, c, "read", "/b/f", 1024, runtime=SECONDS + 4, timeout=300)
        time.sleep(1)
        ra = fio(c, "read", "/a/f", 150)
        rb = wait_b()
        assert ra["error"] == 0 and rb["error"] == 0, (ra, rb)
        together.append({"a": ra["read"], "b": rb["read"]})
    a_med = statistics.median(x["a"] for x in together[1:])
    b_med = statistics.median(x["b"] for x in together[1:])
    note("AC-05", tc=tc, alone=alone, together=together, a_median=a_med, b_median=b_med,
         a_difference=round(a_med - alone["median"], 3))
    c.remove()
    delete_volume("va", pool="ub")
    delete_volume("vb", pool="ub")
    assert matches(tc["a"], 10) and matches(tc["b"], 4500), tc
    assert within(alone["ratio"]) and within(a_med / 10), (alone, a_med)
    assert b_med >= 10 * a_med, (a_med, b_med)
    assert abs(a_med - alone["median"]) <= band(10), (alone, a_med)


# --- AC-06 ---


def timed(c, script: str) -> dict:
    t0 = time.monotonic()
    r = c.run(script, timeout=300)
    return {"rc": r.returncode, "seconds": round(time.monotonic() - t0, 3), "stderr": r.stderr[-300:]}


def mount_stats(c, mp: str) -> dict:
    """/proc/self/mountstats의 그 마운트: xprt 줄과 쓰인 연산 줄 (연산 줄의 셋째 값이 timeouts)."""
    section, rows = None, {}
    for line in c.run("cat /proc/self/mountstats").stdout.splitlines():
        if line.startswith("device "):
            section = f" mounted on {mp} " in line
            continue
        if not section:
            continue
        s = line.strip()
        if s.startswith("xprt:"):
            rows["xprt"] = s
        elif ":" in s and s.split(":")[0].isupper():
            op, _, nums = s.partition(":")
            values = nums.split()
            if values and values[0].isdigit() and int(values[0]) > 0:
                rows[op] = {"ops": int(values[0]), "trans": int(values[1]), "timeouts": int(values[2])}
    return rows


def nfs_dmesg() -> list[str]:
    return [line for line in sh("dmesg").stdout.splitlines() if "nfs" in line.lower() or "rpc" in line.lower()]


def test_ac06_small_auto_limit_keeps_small_io_working(agent, api, clients):
    api()
    create_account(ACCT)
    create_pool(ACCT, "up", 4 * TIB, "Premium")  # Auto: 1 GiB = 0.062
    c, other = clients(), clients()
    results = {}
    for name, protocols, vers in (("s3", None, "3"), ("s41", ["NFSv4.1"], "4.1")):
        tok = token(f"d6{name}")
        *_, v = make(name, tok, "up", GIB, protocols)
        mp = f"/{name}"
        dmesg_before = nfs_dmesg()
        c.mount(mount_ip(v), tok, vers, mp)
        other.mount(mount_ip(v), tok, vers, mp)
        small = timed(c, f"echo hello > {mp}/small && cat {mp}/small && ls -la {mp}")
        # 큰 직접 쓰기: 64 KiB 한 개씩(64 KiB가 한도에서 약 1 s). 1 MiB × 16은 대기열을 비우는 데만 4분 넘게 걸린다
        wait = in_background(fio, c, "write", f"{mp}/big", 4, runtime=30, bs="64k", iodepth=1, timeout=300)
        time.sleep(5)
        same, diff = [], []
        for i in range(3):
            same.append(timed(c, f"ls -la {mp} && stat {mp}/small && cat {mp}/small"))
            diff.append(timed(other, f"ls -la {mp} && echo o{i} > {mp}/o && cat {mp}/o"))
            time.sleep(2)
        big = wait()
        after = timed(c, f"ls -la {mp} && cat {mp}/small")
        results[name] = {"vers": vers, "actual": v["properties"]["actualThroughputMibps"],
                         "tc": tc_state(fsid_of(v)), "small": small, "same_connection": same,
                         "other_connection": diff, "after": after, "big_write": big,
                         "mountstats": mount_stats(c, mp), "dmesg_new": nfs_dmesg()[len(dmesg_before):]}
        note("AC-06", volume=name, **results[name])
    c.remove()
    other.remove()
    for name in results:
        delete_volume(name, pool="up")
    for name, x in results.items():
        assert x["actual"] == 0.062 and matches(x["tc"], 0.062), (name, x["tc"])
        ops = [x["small"], *x["same_connection"], *x["other_connection"], x["after"]]
        assert all(o["rc"] == 0 for o in ops), (name, ops)
        assert x["big_write"]["error"] == 0 and x["big_write"]["write"] <= 0.062 * HIGH, (name, x["big_write"])


# --- AC-07 ---


def resumed(windows: list, after: float, mibps: float) -> float | None:
    """after 뒤 처음으로 한도의 절반 이상이 흐른 1초 창의 시작 시각."""
    return next((t for t, d in windows if t >= after and d >= 0.5 * mibps), None)


def through_step(c, fsid: str, mibps: float, step, runtime: int) -> dict:
    """시간 기반 쓰기를 돌리는 중에 step()을 하고, 끝난 뒤 다시 흐르기 시작한 때부터 15 s 동안의 1초 창을 본다.
    반환: 단계 시각, 다시 흐른 때까지의 지연, 측정 창의 중앙값·비율, 한도를 넘은 창, 표본이 없던 구간, fio 결과."""
    s = Sampler(fsid)
    s.start()
    wait = in_background(fio, c, "write", "/m/f", round(mibps * SECONDS), runtime=runtime, timeout=runtime + 300)
    time.sleep(6)
    t_step = time.monotonic()  # 창 시각과 같은 시계 (Sampler)
    detail = step()
    t_done = time.monotonic()
    io = wait()
    windows = s.stop()
    t_resume = resumed(windows, t_done, mibps)
    span = [d for t, d in windows if t_resume is not None and t_resume + 1 <= t <= t_resume + 16]
    median = statistics.median(span) if span else None
    return {"detail": detail, "step_s": round(t_done - t_step, 2),
            "resume_delay_s": None if t_resume is None else round(t_resume - t_done, 2), "windows_measured": len(span),
            "median": median, "ratio": None if median is None else round(median / mibps, 4),
            "over_limit": [w for w in windows if w[1] > mibps * HIGH], "gaps": s.gaps(), "fio": io,
            "tc": tc_state(fsid)}


def test_ac07_limit_survives_lifecycle(agent, api, clients):
    api()
    create_account(ACCT)
    create_pool(ACCT, "ul", 2 * TIB, "Ultra", qos_type="Manual")
    create_pool(ACCT, "ula", TIB, "Ultra")  # Auto
    tok, mibps = token("d7"), 10
    *_, v = make("l1", tok, "ul", GIB, throughputMibps=mibps)
    fsid = fsid_of(v)
    c = clients()
    c.mount(mount_ip(v), tok, "3")
    assert fio(c, "write", "/m/f", mibps * SECONDS)["error"] == 0
    snap, _ = create_snapshot("l1", "s1", pool="ul")
    steps = {}

    def restart_agent():
        agent.stop()
        agent.start()
        return {"pid": instance_pid(fsid)}

    def stop_instance_then_restart_agent():
        before = instance_pid(fsid)
        rc = sh("docker", "stop", instance_name(fsid)).returncode
        agent.stop()
        agent.start()
        return {"docker_stop_rc": rc, "pid_before": before, "pid_after": instance_pid(fsid)}

    def remove_instance_then_put():
        rc = sh("docker", "rm", "-f", instance_name(fsid)).returncode
        r = call("PUT", vol_url(ACCT, "ul", "l1"), vol_body(tok, GIB, throughputMibps=mibps))
        final, seen = poll(r.headers["azure-asyncoperation"], 120)
        return {"docker_rm_rc": rc, "put": r.status, "seen": seen, "final": final["status"],
                "pid_after": instance_pid(fsid)}

    def revert_to_s1():
        r = post_revert("l1", snap["id"], pool="ul")
        final, seen = poll(r.headers["azure-asyncoperation"], 120)
        return {"post": r.status, "seen": seen, "final": final["status"]}

    # runtime은 단계 + 클라이언트 재연결(TCP 재연결 backoff가 수십 초까지 는다) + 측정 16 s를 덮는다
    for label, step, runtime in (("a agent restart", restart_agent, 50),
                                 ("b docker stop + agent restart", stop_instance_then_restart_agent, 150),
                                 ("c docker rm + re-PUT", remove_instance_then_put, 150),
                                 ("d revert while writing", revert_to_s1, 50)):
        steps[label] = through_step(c, fsid, mibps, step, runtime)
        note("AC-07", step=label, **{k: x for k, x in steps[label].items()})

    # (e) 한도 건 볼륨의 스냅샷에서 새 볼륨: Manual 풀에 20, Auto 풀(1 GiB Ultra = 0.125)
    t2, t3 = token("d7r"), token("d7ra")
    _, _, seen2, r2 = restore_volume("l2", t2, snap["id"], pool="ul", throughputMibps=20)
    c2 = clients()
    c2.mount(mount_ip(r2), t2, "3")
    e_manual = {"values": limits("l2", "ul"), "tc": tc_state(fsid_of(r2)),
                "write": measure(c2, "write", "/m/f", 20)}  # 스냅샷에 있는 f(150 MiB)를 늘리는 첫 회는 버린다
    _, _, seen3, r3 = restore_volume("l3", t3, snap["id"], pool="ula")
    e_auto = {"values": limits("l3", "ula"), "tc": tc_state(fsid_of(r3))}
    note("AC-07", step="e restore", manual=e_manual, auto=e_auto)
    c.remove()
    c2.remove()
    for name, pool in (("l2", "ul"), ("l3", "ula"), ("l1", "ul")):
        delete_volume(name, pool=pool)

    for label, x in steps.items():
        assert x["fio"]["error"] == 0, (label, x["fio"])
        assert x["detail"].get("final", "Succeeded") == "Succeeded", (label, x["detail"])
        assert matches(x["tc"], mibps), (label, x["tc"])
        assert x["ratio"] is not None and within(x["ratio"]), (label, x)
        assert not x["over_limit"], (label, x["over_limit"])
    assert e_manual["values"]["throughputMibps"] == 20 and matches(e_manual["tc"], 20), e_manual
    assert within(e_manual["write"]["ratio"]), e_manual
    assert e_auto["values"] == {"throughputMibps": None, "actualThroughputMibps": 0.125,
                                "provisioningState": "Succeeded"} and matches(e_auto["tc"], 0.125), e_auto


# --- AC-09 ---


def test_ac09_auto_to_manual_keeps_the_limit(agent, api, clients):
    api()
    create_account(ACCT)
    create_pool(ACCT, "ux", TIB, "Ultra")  # Auto
    tok = token("d9")
    *_, big = make("x40", tok, "ux", 40 * GIB)  # 5.0
    *_, small = make("x1", token("d9s"), "ux", GIB)  # 0.125
    c = clients()
    c.mount(mount_ip(big), tok, "3")

    def state():
        return {"x40": limits("x40", "ux"), "x1": limits("x1", "ux"),
                "utilized": pool_props("ux")["utilizedThroughputMibps"],
                "tc": {"x40": tc_state(fsid_of(big)), "x1": tc_state(fsid_of(small))}}

    before = state()
    w_before = measure(c, "write", "/m/f", 5.0)
    r = call("PATCH", pool_url(ACCT, "ux"), {"properties": {"qosType": "Manual"}})
    assert r.status == 202, r.raw
    final, seen = poll(r.headers["azure-asyncoperation"], 60)
    after = state()
    w_after = measure(c, "write", "/m/f", 5.0)
    p = patch_volume("x40", "ux", {"throughputMibps": 20})
    assert p.status == 202, p.raw
    final_p, seen_p = poll(p.headers["azure-asyncoperation"], 60)
    changed = {"values": limits("x40", "ux"), "tc": tc_state(fsid_of(big)),
               "write": measure(c, "write", "/m/f", 20)}  # 앞의 측정이 만든 f(75 MiB)를 늘리는 첫 회는 버린다
    note("AC-09", before=before, write_before=w_before, pool_patch=r.json()["properties"], seen=seen,
         final=final["status"], after=after, write_after=w_after, volume_patch_seen=seen_p,
         volume_patch_final=final_p["status"], changed=changed)
    c.remove()
    delete_volume("x40", pool="ux")
    delete_volume("x1", pool="ux")
    assert before["x40"]["throughputMibps"] is None and before["x40"]["actualThroughputMibps"] == 5.0
    assert before["x1"]["throughputMibps"] is None and before["x1"]["actualThroughputMibps"] == 0.125
    assert r.json()["properties"]["provisioningState"] == "Patching" and final["status"] == "Succeeded"
    assert after["x40"]["throughputMibps"] == after["x40"]["actualThroughputMibps"] == 5.0
    assert after["x1"]["throughputMibps"] == after["x1"]["actualThroughputMibps"] == 0.125
    assert before["utilized"] == after["utilized"] == 5.125
    assert all(matches(st["tc"]["x40"], 5.0) and matches(st["tc"]["x1"], 0.125) for st in (before, after))
    assert within(w_before["ratio"]) and within(w_after["ratio"]), (w_before, w_after)
    assert abs(w_after["median"] - w_before["median"]) <= band(5.0), (w_before, w_after)
    assert final_p["status"] == "Succeeded" and changed["values"]["throughputMibps"] == 20
    assert matches(changed["tc"], 20) and within(changed["write"]["ratio"]), changed
