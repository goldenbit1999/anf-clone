"""대시보드 실환경 검증 도구 (FR-09): anf-api의 트리를 직접 읽어 화면 행과 같은 형식으로 남긴다.

pytest 테스트가 아니라 검증자가 손으로 실행하는 도구다 (대시보드 설계 §7, real-env-verify "대시보드 화면").
Windows의 .venv-win Python으로 실행한다. 브라우저의 Date.now()와 같은 Windows 시계로 시각을 남겨야
"API 상태가 바뀐 뒤 화면에 보이기까지"를 잴 수 있기 때문이다 (WSL 시계는 뒤로 갈 수 있다).

    python backend/tests/e2e/dashboard_watch.py watch SUB LOG.jsonl [간격초]
        간격마다 트리를 읽고, 행이 바뀔 때마다 한 줄을 남긴다 (t, prev_t, rows 또는 error).
    python backend/tests/e2e/dashboard_watch.py rows SUB
        지금 API 트리를 화면 행 형식 [깊이, 이름, 종류, 상태, 속성]으로 출력한다.
    python backend/tests/e2e/dashboard_watch.py compare SUB DOM.json
        DOM에서 읽은 행(JSON 배열)과 지금 API 행을 비교한다. 같으면 종료 코드 0.

API 주소는 ANF_API_URL (기본 http://127.0.0.1:8080). 대시보드의 Vite 프록시를 거치지 않고 anf-api를 직접 부른다.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

API = os.environ.get("ANF_API_URL", "http://127.0.0.1:8080")
VERSION = "2026-08-01"
CHILDREN = ["capacityPools", "volumes", "snapshots"]
KINDS = ["NetApp account", "Capacity pool", "Volume", "Snapshot"]
GIB = 1024 ** 3
TIB = 1024 * GIB


class ReadError(Exception):
    pass


def _list(path: str, missing_is_empty: bool) -> list[dict]:
    try:
        with urllib.request.urlopen(f"{API}{path}?api-version={VERSION}", timeout=5) as r:
            return json.loads(r.read())["value"]
    except urllib.error.HTTPError as e:
        if e.code == 404 and missing_is_empty:
            return []
        raise ReadError(f"GET {path} returned {e.code}") from None
    except OSError as e:
        raise ReadError(f"GET {path}: {e}") from None


def tree(sub: str) -> list[dict]:
    def node(res: dict, depth: int) -> dict:
        kids = [] if depth >= len(CHILDREN) else _list(f"{res['id']}/{CHILDREN[depth]}", True)
        return {"resource": res, "children": [node(k, depth + 1) for k in kids]}

    accounts = _list(f"/subscriptions/{sub}/providers/Microsoft.NetApp/netAppAccounts", False)
    return [node(a, 0) for a in accounts]


def _js(x) -> str:
    """JavaScript의 `${x}`와 같은 숫자 글자 (4.0 → "4")."""
    if isinstance(x, bool) or x is None:
        return json.dumps(x)
    if isinstance(x, float) and x.is_integer():
        return str(int(x))
    return str(x)


def _details(depth: int, r: dict) -> str:
    p = r["properties"]
    if depth == 0:
        parts = [r["id"].split("/")[4], r.get("location", "")]
    elif depth == 1:
        parts = [f"{_js(p['size'] / TIB)} TiB", str(p.get("serviceLevel")), f"{p.get('qosType')} QoS",
                 f"{_js(p.get('utilizedThroughputMibps'))} / {_js(p.get('totalThroughputMibps'))} MiB/s"]
    elif depth == 2:
        mt = p.get("mountTargets") or []
        parts = [f"{mt[0]['ipAddress']}:/{p['creationToken']}" if mt else "",
                 ", ".join(p.get("protocolTypes", [])), f"{_js(p['usageThreshold'] / GIB)} GiB",
                 f"{_js(p.get('actualThroughputMibps'))} MiB/s"]
    else:
        parts = [str(p.get("created") or "")]
    return " · ".join(x for x in parts if x)


def rows(nodes: list[dict], depth: int = 0) -> list[list]:
    out = []
    for n in nodes:
        r = n["resource"]
        out.append([depth + 1, r["name"].split("/")[-1], KINDS[depth], r["properties"]["provisioningState"],
                    _details(depth, r)])
        out.extend(rows(n["children"], depth + 1))
    return out


def watch(sub: str, log_path: str, interval: float) -> None:
    last, prev_t = None, None
    with open(log_path, "a", encoding="utf-8") as log:
        while True:
            t = time.time()
            try:
                entry = {"rows": rows(tree(sub))}
            except ReadError as e:
                entry = {"error": str(e)}
            key = json.dumps(entry, sort_keys=True)
            if key != last:
                log.write(json.dumps({"t": round(t, 3), "iso": datetime.fromtimestamp(t).isoformat(timespec="milliseconds"),
                                      "prev_t": prev_t, **entry}, ensure_ascii=False) + "\n")
                log.flush()
                last = key
            prev_t = round(t, 3)
            time.sleep(max(0.0, interval - (time.time() - t)))


def compare(sub: str, dom_path: str) -> int:
    with open(dom_path, encoding="utf-8") as f:
        dom = json.load(f)
    api = rows(tree(sub))
    dom = [[int(x[0]), *x[1:5]] for x in dom]
    for i in range(max(len(api), len(dom))):
        a = api[i] if i < len(api) else None
        d = dom[i] if i < len(dom) else None
        print(("same " if a == d else "DIFF ") + json.dumps({"api": a, "dom": d}, ensure_ascii=False))
    same = api == dom
    print(f"rows api={len(api)} dom={len(dom)} identical={same}")
    return 0 if same else 1


if __name__ == "__main__":
    cmd, sub = sys.argv[1], sys.argv[2]
    if cmd == "watch":
        watch(sub, sys.argv[3], float(sys.argv[4]) if len(sys.argv) > 4 else 0.5)
    elif cmd == "rows":
        print(json.dumps(rows(tree(sub)), ensure_ascii=False, indent=1))
    elif cmd == "compare":
        sys.exit(compare(sub, sys.argv[3]))
    else:
        sys.exit(f"unknown command {cmd}")
