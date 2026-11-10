"""[verify, do not merge] FR-11 2부 AC-03 (_workspace/ci/02_main_design_dataplane.md §5).

데이터 플레인 테스트가 실패하면 data-plane 조각이 failure가 되고 artifact가 올라오는지 본다.
임시 브랜치 verify/fr11-ac03-fail에만 있다. 두 시험 모두 진짜 볼륨을 만들어 클라이언트에서 쓰고 읽는다.
하나는 맞는 내용을 기대해 통과하고, 하나는 일부러 틀린 내용을 기대해 실패한다. 실패하는 단언 전에 볼륨을
지워서, 실행기의 "남은 것" 검사가 실패 이유에 섞이지 않게 한다.
"""

import uuid

import pytest

import live_api
from dataplane_live import create_volume, delete_volume, mount_ip, note, out, setup_pool, SKIP_UNLESS_ROOT, token

pytestmark = [pytest.mark.e2e, pytest.mark.dataplane, live_api.SKIP_UNLESS_LIVE, SKIP_UNLESS_ROOT,
              pytest.mark.usefixtures("manual_data")]

WRONG = "AC-03 deliberately wrong expectation"


def _write_read(name: str, tag: str, clients) -> tuple[str, object]:
    setup_pool()
    tok = token(tag)
    v = create_volume(name, tok)
    ip = mount_ip(v)
    c = clients()
    content = f"ac03-{uuid.uuid4().hex}"
    c.mount(ip, tok, "3")
    rd = c.run(f"echo {content} > /m/f.txt && sync && cat /m/f.txt")
    note(f"verify AC-03 {tag} write+read", **out(rd))
    c.run("umount /m")
    delete_volume(name)
    return content, rd


def test_verify_ac03_real_write_read_passes(agent, api, clients):
    api()
    content, rd = _write_read("vac03p", "ac03p", clients)
    assert rd.returncode == 0, out(rd)
    assert rd.stdout.strip() == content


def test_verify_ac03_deliberate_failure(agent, api, clients):
    api()
    content, rd = _write_read("vac03f", "ac03f", clients)
    assert rd.returncode == 0, out(rd)
    assert rd.stdout.strip() == content
    assert rd.stdout.strip() == f"{WRONG}: {content}", "deliberate failure for FR-11 AC-03"
