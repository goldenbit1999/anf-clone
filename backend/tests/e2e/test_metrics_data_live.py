"""메트릭 e2e: storage agent `/metrics`와 Prometheus가 클라이언트 I/O를 보인다 (메트릭 설계 §5, FR-12).

- AC-03 사용량, AC-04 처리량(볼륨·방향 분리), AC-05 IOPS: 볼륨 둘(v3, v4.1)에 쓰고 읽을 때 agent 값과 fio·df
- AC-06 Manual 한도 볼륨의 포화 쓰기를 Prometheus `rate()`로 보면 한도 gauge의 90~101%이고 PATCH를 따라간다.
  AC-07 Prometheus 컨테이너(scripts/run-prometheus.sh)가 두 대상을 긁고, 부하를 건 뒤 15 s 안에 rate가 0보다 커진다
- AC-09 인스턴스가 내려간 동안·다시 뜬 뒤(카운터 리셋)·볼륨을 지운 뒤의 계열
- AC-10 스냅샷 뒤 덮어쓰기: aggregate 사용량만 늘고 볼륨 사용량은 그대로
- AC-11 1초 스크레이프가 한도 측정과 볼륨 생성 job을 방해하지 않고, 볼륨 둘의 스크레이프가 0.5 s 안이다

AC-01·AC-02(anf-api 요청·작업 지표)는 계약 테스트(test_arm_app.py)가 본다. 여기서는 Prometheus가 실제 anf-api에서
작업 지표를 긁는 것만 본다(AC-07). AC-08(브라우저)은 verifier가, AC-12·13은 CI와 프런트엔드 명령이 본다.
이 파일은 약 10분 걸린다(CI rest 조각에 들어간다).

실행 (WSL, root, 저장소 루트):
    wsl -d Ubuntu -u root -e bash -c 'cd /mnt/c/<repo> && PYTHONDONTWRITEBYTECODE=1 \
        ANF_E2E_API_URL=http://127.0.0.1:8080 /home/<user>/.venvs/anf-clone/bin/python -m pytest \
        -p no:cacheprovider backend/tests/e2e/test_metrics_data_live.py -v -s'
"""

import statistics
import time

import pytest

import live_api
from live_api import call, poll
from dataplane_live import (
    ACCT, GIB, POLL, POOL, SKIP_UNLESS_ROOT, create_volume, delete_volume, fsid_of, instance_name, mount_ip, note,
    out, setup_pool, sh, token, vol_body, vol_url,
)
from metrics_live import (
    MIB, AgentScraper, agent_samples, client_df, delta, fio_job, instant, names_of, parse, query_range,
    run_prometheus, scalar, scrape_agent, targets_up, value, wait_until,
)
from revert_live import fast_poll
from snapshot_live import create_snapshot, delete_snapshot
from throughput_live import in_background, make, measure, patch_volume, within

# 데이터를 쓰므로 Manual 풀과 DATA_MIBPS(64) 한도로 볼륨을 만든다 (처리량 설계 결정 17)
pytestmark = [pytest.mark.e2e, pytest.mark.dataplane, live_api.SKIP_UNLESS_LIVE, SKIP_UNLESS_ROOT,
              pytest.mark.usefixtures("manual_data")]

SIZE = "256M"
WRITTEN = 256 * MIB
R, W = "anf_volume_read_bytes_total", "anf_volume_write_bytes_total"
REQUESTS, OPS = "anf_volume_nfs_requests_total", "anf_volume_nfs_operations_total"
USED, LIMIT = "anf_volume_used_bytes", "anf_volume_throughput_limit_bytes_per_second"
USAGE_ONLY = ["anf_volume_inodes", "anf_volume_inodes_used", "anf_volume_size_bytes", "anf_volume_snapshots",
              LIMIT, USED]  # 인스턴스가 없을 때 남는 계열 (설계 §2.1)


def close(a: float, b: float, tolerance: float) -> bool:
    return abs(a - b) <= tolerance * abs(b)


def value_of(samples: dict, name: str) -> float | None:
    """라벨 없는 계열(aggregate, 수집기 자신)의 값."""
    return samples.get((name, ()))


@pytest.fixture(scope="module")
def prometheus(agent):
    """설계 §6: Prometheus 컨테이너는 테스트가 띄우고 지운다. 실패해도 지운다."""
    r = run_prometheus()
    assert r.returncode == 0, out(r)
    note("prometheus", stdout=r.stdout.strip())
    yield
    r = run_prometheus("stop")
    note("prometheus stop", **out(r))


def both_up() -> dict | None:
    up = targets_up()
    return up if up.get("anf-api") == "1" and up.get("storage-agent") == "1" else None


# --- AC-03, AC-04, AC-05 ---


def test_ac03_ac04_ac05_usage_throughput_and_iops_per_volume(agent, api, clients):
    api()
    setup_pool()
    ta, tb = token("m1a"), token("m1b")
    a = create_volume("ma", ta)  # NFSv3
    b = create_volume("mb", tb, protocols=["NFSv4.1"])
    c = clients()
    c.mount(mount_ip(a), ta, "3", "/a")
    c.mount(mount_ip(b), tb, "4.1", "/b")

    steps = {}
    for tok, other, mp in ((ta, tb, "/a"), (tb, ta, "/b")):
        s0, df0 = agent_samples(), client_df(c, mp)
        wr = fio_job(c, f"--rw=write --bs=1M --size={SIZE} --iodepth=16 --filename={mp}/f")
        s1, df1 = agent_samples(), client_df(c, mp)
        rd = fio_job(c, f"--rw=read --bs=1M --size={SIZE} --iodepth=16 --filename={mp}/f")
        s2 = agent_samples()
        steps[tok] = {
            "fio_write": wr, "fio_read": rd, "df_before": df0, "df_after": df1,
            "write": {"w": delta(s0, s1, W, tok), "r": delta(s0, s1, R, tok),
                      "other_w": delta(s0, s1, W, other), "other_r": delta(s0, s1, R, other)},
            "read": {"r": delta(s1, s2, R, tok), "w": delta(s1, s2, W, tok)},
            "used": [value(s0, USED, tok), value(s1, USED, tok)],
            "agent_after_write": {k: value(s1, f"anf_volume_{k}", tok)
                                  for k in ("size_bytes", "used_bytes", "inodes", "inodes_used", "snapshots")},
        }
        note("AC-03/04", volume=tok, **steps[tok])

    # AC-05: v4.1은 READ 연산 수, v3는 요청 수. v3는 iodepth 1로 건다: rpc 줄은 동시 증가를 잃는다(S8 Q3, 설계 §7)
    s0 = agent_samples()
    ops41 = fio_job(c, f"--rw=randread --bs=4k --size={SIZE} --iodepth=8 --time_based --runtime=5 --filename=/b/f")
    s1 = agent_samples()
    ops3 = fio_job(c, f"--rw=randread --bs=4k --size={SIZE} --iodepth=1 --time_based --runtime=5 --filename=/a/f")
    s2 = agent_samples()
    iops = {"v41": {"fio_ios": ops41["read"]["ios"], "read_ops": delta(s0, s1, OPS, tb, op="read"),
                    "requests": delta(s0, s1, REQUESTS, tb), "error": ops41["error"]},
            "v3": {"fio_ios": ops3["read"]["ios"], "requests": delta(s1, s2, REQUESTS, ta),
                   "op_series": [n for n, key in s2 if n == OPS and dict(key).get("creation_token") == ta],
                   "error": ops3["error"]}}
    note("AC-05", **iops)
    c.remove()
    delete_volume("ma")
    delete_volume("mb")

    for tok, x in steps.items():
        assert x["fio_write"]["error"] == 0 and x["fio_read"]["error"] == 0, x
        # AC-04: 쓴 볼륨의 쓰기 카운터가 fio 바이트 ± 1%, 다른 볼륨은 0. 읽기만 하면 쓰기 카운터는 늘지 않는다
        assert close(x["write"]["w"], x["fio_write"]["write"]["bytes"], 0.01), (tok, x)
        assert x["write"]["other_w"] == 0 and x["write"]["other_r"] == 0, (tok, x)
        assert close(x["read"]["r"], x["fio_read"]["read"]["bytes"], 0.01), (tok, x)
        assert x["read"]["w"] == 0, (tok, x)
        # AC-03: 256 MiB를 쓰면 used가 268,435,456 ± 1% 늘고, 크기·used·inode가 클라이언트 df와 맞는다
        assert close(x["used"][1] - x["used"][0], WRITTEN, 0.01), (tok, x)
        agent_after, df1 = x["agent_after_write"], x["df_after"]
        assert close(agent_after["used_bytes"], df1["used"], 0.01), (tok, x)
        assert close(agent_after["size_bytes"], df1["size"], 0.01), (tok, x)
        assert (agent_after["inodes"], agent_after["inodes_used"]) == (df1["inodes"], df1["inodes_used"]), (tok, x)
        assert agent_after["snapshots"] == 0, (tok, x)
    assert iops["v41"]["error"] == 0 and close(iops["v41"]["read_ops"], iops["v41"]["fio_ios"], 0.02), iops
    assert iops["v3"]["error"] == 0 and iops["v3"]["requests"] >= iops["v3"]["fio_ios"] > 0, iops
    assert iops["v3"]["op_series"] == [], iops


# --- AC-06, AC-07 ---

PATCH_AT = 45  # 부하 시작 뒤 PATCH까지 (s)
RUNTIME = 100  # 부하 길이 (s)
STEADY = 25  # 한도가 정해진 뒤 20 s 창이 모두 그 한도 안에 들도록 기다리는 시간 (s)


def test_ac06_ac07_prometheus_shows_the_load_and_follows_the_limit(agent, api, clients, prometheus):
    api()
    setup_pool()
    tok = token("m2")
    *_, v = make("mc", tok, POOL, GIB, ["NFSv4.1"], throughputMibps=10)
    up, up_after = wait_until(both_up, 30, what="anf-api and storage-agent up")
    sel = f'{{creation_token="{tok}"}}'
    rate_w = f"rate({W}{sel}[20s])"
    c = clients()
    c.mount(mount_ip(v), tok, "4.1", "/c")
    # rate()는 창 안에 표본이 둘 있어야 값이 나온다. 부하 전의 값(0)을 먼저 본다
    wait_until(lambda: scalar(rate_w) is not None, 60, what="write rate series in Prometheus")
    idle = scalar(rate_w)
    t_load = time.time()
    wait_io = in_background(fio_job, c, f"--rw=write --bs=1M --size=64M --iodepth=16 --time_based "
                                        f"--runtime={RUNTIME} --filename=/c/f", timeout=RUNTIME + 120)
    first_rate, to_positive = wait_until(lambda: scalar(rate_w), 60, interval=0.25, what="write rate > 0")
    time.sleep(max(0.0, t_load + PATCH_AT - time.time()))
    t_patch = time.time()
    r = patch_volume("mc", POOL, {"throughputMibps": 20})
    assert r.status == 202, r.raw
    _, final, seen = fast_poll(r.headers["azure-asyncoperation"])
    t_patched = time.time()
    gauge_after_patch = value(agent_samples(), LIMIT, tok)
    io = wait_io()
    t_end = time.time()
    time.sleep(6)  # 마지막 표본까지 긁히게

    rate_sum = f"rate({R}{sel}[20s]) + rate({W}{sel}[20s])"
    phases = []
    for mibps, start, end in ((10, t_load + STEADY, t_patch), (20, t_patched + STEADY, t_end - 1)):
        rates = [float(x[1]) for x in query_range(rate_sum, start, end)[0]["values"]]
        gauges = sorted({float(x[1]) for x in query_range(f"{LIMIT}{sel}", start, end)[0]["values"]})
        phases.append({"mibps": mibps, "window": [round(start - t_load, 1), round(end - t_load, 1)],
                       "rates_mibps": [round(x / MIB, 3) for x in rates], "gauges": gauges,
                       "ratio": round(statistics.median(rates) / gauges[-1], 4)})
    series = query_range(f"{W}{sel}", t_load - 30, t_end)
    api_ops = scalar('sum(anf_api_operations_total{resource_type="volumes",result="Succeeded"})')
    api_routes = sorted({x["metric"]["route"] for x in instant("anf_api_http_requests_total")})
    evidence = {"up": up, "up_after_s": round(up_after, 1), "idle_rate": idle, "first_rate": first_rate,
                "rate_positive_after_s": round(to_positive, 2), "patch": {"seen": seen, "final": final["status"]},
                "gauge_after_patch": gauge_after_patch, "fio": io, "phases": phases, "series": len(series),
                "api_volume_ops": api_ops, "api_routes": api_routes}
    note("AC-06/07", **evidence)
    c.remove()
    delete_volume("mc")

    # AC-07: 두 대상이 up, 쿼리 API가 볼륨 계열을 돌려주고, 부하 뒤 15 s 안에 rate > 0. anf-api의 작업 지표도 긁힌다
    assert up == {"anf-api": "1", "storage-agent": "1"}, evidence
    assert idle == 0 and to_positive <= 15, evidence
    assert len(series) == 1, evidence
    assert api_ops is not None and api_ops >= 2, evidence  # 볼륨 create와 patch
    assert any("/volumes/{volume_name}" in route for route in api_routes), evidence
    # AC-06: 한도 gauge = X × 1,048,576, 안정 구간 rate(read+write)의 중앙값이 그 90~101%. PATCH를 따라 바뀐다
    assert io["error"] == 0 and final["status"] == "Succeeded", evidence
    assert gauge_after_patch == 20 * MIB, evidence
    for p in phases:
        assert p["gauges"] == [p["mibps"] * MIB], evidence
        assert within(p["ratio"]), evidence


# --- AC-09 ---


def test_ac09_series_across_instance_restart_and_volume_delete(agent, api, clients, prometheus):
    api()
    setup_pool()
    td, te = token("m3d"), token("m3e")
    d = create_volume("md", td)  # NFSv3: 다시 뜰 때 NFSv4 유예 기간을 기다리지 않는다
    e = create_volume("me", te)
    fd, fe = fsid_of(d), fsid_of(e)
    sel = f'{{creation_token="{td}"}}'
    c = clients()
    c.mount(mount_ip(d), td, "3", "/d")
    assert fio_job(c, "--rw=write --bs=1M --size=64M --iodepth=16 --filename=/d/f")["error"] == 0
    before = agent_samples()
    wait_until(lambda: scalar(f"{W}{sel}") == value(before, W, td), 30, what="Prometheus has the 64 MiB")
    t0 = time.time()

    # 인스턴스가 내려간 동안: /metrics는 200이고 다른 볼륨의 값이 나온다. 내려간 볼륨은 사용량 계열만 남는다
    assert c.run("umount /d").returncode == 0
    assert sh("docker", "rm", "-f", instance_name(fd)).returncode == 0
    status, body, _ = scrape_agent()
    down = parse(body) if status == 200 else {}
    # 같은 PUT이 인스턴스를 다시 띄운다 (Updating)
    r = call("PUT", vol_url(ACCT, POOL, "md"), vol_body(td, GIB))
    assert r.status == 200, r.raw
    final, seen = poll(r.headers["azure-asyncoperation"], POLL)
    restarted = agent_samples()
    c.mount(mount_ip(d), td, "3", "/d")
    assert fio_job(c, "--rw=write --bs=1M --size=32M --iodepth=16 --filename=/d/g")["error"] == 0
    after = agent_samples()
    wait_until(lambda: scalar(f"{W}{sel}") == value(after, W, td), 30, what="Prometheus has the restarted counter")
    t1 = time.time()
    raw = query_range(f"{W}{sel}", t0 - 30, t1)
    rates = query_range(f"rate({W}{sel}[20s])", t0 - 30, t1)

    # 볼륨을 지우면 다음 스크레이프부터 그 볼륨의 계열이 없다. Prometheus에서도 사라진다(stale)
    c.remove()
    delete_volume("me")
    gone = agent_samples()
    _, stale_after = wait_until(lambda: instant(f'{USED}{{creation_token="{te}"}}') == [], 30,
                                what="deleted volume gone from Prometheus")
    delete_volume("md")

    evidence = {
        "down_status": status, "down_d": names_of(down, fd), "down_e": names_of(down, fe),
        "errors": [value_of(before, "anf_agent_scrape_errors_total"), value_of(down, "anf_agent_scrape_errors_total")],
        "reput": {"seen": seen, "final": final["status"]},
        "write": {"before": value(before, W, td), "restarted": value(restarted, W, td), "after": value(after, W, td)},
        "raw_series": len(raw), "raw_values": [round(float(x[1]) / MIB, 2) for s in raw for x in s["values"]],
        "rates_min": min(float(x[1]) for s in rates for x in s["values"]),
        "gone_e": names_of(gone, fe), "stale_after_s": round(stale_after, 1),
    }
    note("AC-09", **evidence)
    assert status == 200, evidence
    assert evidence["down_d"] == USAGE_ONLY, evidence
    assert {R, W, REQUESTS, USED} <= set(evidence["down_e"]), evidence
    assert evidence["errors"][1] == evidence["errors"][0], evidence  # 내려간 인스턴스는 수집 오류가 아니다
    assert final["status"] == "Succeeded", evidence
    assert evidence["write"] == {"before": 64 * MIB, "restarted": 0, "after": 32 * MIB}, evidence
    # 같은 라벨의 계열 하나가 이어지고(64 MiB → 리셋 → 32 MiB), rate()는 음수가 되지 않는다
    assert evidence["raw_series"] == 1, evidence
    assert evidence["rates_min"] >= 0, evidence
    assert evidence["gone_e"] == [], evidence


# --- AC-10 (AC-03의 스냅샷 수) ---


def test_ac10_snapshot_overwrite_grows_the_aggregate_not_the_volume(agent, api, clients):
    api()
    setup_pool()
    tf = token("m4")
    f = create_volume("mf", tf)
    c = clients()
    c.mount(mount_ip(f), tf, "3", "/f")
    assert fio_job(c, f"--rw=write --bs=1M --size={SIZE} --iodepth=16 --filename=/f/f")["error"] == 0
    s0 = agent_samples()
    create_snapshot("mf", "s1")
    s1 = agent_samples()
    w = fio_job(c, f"--rw=write --bs=1M --size={SIZE} --iodepth=16 --filename=/f/f")  # 같은 파일을 덮어쓴다
    s2 = agent_samples()
    delete_snapshot("mf", "s1")
    s3 = agent_samples()
    c.remove()
    delete_volume("mf")

    agg = "anf_aggregate_data_used_bytes"
    evidence = {"snapshots": [value(s, "anf_volume_snapshots", tf) for s in (s0, s1, s2, s3)],
                "aggregate_growth": value_of(s2, agg) - value_of(s1, agg), "fio": w,
                "used": [value(s1, USED, tf), value(s2, USED, tf)],
                "aggregate": [value_of(s, agg) for s in (s0, s1, s2, s3)],
                "metadata": [value_of(s, "anf_aggregate_metadata_used_bytes") for s in (s0, s1, s2, s3)]}
    note("AC-10", **evidence)
    assert w["error"] == 0, evidence
    assert evidence["snapshots"] == [0, 1, 1, 0], evidence
    assert close(evidence["aggregate_growth"], w["write"]["bytes"], 0.10), evidence
    assert close(evidence["used"][1], evidence["used"][0], 0.01), evidence


# --- AC-11 ---


def test_ac11_one_second_scrapes_do_not_disturb_limits_or_jobs(agent, api, clients):
    api()
    setup_pool()
    tg, th = token("m5g"), token("m5h")
    *_, g = make("mg", tg, POOL, GIB, None, throughputMibps=10)
    c = clients()
    c.mount(mount_ip(g), tg, "3", "/g")
    scraper = AgentScraper(1.0)
    scraper.start()
    job0 = time.monotonic()
    r = call("PUT", vol_url(ACCT, POOL, "mh"), vol_body(th, GIB, ["NFSv4.1"]))  # 스크레이프 중 볼륨 생성 job
    assert r.status == 201, r.raw
    final, seen = poll(r.headers["azure-asyncoperation"], POLL)
    job1 = m0 = time.monotonic()
    limited = measure(c, "write", "/g/f", 10)  # 볼륨 둘(mg, mh)이 있는 동안
    m1 = time.monotonic()
    rows = scraper.stop()
    c.remove()
    delete_volume("mg")
    delete_volume("mh")

    during_job = [x for x in rows if job0 <= x[0] <= job1]
    during_measure = [x for x in rows if m0 <= x[0] <= m1]
    evidence = {"job": {"seen": seen, "final": final["status"], "seconds": round(job1 - job0, 1)},
                "scrapes": len(rows), "statuses": sorted({x[1] for x in rows}),
                "during_job": during_job, "measure": limited,
                "measure_scrapes": len(during_measure),
                "measure_scrape_max_s": max(x[2] for x in during_measure),
                "measure_scrape_median_s": statistics.median(x[2] for x in during_measure)}
    note("AC-11", **evidence)
    assert evidence["statuses"] == [200], evidence
    assert final["status"] == "Succeeded" and during_job, evidence
    assert within(limited["ratio"]), evidence
    assert evidence["measure_scrapes"] > 0 and evidence["measure_scrape_max_s"] < 0.5, evidence
