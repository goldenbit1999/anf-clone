// Prometheus HTTP API의 범위 쿼리를 읽는다 (메트릭 설계 §3, FR-12).
// 브라우저는 같은 출처의 /prometheus/... 를 부르고 Vite 프록시가 Prometheus(127.0.0.1:9090)로 넘긴다.

/** 계열 하나: 라벨과 [Unix 초, 값] 점들. */
export interface Series {
  labels: Record<string, string>;
  points: [number, number][];
}

type FetchFn = (url: string) => Promise<Response>;

interface RangeResult {
  metric: Record<string, string>;
  values: [number, string][];
}

export async function queryRange(
  query: string,
  start: number,
  end: number,
  step: number,
  fetchFn: FetchFn = (url) => fetch(url),
): Promise<Series[]> {
  const params = new URLSearchParams({ query, start: String(start), end: String(end), step: String(step) });
  const response = await fetchFn(`/prometheus/api/v1/query_range?${params}`);
  if (!response.ok) throw new Error(`Prometheus query_range returned ${response.status}`);
  const body = await response.json();
  if (body.status !== "success") throw new Error(`Prometheus: ${body.error ?? "query failed"}`);
  // 값은 문자열로 온다("1048576", "NaN"). 숫자로 바꿔 차트가 쓴다
  return (body.data.result as RangeResult[]).map((r) => ({
    labels: r.metric,
    points: r.values.map(([t, v]) => [t, Number(v)]),
  }));
}
