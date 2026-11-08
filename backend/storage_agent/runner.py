"""커널 명령 실행기. 셸을 거치지 않고 인자 목록으로 실행한다 (ADR R-07).

agent의 볼륨 관리자는 이 객체를 주입받는다. 단위 테스트는 가짜 실행기를 넣어 Windows에서도 돈다 (ADR §9.2).
"""

import logging
import os
import subprocess
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Result:
    returncode: int
    stdout: str
    stderr: str


class CommandError(Exception):
    def __init__(self, argv: list[str], result: Result):
        super().__init__(f"{' '.join(argv)} exited {result.returncode}: {result.stderr.strip()}")
        self.argv = argv
        self.result = result


class Runner:
    def __init__(self):
        # LVM은 상속된 파일 기술자마다 경고를 낸다 (S1 추가 관찰)
        self._env = {**os.environ, "LVM_SUPPRESS_FD_WARNINGS": "1"}

    def run(self, argv: list[str], check: bool = True, input: str | None = None) -> Result:
        if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
            raise TypeError("argv must be a list of strings (no shell)")
        # 입력이 없으면 빈 입력을 준다. 확인 질문이 데몬의 표준 입력을 기다리며 멈추지 않게 한다
        stdin = {"input": input} if input is not None else {"stdin": subprocess.DEVNULL}
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, env=self._env, **stdin)
            result = Result(proc.returncode, proc.stdout, proc.stderr)
        except FileNotFoundError as e:
            result = Result(127, "", str(e))
        log.debug("run %s -> %s", argv, result.returncode)
        if check and result.returncode != 0:
            raise CommandError(argv, result)
        return result
