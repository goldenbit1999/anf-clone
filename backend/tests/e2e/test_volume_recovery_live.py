"""볼륨 e2e (3/3): 실패와 재시작 복구 (볼륨 설계 §8).

- AC-11 생성 실패(주입, agent 정지)는 Failed가 되고 예약이 남는다. 다시 PUT하면 회복한다
- AC-12 anf-api SIGKILL, job 단계별 agent SIGKILL, WSL 재시작 흉내 뒤 복구

실행 (WSL, root, 저장소 루트):
    wsl -d Ubuntu -u root -e bash -c 'cd /mnt/c/<repo> && PYTHONDONTWRITEBYTECODE=1 \
        ANF_E2E_API_URL=http://127.0.0.1:8080 /home/<user>/.venvs/anf-clone/bin/python -m pytest \
        -p no:cacheprovider backend/tests/e2e/test_volume_recovery_live.py -v -s'
볼륨 e2e 세 파일을 한 번에: 파일 대신 `-m dataplane backend/tests/e2e`.
"""

import time
from pathlib import Path

import pytest

import live_api
from live_api import TIB, call, poll
from dataplane_live import (
    ACCT, create_volume, dataplane, delete_volume, error_of, fsid_of, GIB, instance_ip, instance_name, lv_name,
    lvs_volumes, mount_ip, note, NS, one_shot, ops_for, out, POLL, POOL, setup_pool, sh, SKIP_UNLESS_ROOT,
    token, vol_body, vol_url, volume_state,
)

pytestmark = [pytest.mark.e2e, pytest.mark.dataplane, live_api.SKIP_UNLESS_LIVE, SKIP_UNLESS_ROOT]


# --- AC-11 ---


def test_ac11_injected_failure_keeps_reservation_then_put_recovers(agent, api):
    srv = api(faults={"volumes/create": {"fail": True}})
    db = srv.db_path
    setup_pool(TIB)
    tok = token("ac11a")
    before = dataplane()
    r = call("PUT", vol_url(ACCT, POOL, "v11"), vol_body(tok, GIB))
    assert r.status == 201
    final, seen = poll(r.headers["azure-asyncoperation"], POLL)
    state = call("GET", vol_url(ACCT, POOL, "v11")).json()["properties"]["provisioningState"]
    over = call("PUT", vol_url(ACCT, POOL, "v11big"), vol_body(token("ac11b"), TIB))  # 1 GiB 예약 + 1 TiB > 1 TiB
    note("AC-11 injected failure", seen=seen, final=final, volume_state=state, reservation_check=error_of(over),
         dataplane_unchanged=dataplane() == before)
    assert final["status"] == "Failed" and final["error"]["code"] == "InternalServerError" and final["error"]["message"]
    assert state == "Failed"
    assert error_of(over) == (400, "BadRequest", "Pool size too small for total volume size.")
    assert dataplane() == before

    srv.stop()
    api(db=db)
    u = call("PUT", vol_url(ACCT, POOL, "v11"), vol_body(tok, GIB))
    assert u.status == 200, u.raw
    assert u.json()["properties"]["provisioningState"] == "Updating"
    final, seen = poll(u.headers["azure-asyncoperation"], POLL)
    v = call("GET", vol_url(ACCT, POOL, "v11")).json()
    m = one_shot(mount_ip(v), tok, "3", "echo ok > /m/f && cat /m/f")
    note("AC-11 recovery PUT", status=u.status, seen=seen, final=final,
         state=v["properties"]["provisioningState"], mount=out(m))
    assert final["status"] == "Succeeded" and final["properties"]["action"] == "UPDATE"
    assert v["properties"]["provisioningState"] == "Succeeded"
    assert m.returncode == 0 and m.stdout == "ok\n"
    delete_volume("v11")


def test_ac11_agent_down_fails_after_retry_then_put_recovers(agent, api):
    srv = api()
    setup_pool()
    tok = token("ac11c")
    agent.stop()
    try:
        t0 = time.monotonic()
        r = call("PUT", vol_url(ACCT, POOL, "v11c"), vol_body(tok))
        assert r.status == 201
        final, seen = poll(r.headers["azure-asyncoperation"], 2 * POLL)
        elapsed = round(time.monotonic() - t0, 1)
        state = call("GET", vol_url(ACCT, POOL, "v11c")).json()["properties"]["provisioningState"]
        retries = srv.output().count("is unreachable")
        note("AC-11 agent down", elapsed_seconds=elapsed, seen=sorted(set(seen)), final=final, volume_state=state,
             unreachable_log_lines=retries)
        assert final["status"] == "Failed" and final["error"]["code"] == "InternalServerError"
        assert state == "Failed"
        assert 55 <= elapsed <= 90
        assert retries > 0
    finally:
        agent.start()
    u = call("PUT", vol_url(ACCT, POOL, "v11c"), vol_body(tok))
    assert u.status == 200 and u.json()["properties"]["provisioningState"] == "Updating"
    final, seen = poll(u.headers["azure-asyncoperation"], POLL)
    v = call("GET", vol_url(ACCT, POOL, "v11c")).json()
    m = one_shot(mount_ip(v), tok, "3", "echo ok > /m/f && cat /m/f")
    note("AC-11 agent back, PUT", seen=seen, final=final, mount=out(m))
    assert final["status"] == "Succeeded"
    assert m.returncode == 0 and m.stdout == "ok\n"
    delete_volume("v11c")


# --- AC-12 ---


def test_ac12a_anf_api_sigkill_during_create(agent, api):
    delay = 10
    srv = api(faults={"volumes/create": {"delaySeconds": delay}})
    db = srv.db_path
    setup_pool()
    tok = token("ac12a")
    r = call("PUT", vol_url(ACCT, POOL, "v12a"), vol_body(tok))
    assert r.status == 201
    rid, fsid = r.json()["id"], fsid_of(r.json())
    time.sleep(2)
    rc = srv.sigkill()
    at_kill = [(o["action"], o["status"]) for o in ops_for(db, rid)]
    state_at_kill = volume_state(fsid, tok)
    api(db=db)
    final, seen = poll(r.headers["azure-asyncoperation"], POLL)
    v = call("GET", vol_url(ACCT, POOL, "v12a")).json()
    m = one_shot(mount_ip(v), tok, "3", "echo ok > /m/f && cat /m/f")
    lvs = [n for n in lvs_volumes() if n == lv_name(fsid)]
    note("AC-12a", sigkill_rc=rc, operations_at_kill=at_kill, dataplane_at_kill=state_at_kill, seen=seen,
         final=final, mount=out(m), lvs=lvs)
    assert at_kill == [("CREATE", "Creating")]
    assert final["status"] == "Succeeded"
    assert m.returncode == 0 and m.stdout == "ok\n"
    assert len(lvs) == 1
    delete_volume("v12a")


@pytest.mark.parametrize("stage", ["job-start", "lv-created", "mounted"])
def test_ac12b_agent_killed_during_create_job(agent, api, stage):
    """job의 여러 단계(결정 10)에서 agent를 SIGKILL한다: POST를 받은 직후, LV가 생긴 직후, 호스트 마운트 직후."""
    api()
    setup_pool()
    tok = token(f"ac12b{stage[:2]}")
    offset = len(agent.text())
    r = call("PUT", vol_url(ACCT, POOL, "v12b"), vol_body(tok))
    assert r.status == 201
    fsid = fsid_of(r.json())
    marker = f"POST /api/storage/volumes/{fsid}: job"  # agent 로그 문구 (스냅샷 사이클에서 job 설명과 같아졌다)
    mp = f" {NS / tok} "
    reached = {
        "job-start": lambda: marker in agent.text()[offset:],
        "lv-created": lambda: Path(f"/dev/anf/{lv_name(fsid)}").exists(),
        "mounted": lambda: mp in Path("/proc/self/mounts").read_text(),
    }[stage]
    deadline = time.monotonic() + 30
    while not reached():
        assert time.monotonic() < deadline, f"stage {stage} never reached"
        time.sleep(0.005)
    agent.kill()
    try:
        state_at_kill = volume_state(fsid, tok)
        time.sleep(3)
        state_before_restart = volume_state(fsid, tok)
    finally:
        t0 = time.monotonic()
        agent.start()
    final, seen = poll(r.headers["azure-asyncoperation"], 2 * POLL)
    recovered_seconds = round(time.monotonic() - t0, 1)
    v = call("GET", vol_url(ACCT, POOL, "v12b")).json()
    tagged = [n for n, x in lvs_volumes().items() if f"anf_uuid={fsid}" in x["tags"]]
    m = one_shot(mount_ip(v), tok, "3", "echo ok > /m/f && cat /m/f")
    note(f"AC-12b {stage}", dataplane_at_kill=state_at_kill, dataplane_3s_later=state_before_restart, seen=sorted(set(seen)),
         final=final, seconds_after_restart=recovered_seconds, lvs_for_uuid=tagged,
         dataplane_after=volume_state(fsid, tok), mount=out(m))
    assert final["status"] == "Succeeded"
    assert tagged == [lv_name(fsid)]
    assert m.returncode == 0 and m.stdout == "ok\n"
    delete_volume("v12b")


def test_ac12c_agent_restart_recovers_stopped_instance_and_unmounted_volume(agent, api):
    api()
    setup_pool()
    tok = token("ac12c")
    v = create_volume("v12c", tok, protocols=["NFSv4.1"])
    ip, fsid = mount_ip(v), fsid_of(v)
    w = one_shot(ip, tok, "4.1", "echo before-restart > /m/f && sync")
    assert w.returncode == 0, out(w)

    agent.stop()
    try:
        stop = sh("docker", "stop", instance_name(fsid))
        umount_tries = 0
        for umount_tries in range(1, 121):
            if sh("umount", str(NS / tok)).returncode == 0:
                break
            time.sleep(0.5)
        down = volume_state(fsid, tok)
        refused = one_shot(ip, tok, "4.1")
        note("AC-12c simulated restart", docker_stop=out(stop), umount_tries=umount_tries, dataplane=down,
             mount_while_down=out(refused))
        assert down["mounted"] is False and down["instance"] == "exited"
        assert refused.returncode != 0
    finally:
        agent.start()
    up = volume_state(fsid, tok)
    rd = one_shot(ip, tok, "4.1", "cat /m/f")
    note("AC-12c after agent start", dataplane=up, instance_ip=instance_ip(fsid), read=out(rd))
    assert up["mounted"] is True and up["instance"] == "running"
    assert instance_ip(fsid) == ip
    assert rd.returncode == 0 and rd.stdout == "before-restart\n"
    delete_volume("v12c")
