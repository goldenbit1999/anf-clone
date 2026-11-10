import { useEffect, useState } from "react";
import { queryRange, type Series } from "./promClient";

export const METRICS_POLL_MS = 5000; // Prometheus가 5초마다 긁는다 (메트릭 설계 §3)
export const RANGE_SECONDS = 300; // 최근 5분
export const STEP_SECONDS = 5;

export interface MetricsState {
  /** 이름 → 계열. 마지막으로 성공한 읽기. 아직 한 번도 성공하지 못했으면 null. */
  data: Record<string, Series[]> | null;
  /** data를 읽은 시간 범위(Unix 초). 차트의 가로축이다. */
  range: { start: number; end: number } | null;
  /** 가장 최근 읽기가 실패했으면 그 메시지. 다음 성공에서 null로 돌아간다. */
  error: string | null;
}

const EMPTY: MetricsState = { data: null, range: null, error: null };

/**
 * 이름 붙은 PromQL 쿼리들을 최근 5분 범위로 5초마다 다시 읽는다.
 * useResourceTree처럼 한 번의 읽기가 끝난 뒤에 기다리므로 요청이 겹치지 않고, 실패하면 마지막 값을 두고 오류만 알린다.
 * 쿼리가 null이면 읽지 않는다. 쿼리 객체는 내용으로 비교한다(렌더마다 새로 만들어도 된다).
 */
export function useMetrics(queries: Record<string, string> | null): MetricsState {
  const [state, setState] = useState(EMPTY);
  const key = queries === null ? "" : JSON.stringify(queries);

  useEffect(() => {
    setState(EMPTY);
    if (!key) return;
    const named: Record<string, string> = JSON.parse(key);
    let stopped = false; // 쿼리가 바뀌거나 화면이 닫힌 뒤 도착한 응답은 버린다
    let timer: ReturnType<typeof setTimeout>;

    async function poll() {
      const end = Math.floor(Date.now() / 1000);
      const start = end - RANGE_SECONDS;
      try {
        const entries = await Promise.all(
          Object.entries(named).map(async ([name, q]) => [name, await queryRange(q, start, end, STEP_SECONDS)]),
        );
        if (stopped) return;
        setState({ data: Object.fromEntries(entries), range: { start, end }, error: null });
      } catch (e) {
        if (stopped) return;
        setState((last) => ({ ...last, error: e instanceof Error ? e.message : String(e) }));
      }
      timer = setTimeout(poll, METRICS_POLL_MS);
    }

    poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [key]);

  return state;
}
