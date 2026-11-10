"""junit_gate.py: JUnit XML을 합쳐 수집 0개, skip, 실패, 오류, 읽을 수 없는 XML을 실패로 판정한다
(테스트 자동화 설계 결정 5·6, §5.3).

데이터 플레인 실행기(scripts/run-dataplane-tests.sh)와 CI의 "Fail on skipped tests" 단계가 같은 명령을 부른다.
그래서 명령 그대로(별도 프로세스의 종료 코드와 출력)로 확인한다.
"""

import subprocess
import sys
from pathlib import Path

import pytest

GATE = Path(__file__).resolve().parents[1] / "junit_gate.py"
SKIP_MESSAGE = "Skipped tests are not passes. Run them here or deselect them by marker on purpose."


def suite(tests=1, failures=0, errors=0, skipped=0, time="1.0"):
    return (f'<testsuite name="pytest" errors="{errors}" failures="{failures}" skipped="{skipped}" '
            f'tests="{tests}" time="{time}" timestamp="2026-11-09T00:00:00" hostname="h" />')


def xml(tmp_path, name, *suites, wrapped=True):
    """pytest의 기본 형식은 <testsuites><testsuite/></testsuites>다. wrapped=False는 <testsuite>가 루트인 형식."""
    body = "".join(suites)
    p = tmp_path / f"{name}.xml"
    p.write_text("<?xml version='1.0' encoding='utf-8'?>" + (f"<testsuites>{body}</testsuites>" if wrapped else body),
                 encoding="utf-8")
    return p


def gate(*paths):
    r = subprocess.run([sys.executable, str(GATE), *map(str, paths)], capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout + r.stderr


def row(output, name):
    """요약 표에서 name 행의 칸들 (file, tests, passed, failed, errors, skipped, seconds)."""
    return next(line.split() for line in output.splitlines() if line.split()[:1] == [name])


def test_all_passed_exits_0_with_counts(tmp_path):
    rc, output = gate(xml(tmp_path, "test_a", suite(tests=3, time="2.25")))
    assert rc == 0, output
    assert "collected 3, skipped 0" in output
    assert row(output, "test_a") == ["test_a", "3", "3", "0", "0", "0", "2.2"]
    assert row(output, "total") == ["total", "3", "3", "0", "0", "0", "2.2"]


def test_testsuite_root_is_read_too(tmp_path):
    rc, output = gate(xml(tmp_path, "old", suite(tests=2), wrapped=False))
    assert rc == 0, output
    assert "collected 2, skipped 0" in output


def test_a_skip_fails(tmp_path):
    rc, output = gate(xml(tmp_path, "test_a", suite(tests=3, skipped=1)))
    assert rc == 1, output
    assert "collected 3, skipped 1" in output
    assert SKIP_MESSAGE in output
    assert row(output, "test_a")[1:6] == ["3", "2", "0", "0", "1"]


def test_nothing_collected_fails(tmp_path):
    rc, output = gate(xml(tmp_path, "empty", suite(tests=0)))
    assert rc == 1, output
    assert "collected 0, skipped 0" in output
    assert "No tests were collected." in output


@pytest.mark.parametrize("counts, failed, errors", [
    pytest.param({"failures": 1}, "1", "0", id="failure"),
    pytest.param({"errors": 2}, "0", "2", id="error"),
])
def test_failures_and_errors_fail(tmp_path, counts, failed, errors):
    rc, output = gate(xml(tmp_path, "test_a", suite(tests=4, **counts)))
    assert rc == 1, output
    assert row(output, "test_a")[3:5] == [failed, errors]
    assert f"{failed} failed, {errors} errors." in output


def test_counts_add_up_across_files(tmp_path):
    a = xml(tmp_path, "test_a", suite(tests=5, time="10.0"))
    b = xml(tmp_path, "test_b", suite(tests=3, skipped=1, time="4.5"))
    rc, output = gate(a, b)
    assert rc == 1, output
    assert row(output, "test_a") == ["test_a", "5", "5", "0", "0", "0", "10.0"]
    assert row(output, "test_b") == ["test_b", "3", "2", "0", "0", "1", "4.5"]
    assert row(output, "total") == ["total", "8", "7", "0", "0", "1", "14.5"]
    assert "collected 8, skipped 1" in output


def test_files_that_all_pass_together_exit_0(tmp_path):
    rc, output = gate(xml(tmp_path, "test_a", suite(tests=5)), xml(tmp_path, "test_b", suite(tests=1)))
    assert rc == 0, output
    assert "collected 6, skipped 0" in output


def test_missing_or_unreadable_xml_fails_and_is_named(tmp_path):
    """pytest가 죽으면 XML이 없거나 중간에 끊긴다. 나머지 파일이 모두 통과해도 실패다."""
    good = xml(tmp_path, "test_good", suite(tests=2))
    broken = tmp_path / "test_broken.xml"
    broken.write_text("<testsuites><testsuite tests=", encoding="utf-8")
    missing = tmp_path / "test_missing.xml"
    rc, output = gate(good, broken, missing)
    assert rc == 1, output
    assert row(output, "test_broken")[1:] == ["no", "readable", "XML"]
    assert row(output, "test_missing")[1:] == ["no", "readable", "XML"]
    assert row(output, "total")[1] == "2"
    assert f"No readable JUnit XML: {broken}, {missing}" in output
