"""메모리 job 표. ONTAP의 비동기 job 모델(queued·running·success·failure)을 따른다 (볼륨 설계 결정 8·9, §6.2).

- 같은 키(agent는 작업 종류 + 볼륨 UUID)에 끝나지 않은 job이 있으면 새 job을 만들지 않고 그 job을 돌려준다.
- job은 한 번에 하나씩 실행한다. 두 job이 LVM을 동시에 바꾸거나 같은 볼륨 IP를 고르지 않게 하기 위해서다.
- 끝난 job은 보관 시간(ONTAP 300초)이 지나면 지운다. agent가 재시작하면 표가 비므로 조회는 404가 된다.
"""

import logging
import queue
import threading
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone

log = logging.getLogger(__name__)

TERMINAL = ("success", "failure")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobTable:
    def __init__(self, retention_seconds: float = 300, clock: Callable[[], float] = time.monotonic):
        self._retention = retention_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}
        self._finished_at: dict[str, float] = {}
        self._unfinished: dict[str, str] = {}  # 키 → 끝나지 않은 job uuid
        self._queue: queue.Queue = queue.Queue()
        self._worker = threading.Thread(target=self._run, name="storage-agent-jobs", daemon=True)
        self._worker.start()

    def submit(self, key: str, work: Callable[[], None], description: str) -> dict:
        with self._lock:
            existing = self._unfinished.get(key)
            if existing is not None:
                return dict(self._jobs[existing])
            job = {
                "uuid": str(uuid.uuid4()),
                "description": description,
                "state": "queued",
                "message": "",
                "code": 0,
                "start_time": None,
                "end_time": None,
            }
            self._jobs[job["uuid"]] = job
            self._unfinished[key] = job["uuid"]
            self._queue.put((key, job["uuid"], work))
            return dict(job)

    def get(self, job_uuid: str) -> dict | None:
        with self._lock:
            self._expire()
            job = self._jobs.get(job_uuid)
            return dict(job) if job else None

    def close(self) -> None:
        self._queue.put(None)
        self._worker.join(timeout=5)

    def _run(self) -> None:
        while (item := self._queue.get()) is not None:
            key, job_uuid, work = item
            with self._lock:
                self._jobs[job_uuid].update(state="running", start_time=_now())
            try:
                work()
            except Exception as e:
                log.exception("job %s failed", job_uuid)
                self._finish(key, job_uuid, "failure", str(e), 1)
            else:
                self._finish(key, job_uuid, "success", "", 0)

    def _finish(self, key: str, job_uuid: str, state: str, message: str, code: int) -> None:
        with self._lock:
            self._jobs[job_uuid].update(state=state, message=message, code=code, end_time=_now())
            self._finished_at[job_uuid] = self._clock()
            del self._unfinished[key]

    def _expire(self) -> None:
        now = self._clock()
        for job_uuid, finished in list(self._finished_at.items()):
            if now - finished > self._retention:
                del self._finished_at[job_uuid]
                del self._jobs[job_uuid]
