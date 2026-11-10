"""deploy/compose.yaml의 불변 조건 (FR-13, 설계 _workspace/containers/02_main_design.md §1·§3, 스파이크 S9).

storage agent 컨테이너는 다섯 조건이 모두 있어야 볼륨 생성, 되돌리기, 처리량 제한이 컨테이너 안에서 돈다(S9 Q2).
하나라도 빠지면 compose는 뜨지만 나중에 데이터 플레인이 깨진다(되돌리기 실패, VG 활성화 경합, lvcreate 멈춤).
여기서는 파일이 그 조건을 담는지만 본다. 조건이 실제로 충분한지는 실환경 e2e(test_compose_stack_live.py)가 본다.

PyYAML은 의존성에 없다(pyproject.toml은 제품 코드 해시에 들어간다). compose 파일이 쓰는 YAML의 부분집합
(들여쓰기 매핑, 블록 시퀀스, 한 줄 JSON 배열, 따옴표 문자열, 줄 전체 주석)만 읽는 작은 파서를 둔다.
"""

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
DEPLOY = REPO / "deploy"
_MAP_ITEM = re.compile(r"^[A-Za-z_][\w.-]*:(\s|$)")


def parse_compose_subset(text: str):
    lines = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped and not stripped.startswith("#"):
            lines.append([len(raw) - len(raw.lstrip(" ")), stripped])
    value, pos = _block(lines, 0, lines[0][0])
    assert pos == len(lines), f"unparsed from line {lines[pos]}"
    return value


def _block(lines, pos, indent):
    if lines[pos][1].startswith("- "):
        return _seq(lines, pos, indent)
    return _map(lines, pos, indent)


def _map(lines, pos, indent):
    out = {}
    while pos < len(lines) and lines[pos][0] == indent and not lines[pos][1].startswith("- "):
        key, sep, rest = lines[pos][1].partition(":")
        assert sep, f"not a mapping line: {lines[pos]}"
        rest = rest.strip()
        pos += 1
        if rest:
            out[key] = _scalar(rest)
        elif pos < len(lines) and lines[pos][0] > indent:
            out[key], pos = _block(lines, pos, lines[pos][0])
        else:
            out[key] = None
    return out, pos


def _seq(lines, pos, indent):
    out = []
    while pos < len(lines) and lines[pos][0] == indent and lines[pos][1].startswith("- "):
        item = lines[pos][1][2:].strip()
        if _MAP_ITEM.match(item):
            lines[pos] = [indent + 2, item]
            value, pos = _map(lines, pos, indent + 2)
        else:
            value, pos = _scalar(item), pos + 1
        out.append(value)
    return out, pos


def _scalar(text: str):
    if text.startswith("["):
        return json.loads(text)
    if text[0] in "\"'":
        assert text[-1] == text[0], text
        return text[1:-1]
    if text in ("true", "false"):
        return text == "true"
    return int(text) if text.isdigit() else text


@pytest.fixture(scope="module")
def compose():
    return parse_compose_subset((DEPLOY / "compose.yaml").read_text(encoding="utf-8"))


def _volumes(service):
    """짧은 문법(원본:대상[:옵션])과 긴 문법을 {대상: 긴 문법 dict}로 맞춘다."""
    out = {}
    for v in service.get("volumes", []):
        if isinstance(v, str):
            parts = v.split(":")
            v = {"type": "bind", "source": parts[0], "target": parts[1], "read_only": parts[2:] == ["ro"]}
        out[v["target"]] = v
    return out


def test_parser_reads_the_whole_file(compose):
    assert set(compose) == {"name", "services", "volumes"}
    assert set(compose["services"]) == {"init", "storage-agent", "anf-api", "prometheus", "dashboard"}


def test_agent_is_privileged_on_host_network_and_pid(compose):
    agent = compose["services"]["storage-agent"]
    assert agent["privileged"] is True
    assert agent["network_mode"] == "host"
    # P4: 없으면 nsenter -t <인스턴스 pid>가 /proc/<pid>/ns/net을 열지 못해 tc 적용이 실패한다
    assert agent["pid"] == "host"


def test_agent_binds_state_dir_without_recursion(compose):
    # P3: 재귀 바인드는 재시작 때 ns 아래 마운트의 private 복사본을 만들어 되돌리기가 실패한다
    v = _volumes(compose["services"]["storage-agent"])["/var/lib/anf-clone"]
    assert v["source"] == "/var/lib/anf-clone"
    assert v["bind"]["recursive"] == "disabled"


def test_agent_binds_ns_rshared_after_init(compose):
    agent = compose["services"]["storage-agent"]
    v = _volumes(agent)["/var/lib/anf-clone/ns"]
    assert v["source"] == "/var/lib/anf-clone/ns"
    # P1: agent가 컨테이너 안에서 한 마운트가 호스트와 볼륨 인스턴스로 가야 한다
    assert v["bind"]["propagation"] == "rshared"
    # 호스트의 ns를 rshared로 만드는 init이 먼저 끝나야 docker가 이 바인드를 받아들인다
    assert agent["depends_on"]["init"]["condition"] == "service_completed_successfully"


def test_agent_shares_the_lvm_lock_dir(compose):
    vols = _volumes(compose["services"]["storage-agent"])
    # P2: 호스트 udev의 VG 자동 활성화와 같은 잠금을 써야 vgchange가 경합하지 않는다
    assert vols["/run/lock/lvm"]["source"] == "/run/lock/lvm"


def test_agent_waits_for_host_udev_like_a_host_process(compose):
    agent = compose["services"]["storage-agent"]
    vols = _volumes(agent)
    # L4: LVM이 호스트 udev를 보고(/run/udev) 그 처리가 끝날 때까지 기다린다. 기다리지 않으면(L2) lvcreate 직후의
    # mount가 /dev/anf/<lv>를 못 찾을 때가 있다(FR-13 구현 중 변경). 쿠키 세마포어가 호스트 IPC 네임스페이스에
    # 있어야 호스트 udev가 풀어 준다. /run/udev만 붙이면 lvcreate가 멈춘다(L3)
    assert vols["/run/udev"]["read_only"] is True
    assert agent["ipc"] == "host"


def test_agent_has_devices_modules_and_docker_socket(compose):
    vols = _volumes(compose["services"]["storage-agent"])
    assert vols["/dev"]["source"] == "/dev"
    assert vols["/lib/modules"]["read_only"] is True
    assert vols["/var/run/docker.sock"]["source"] == "/var/run/docker.sock"


def test_init_prepares_the_host_once_from_the_repository(compose):
    init = compose["services"]["init"]
    assert init["privileged"] is True
    assert init["pid"] == "host"
    assert init["command"] == ["bash", "/repo/deploy/init.sh"]
    vols = _volumes(init)
    assert vols["/repo"]["source"] == ".." and vols["/repo"]["read_only"] is True
    # init.sh는 docker inspect로 /repo 바인드의 호스트 경로를 찾는다
    assert vols["/var/run/docker.sock"]["source"] == "/var/run/docker.sock"
    assert "setup-wsl-dataplane.sh" in (DEPLOY / "init.sh").read_text(encoding="utf-8")


def test_services_listen_on_localhost_only(compose):
    services = compose["services"]
    # host 네트워크라 포트 공개가 없고, 각 서버가 127.0.0.1에만 바인딩한다(D-13)
    assert [n for n, s in services.items() if "ports" in s] == []
    assert all(s["network_mode"] == "host" for n, s in services.items() if n != "init")
    for dockerfile in ("agent/Dockerfile", "api/Dockerfile"):
        assert '"--host", "127.0.0.1"' in (DEPLOY / dockerfile).read_text(encoding="utf-8")
    assert "--web.listen-address=127.0.0.1:9090" in services["prometheus"]["command"]
    assert "listen 127.0.0.1:8081;" in (DEPLOY / "dashboard" / "nginx.conf").read_text(encoding="utf-8")


def test_compose_does_not_own_the_volume_network(compose):
    # anf-vnet은 init(setup 스크립트)이 만든다. compose가 가지면 down이 인스턴스 때문에 지우지 못한다(결정 5)
    assert "networks" not in compose
