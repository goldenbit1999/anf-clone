"""anf-api 메트릭 묶음: HTTP 요청, 비동기 작업의 수·소요 시간·진행 중 수 (메트릭 설계 §2.2).

미들웨어와 워커에 붙인 동작은 test_arm_app.py와 test_lro.py가 확인한다.
"""

from datetime import datetime, timedelta, timezone

from prometheus_client.parser import text_string_to_metric_families

from anf_api.api_metrics import ApiMetrics

START = "2026-11-10T09:00:00.250000Z"  # state_store.utc_now 형식
T0 = datetime(2026, 11, 10, 9, 0, 0, 250000, tzinfo=timezone.utc)


def samples(metrics: ApiMetrics) -> dict:
    text = metrics.exposition().decode()
    return {(s.name, tuple(sorted(s.labels.items()))): s.value
            for family in text_string_to_metric_families(text) for s in family.samples}


def labels(**kv) -> tuple:
    return tuple(sorted(kv.items()))


def test_requests_are_counted_by_method_route_and_status():
    m = ApiMetrics()
    m.observe_request("PUT", "/subscriptions/{subscription_id}/x", 201, 0.02)
    m.observe_request("PUT", "/subscriptions/{subscription_id}/x", 201, 0.03)
    m.observe_request("GET", "unmatched", 404, 0.001)
    s = samples(m)
    put = labels(method="PUT", route="/subscriptions/{subscription_id}/x")
    assert s[("anf_api_http_requests_total", labels(method="PUT", route="/subscriptions/{subscription_id}/x",
                                                    status="201"))] == 2
    assert s[("anf_api_http_requests_total", labels(method="GET", route="unmatched", status="404"))] == 1
    assert s[("anf_api_http_request_duration_seconds_count", put)] == 2
    assert abs(s[("anf_api_http_request_duration_seconds_sum", put)] - 0.05) < 1e-9


def test_operation_is_counted_once_with_its_duration_from_the_operation_start():
    now = [T0 + timedelta(seconds=12.5)]
    m = ApiMetrics(now=lambda: now[0])
    m.operation_finished("volumes", "create", "Succeeded", START)
    s = samples(m)
    key = labels(resource_type="volumes", action="create", result="Succeeded")
    assert s[("anf_api_operations_total", key)] == 1
    assert s[("anf_api_operation_duration_seconds_count", key)] == 1
    assert s[("anf_api_operation_duration_seconds_sum", key)] == 12.5
    bucket = dict(resource_type="volumes", action="create", result="Succeeded")
    assert s[("anf_api_operation_duration_seconds_bucket", labels(**bucket, le="10.0"))] == 0
    assert s[("anf_api_operation_duration_seconds_bucket", labels(**bucket, le="30.0"))] == 1


def test_a_wall_clock_step_back_does_not_make_a_negative_duration():
    # WSL의 벽시계는 뒤로 건너뛴다. 작업 시작 시각은 DB에 남은 벽시계 값이라 단조 시계로 잴 수 없다
    m = ApiMetrics(now=lambda: T0 - timedelta(seconds=0.4))
    m.operation_finished("snapshots", "delete", "Failed", START)
    key = labels(resource_type="snapshots", action="delete", result="Failed")
    assert samples(m)[("anf_api_operation_duration_seconds_sum", key)] == 0


def test_operations_in_progress_go_up_and_down_and_known_kinds_start_at_zero():
    m = ApiMetrics()
    m.declare_operation("volumes", "create")
    m.declare_operation("volumes", "delete")
    m.operation_started("volumes", "create")
    m.operation_started("volumes", "create")
    m.operation_stopped("volumes", "create")
    s = samples(m)
    assert s[("anf_api_operations_in_progress", labels(resource_type="volumes", action="create"))] == 1
    assert s[("anf_api_operations_in_progress", labels(resource_type="volumes", action="delete"))] == 0
