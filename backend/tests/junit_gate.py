"""JUnit XML 판정: 수집 0개, skip, 실패, 오류, 읽을 수 없는 XML이 하나라도 있으면 실패다 (테스트 자동화 설계 결정 5, §5.3).

pytest는 skip만 있어도 0으로 끝난다. skip은 PASS가 아니다 (PRD §8, ADR §9.1). 데이터 플레인 실행기
(scripts/run-dataplane-tests.sh)와 CI의 "Fail on skipped tests" 단계가 이 스크립트를 같이 쓴다.

    python backend/tests/junit_gate.py <JUnit XML> [<JUnit XML> ...]

XML마다 한 행(파일, 수집, 통과, 실패, 오류, skip, 초)과 합계를 출력하고, 위 조건이면 1로 끝난다.
초는 XML의 time(pytest가 단조 시계로 잰 세션 시간)이다.
"""

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

FIELDS = ("tests", "failures", "errors", "skipped")
ROW = "{:<44} {:>6} {:>6} {:>6} {:>6} {:>7} {:>9}"


def read(path: Path) -> dict | None:
    """<testsuites> 아래의 <testsuite>들, 또는 루트 <testsuite> 하나를 합친다. 없거나 깨졌으면 None."""
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return None
    suites = list(root.iter("testsuite"))
    if not suites:
        return None
    counts = {f: sum(int(s.get(f, 0)) for s in suites) for f in FIELDS}
    counts["time"] = sum(float(s.get("time", 0)) for s in suites)
    return counts


def line(name: str, c: dict) -> str:
    passed = c["tests"] - c["failures"] - c["errors"] - c["skipped"]
    return ROW.format(name, c["tests"], passed, c["failures"], c["errors"], c["skipped"], f"{c['time']:.1f}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("xml", nargs="+", type=Path)
    args = parser.parse_args(argv)

    total = dict.fromkeys(FIELDS, 0) | {"time": 0.0}
    unreadable = []
    print(ROW.format("file", "tests", "passed", "failed", "errors", "skipped", "seconds"))
    for path in args.xml:
        counts = read(path)
        if counts is None:
            unreadable.append(str(path))
            print(f"{path.stem:<44} no readable XML")
            continue
        print(line(path.stem, counts))
        for key in total:
            total[key] += counts[key]
    print(line("total", total))
    print(f"collected {total['tests']}, skipped {total['skipped']}")

    problems = []
    if unreadable:
        problems.append(f"No readable JUnit XML: {', '.join(unreadable)} (pytest did not finish).")
    if total["tests"] == 0:
        problems.append("No tests were collected.")
    if total["failures"] or total["errors"]:
        problems.append(f"{total['failures']} failed, {total['errors']} errors.")
    if total["skipped"]:
        problems.append("Skipped tests are not passes. Run them here or deselect them by marker on purpose.")
    for p in problems:
        print(p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
