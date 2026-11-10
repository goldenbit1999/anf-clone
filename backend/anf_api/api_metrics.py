"""anf-api의 `/metrics` (메트릭 설계 §2.2): HTTP 요청과 비동기 작업의 지표.

- 요청: `route`는 경로 템플릿이라 구독·이름이 라벨에 들어가지 않는다(맞는 경로가 없으면 `unmatched`).
- 작업: 라벨은 LRO 처리기 키(결함 주입 키와 같은 `volumes/create`)를 나눈 것이다. 끝 상태가 되면 한 번 센다.
  소요 시간은 작업 행이 만들어진 때(`start_time`, DB의 벽시계 값)부터라 재시작을 넘어 이어진다.
- 값은 프로세스 메모리에 있다. 재시작하면 0부터 다시 센다(Prometheus `rate()`가 처리한다).

앱마다 레지스트리를 따로 둔다. 전역 레지스트리면 테스트가 앱을 다시 만들 때 이름이 겹친다.
"""

from collections.abc import Callable
from datetime import datetime, timezone

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

START_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"  # state_store.utc_now
# 작업은 계정·풀의 1초 미만부터 볼륨의 수십 초(인스턴스 준비, NFSv4 유예 45초)까지 걸린다
OPERATION_BUCKETS = (0.1, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600)


class ApiMetrics:
    def __init__(self, now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self._now = now
        self.registry = CollectorRegistry()
        self._requests = Counter("anf_api_http_requests_total", "HTTP requests by method, route template, and status.",
                                 ["method", "route", "status"], registry=self.registry)
        self._request_seconds = Histogram("anf_api_http_request_duration_seconds", "HTTP request latency.",
                                          ["method", "route"], registry=self.registry)
        op_labels = ["resource_type", "action"]
        self._operations = Counter("anf_api_operations_total", "Asynchronous operations that reached a terminal state.",
                                   [*op_labels, "result"], registry=self.registry)
        self._operation_seconds = Histogram("anf_api_operation_duration_seconds",
                                            "Time from operation creation to its terminal state.",
                                            [*op_labels, "result"], buckets=OPERATION_BUCKETS, registry=self.registry)
        self._in_progress = Gauge("anf_api_operations_in_progress", "Operations the worker is running now.",
                                  op_labels, registry=self.registry)

    def observe_request(self, method: str, route: str, status: int, seconds: float) -> None:
        self._requests.labels(method, route, str(status)).inc()
        self._request_seconds.labels(method, route).observe(seconds)

    def declare_operation(self, resource_type: str, action: str) -> None:
        """작업이 아직 없어도 진행 중 계열이 0으로 보이게 한다 (대시보드의 빈 차트를 피한다)."""
        self._in_progress.labels(resource_type, action)

    def operation_started(self, resource_type: str, action: str) -> None:
        self._in_progress.labels(resource_type, action).inc()

    def operation_stopped(self, resource_type: str, action: str) -> None:
        self._in_progress.labels(resource_type, action).dec()

    def operation_finished(self, resource_type: str, action: str, result: str, start_time: str) -> None:
        started = datetime.strptime(start_time, START_FORMAT).replace(tzinfo=timezone.utc)
        # WSL 벽시계가 뒤로 건너뛰어도 음수가 되지 않게 한다
        seconds = max(0.0, (self._now() - started).total_seconds())
        self._operations.labels(resource_type, action, result).inc()
        self._operation_seconds.labels(resource_type, action, result).observe(seconds)

    def exposition(self) -> bytes:
        return generate_latest(self.registry)
