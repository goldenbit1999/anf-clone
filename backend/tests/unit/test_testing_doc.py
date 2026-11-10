"""docs/testing.md의 수락 기준 대응표가 가리키는 pytest node ID가 실제로 수집되는지 확인한다
(테스트 자동화 설계 결정 11, AC-03).

표는 손으로 쓰는 문서다. 여기서는 테스트 이름이 바뀌어 표가 썩는 것과 FR 행이 비는 것만 막는다.
표가 PRD §6.1의 수락 기준 문장을 빠짐없이 담는지는 리뷰와 실환경 검증(AC-03)이 본다.
"""

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DOC = REPO / "docs" / "testing.md"
NODE_ID = re.compile(r"`(backend/tests/[^`\s]+\.py::[^`\s]+)`")


def doc_text() -> str:
    return DOC.read_text(encoding="utf-8")


def test_every_node_id_in_the_doc_is_collected():
    ids = sorted(set(NODE_ID.findall(doc_text())))
    assert ids, "no node IDs in docs/testing.md"
    files = sorted({i.split("::", 1)[0] for i in ids})
    r = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", *files],
                       cwd=REPO, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    collected = {line.strip() for line in r.stdout.splitlines()}
    assert [i for i in ids if i not in collected] == []


def test_each_of_fr01_to_fr08_has_a_row_with_a_test():
    rows = [line for line in doc_text().splitlines() if line.startswith("| FR-")]
    for n in range(1, 9):
        fr = f"FR-{n:02d}"
        assert any(line.startswith(f"| {fr} ") and NODE_ID.search(line) for line in rows), fr
