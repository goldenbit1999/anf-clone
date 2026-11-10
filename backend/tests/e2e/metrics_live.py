"""메트릭 실환경 검증 도구 (메트릭 설계 §5·§6). test_metrics_data_live.py가 쓰는 도우미 모듈이다.

볼륨·처리량 e2e 도우미(dataplane_live.py, throughput_live.py)를 그대로 쓰고, 여기에는 storage agent `/metrics`
읽기, 클라이언트 안 fio의 바이트·연산 수, 클라이언트 `df`, Prometheus 컨테이너와 쿼리 API만 더한다.
"""

import http.client
import json
import threading
import time
import urllib.parse
import urllib.request

from prometheus_client.parser import text_string_to_metric_families

from dataplane_live import AGENT_HOST, AGENT_PORT, REPO, out, sh
from throughput_live import FIO

MIB = 1 << 20
PROMETHEUS = "http://127.0.0.1:9090"


# --- storage agent /metrics ---


def scrape_agent(timeout: float = 30) -> tuple[int, str, float]:
    """(상태 코드, 본문, 걸린 초). 걸린 시간은 게스트 단조 시계로 잰다."""
    start = time.monotonic()
    conn = http.client.HTTPConnection(AGENT_HOST, AGENT_PORT, timeout=timeout)
    try:
        conn.request("GET", "/metrics")
        r = conn.getresponse()
        body = r.read().decode()
    finally:
        conn.close()
    return r.status, body, time.monotonic() - start


def parse(text: str) -> dict:
    """노출 형식 → {(샘플 이름, 정렬한 라벨 튜플): 값}."""
    return {(s.name, tuple(sorted(s.labels.items()))): s.value
            for family in text_string_to_metric_families(text) for s in family.samples}


def agent_samples() -> dict:
    status, body, _ = scrape_agent()
    assert status == 200, body[:500]
    return parse(body)


def value(samples: dict, name: str, token_: str, **labels) -> float | None:
    """creation_token(과 op 같은 라벨)으로 찾은 볼륨 계열의 값. 없으면 None."""
    for (n, key), v in samples.items():
        d = dict(key)
        if n == name and d.get("creation_token") == token_ and all(d.get(k) == x for k, x in labels.items()):
            return v
    return None


def names_of(samples: dict, uuid: str) -> list[str]:
    """그 볼륨 uuid 라벨이 붙은 메트릭 이름들."""
    return sorted({n for n, key in samples if dict(key).get("volume_uuid") == uuid})


def delta(before: dict, after: dict, name: str, token_: str, **labels) -> float:
    return (value(after, name, token_, **labels) or 0) - (value(before, name, token_, **labels) or 0)


class AgentScraper(threading.Thread):
    """agent `/metrics`를 interval초마다 긁는다 (AC-11). rows: (단조 시각, 상태 코드, 걸린 초)."""

    def __init__(self, interval: float = 1.0):
        super().__init__(daemon=True)
        self.interval = interval
        self.rows: list[tuple[float, int, float]] = []
        self._done = threading.Event()

    def run(self) -> None:
        while not self._done.is_set():
            t = time.monotonic()
            try:
                status, _, elapsed = scrape_agent()
            except OSError as e:
                status, elapsed = -1, time.monotonic() - t
                print(f"scrape failed: {e}")
            self.rows.append((round(t, 3), status, round(elapsed, 4)))
            self._done.wait(max(0.0, self.interval - (time.monotonic() - t)))

    def stop(self) -> list[tuple[float, int, float]]:
        self._done.set()
        self.join(60)
        return self.rows


# --- 클라이언트 ---


def fio_job(c, args: str, timeout: int = 600) -> dict:
    """클라이언트 안 fio job 하나. 반환: 오류 수와 방향별 바이트·연산 수(fio가 끝낸 I/O)."""
    r = c.run(f"{FIO} --name=j {args}", timeout=timeout)
    assert r.returncode == 0, out(r)
    job = json.loads(r.stdout[r.stdout.index("{"):])["jobs"][0]
    return {"error": job["error"],
            **{d: {"bytes": job[d]["io_bytes"], "ios": job[d]["total_ios"]} for d in ("read", "write")}}


def client_df(c, path: str) -> dict:
    """클라이언트가 NFS로 보는 크기·사용량(바이트)과 inode."""
    r = c.run(f"df -B1 --output=size,used,itotal,iused {path} | tail -1")
    assert r.returncode == 0, out(r)
    size, used, inodes, inodes_used = (int(x) for x in r.stdout.split())
    return {"size": size, "used": used, "inodes": inodes, "inodes_used": inodes_used}


# --- Prometheus ---


def run_prometheus(*args: str):
    return sh("bash", str(REPO / "scripts" / "run-prometheus.sh"), *args, timeout=300)


def prom(path: str, **params) -> dict:
    url = f"{PROMETHEUS}{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=10) as r:
        body = json.load(r)
    assert body["status"] == "success", body
    return body["data"]


def instant(query: str) -> list[dict]:
    return prom("/api/v1/query", query=query)["result"]


def scalar(query: str) -> float | None:
    """결과가 계열 하나면 그 값, 없으면 None."""
    result = instant(query)
    assert len(result) <= 1, result
    return float(result[0]["value"][1]) if result else None


def query_range(query: str, start: float, end: float, step: float = 5) -> list[dict]:
    """start·end는 벽시계(Unix 초)다. Prometheus가 표본에 붙이는 시각과 같은 시계다."""
    return prom("/api/v1/query_range", query=query, start=f"{start:.3f}", end=f"{end:.3f}", step=step)["result"]


def wait_until(fn, timeout: float, interval: float = 0.5, what: str = "condition"):
    """fn()이 참인 값을 돌려줄 때까지 기다린다. 반환: (그 값, 걸린 초)."""
    start = time.monotonic()
    while True:
        result = fn()
        if result:
            return result, time.monotonic() - start
        assert time.monotonic() - start < timeout, f"{what} not met after {timeout}s (last: {result!r})"
        time.sleep(interval)


def targets_up() -> dict:
    return {r["metric"]["job"]: r["value"][1] for r in instant("up")}
