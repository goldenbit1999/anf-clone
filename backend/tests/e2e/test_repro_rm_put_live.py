"""[repro, do not merge] FR-11 검증 2회차 tp8: AC-07 (b) → (c)를 쓰는 중에 되풀이한다.

(b) docker stop + agent 재시작, (c) docker rm -f + 재PUT. (c)의 작업이 Succeeded가 아니거나 docker rm이 느리거나
실패하면 호스트 상태(컨테이너, D 상태 프로세스와 커널 스택, netns, 호스트 rpcbind)를 남기고 실패한다.
"""

import os
import time

import pytest

import live_api
from live_api import TIB, call, create_account, create_pool, poll
from dataplane_live import (
    ACCT, GIB, delete_volume, fsid_of, instance_name, mount_ip, note, out, sh, SKIP_UNLESS_ROOT, token, vol_body, vol_url,
)
from revert_live import instance_pid
from snapshot_live import create_snapshot
from throughput_live import fio, in_background, make

pytestmark = [pytest.mark.e2e, pytest.mark.dataplane, live_api.SKIP_UNLESS_LIVE, SKIP_UNLESS_ROOT]

ROUNDS = int(os.environ.get("ANF_REPRO_ROUNDS", "8"))
MIBPS = 10
RUNTIME = 40

HOST_RPCBIND = ("systemctl is-active rpcbind.service rpcbind.socket 2>&1; ls -la /run/rpcbind.sock 2>&1; "
                "ss -xlp 2>&1 | grep -i rpcbind; rpcinfo -p 2>&1 | head -3; "
                "journalctl -u rpcbind.service -u rpcbind.socket --no-pager -n 20 2>&1; "
                "dpkg -l rpcbind nfs-kernel-server nfs-common 2>&1 | tail -3")
STACKS = ("ps -eo pid,stat,wchan:40,comm | awk 'NR == 1 || $2 ~ /D/'; "
          "for p in $(ps -eo pid,stat | awk '$2 ~ /D/ {print $1}'); do echo \"== $p $(cat /proc/$p/comm)\"; "
          "cat /proc/$p/stack; done 2>&1 | head -200")


def diag(fsid: str) -> dict:
    name = instance_name(fsid)
    inspect = sh("docker", "inspect", "-f", "{{json .State}}", name)
    return {"ps": sh("docker", "ps", "-a", "--format", "{{.Names}} {{.State}} {{.Status}}").stdout,
            "state": (inspect.stdout + inspect.stderr).strip(),
            "dstate": sh("sh", "-c", STACKS).stdout,
            "netns": sh("lsns", "-t", "net", "-o", "NS,NPROCS,PID,COMMAND").stdout,
            "host_rpcbind": sh("sh", "-c", HOST_RPCBIND).stdout,
            "veth": sh("sh", "-c", "ip -o link show type veth | awk '{print $2}'").stdout}


def abort_io(c, mp: str = "/m") -> dict:
    return out(c.run(f"for i in $(seq 30); do umount -f {mp} && exit 0; sleep 1; done; exit 1", timeout=90))


def gone_after(fsid: str, limit: float = 300) -> float | None:
    """docker rm 뒤 컨테이너가 목록에서 사라질 때까지 초. limit까지 없어지지 않으면 None."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < limit:
        if not sh("docker", "ps", "-aq", "--filter", f"name=^{instance_name(fsid)}$").stdout.strip():
            return round(time.monotonic() - t0, 2)
        time.sleep(0.5)
    return None


def test_repro_rm_then_put(agent, api, clients):
    api()
    note("REPRO", host_rpcbind=sh("sh", "-c", HOST_RPCBIND).stdout, kernel=os.uname().release)
    create_account(ACCT)
    create_pool(ACCT, "ul", 2 * TIB, "Ultra", qos_type="Manual")
    tok = token("rp")
    *_, v = make("l1", tok, "ul", GIB, throughputMibps=MIBPS)
    fsid = fsid_of(v)
    c = clients()
    c.mount(mount_ip(v), tok, "3")
    assert fio(c, "write", "/m/f", MIBPS * 15)["error"] == 0
    create_snapshot("l1", "s1", pool="ul")
    rounds = []
    for i in range(ROUNDS):
        # (b) docker stop + agent 재시작
        wait = in_background(fio, c, "write", "/m/f", MIBPS * 15, runtime=RUNTIME, timeout=RUNTIME + 300)
        time.sleep(6)
        rc = sh("docker", "stop", instance_name(fsid)).returncode
        agent.stop()
        agent.start()
        b = {"docker_stop_rc": rc, "pid_after": instance_pid(fsid)}
        try:
            b["fio"] = wait()
        except BaseException as e:  # noqa: BLE001
            b["fio_error"] = repr(e)[:500]
            b["diag"] = diag(fsid)
            b["abort_io"] = abort_io(c)
            note("REPRO", round=i, b=b)
            raise
        # (c) docker rm -f + 재PUT
        wait = in_background(fio, c, "write", "/m/f", MIBPS * 15, runtime=RUNTIME, timeout=RUNTIME + 300)
        time.sleep(6)
        t0 = time.monotonic()
        rm = sh("docker", "rm", "-f", instance_name(fsid), timeout=400)
        rm_s = round(time.monotonic() - t0, 2)
        left = sh("docker", "ps", "-a", "--filter", f"name=^{instance_name(fsid)}$",
                  "--format", "{{.ID}} {{.State}} {{.Status}}").stdout.strip()
        slow = rm.returncode != 0 or rm_s > 5 or left
        d = {"docker_rm_rc": rm.returncode, "docker_rm_s": rm_s, "docker_rm_stderr": rm.stderr.strip(),
             "container_after_rm": left}
        if slow:
            d["diag_after_rm"] = diag(fsid)
        r = call("PUT", vol_url(ACCT, "ul", "l1"), vol_body(tok, GIB, throughputMibps=MIBPS))
        final, seen = poll(r.headers["azure-asyncoperation"], 120)
        d.update(put=r.status, seen=seen, final=final["status"], op=final, pid_after=instance_pid(fsid))
        if final["status"] != "Succeeded":
            d["diag_after_put"] = diag(fsid)
            d["gone_after_s"] = gone_after(fsid)
            d["diag_after_gone"] = diag(fsid)
            d["abort_io"] = abort_io(c)
            note("REPRO", round=i, b=b, c=d, agent_log_tail=agent.text()[-6000:])
            raise AssertionError(f"round {i}: re-PUT after docker rm -f did not succeed: {d['op']}")
        try:
            d["fio"] = wait()
        except BaseException as e:  # noqa: BLE001
            d["fio_error"] = repr(e)[:500]
            d["diag"] = diag(fsid)
            d["abort_io"] = abort_io(c)
            note("REPRO", round=i, b=b, c=d)
            raise
        note("REPRO", round=i, b=b, c=d)
        rounds.append({"rm_rc": rm.returncode, "rm_s": rm_s, "final": final["status"], "slow": bool(slow)})
    note("REPRO summary", rounds=rounds)
    c.remove()
    delete_volume("l1", pool="ul")
    assert all(x["final"] == "Succeeded" for x in rounds), rounds
