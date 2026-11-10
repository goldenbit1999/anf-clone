// 볼륨 차트와 API 차트 (메트릭 설계 §3). 값은 Prometheus에서만 읽는다(D-08).
import type { ReactNode } from "react";
import { LineChart, type Line } from "./LineChart";
import type { Series } from "./promClient";
import { useMetrics, type MetricsState } from "./useMetrics";

const MIB = 1024 ** 2;
const GIB = 1024 ** 3;

type Data = Record<string, Series[]>;
type Range = { start: number; end: number };

/** 쿼리 하나의 첫 계열을 이름 붙은 선으로. 값은 factor로 나눠 표시 단위로 바꾼다. */
function line(data: Data, key: string, name: string, factor = 1, dashed = false): Line {
  const points = data[key]?.[0]?.points ?? [];
  return { name, points: points.map(([t, v]) => [t, v / factor]), dashed };
}

/** 라벨별로 나뉜 계열을 각각 선으로(예: op="read" → "read ops"). */
function linesBy(data: Data, key: string, label: string, suffix = ""): Line[] {
  return (data[key] ?? []).map((s) => ({ name: `${s.labels[label]}${suffix}`, points: s.points }));
}

function Panel({ title, state, children }: { title: string; state: MetricsState; children: (data: Data, range: Range) => ReactNode }) {
  const { data, range, error } = state;
  return (
    <section className="metrics" aria-label={title}>
      <h2>{title}</h2>
      {error && (
        <p role="alert" className="banner">
          Cannot read metrics: {error}. {data && "Showing the last successful read. "}Retrying every 5 s.
        </p>
      )}
      {!data && !error && <p className="empty">Loading metrics…</p>}
      {data && range && <div className="charts">{children(data, range)}</div>}
    </section>
  );
}

/**
 * 볼륨 하나의 처리량·IOPS·사용량. ARM 볼륨의 creationToken을 agent의 creation_token 라벨과 잇는다(설계 결정 9).
 * 쿼리마다 sum으로 묶는다: 볼륨을 지우고 같은 경로로 다시 만들면 volume_uuid가 다른 계열이 5분 창 안에 겹쳐 보이기 때문이다.
 */
export function VolumeMetrics({ name, token }: { name: string; token: string }) {
  const sel = `{creation_token="${token}"}`;
  const state = useMetrics({
    read: `sum(rate(anf_volume_read_bytes_total${sel}[20s]))`,
    write: `sum(rate(anf_volume_write_bytes_total${sel}[20s]))`,
    limit: `sum(anf_volume_throughput_limit_bytes_per_second${sel})`,
    requests: `sum(rate(anf_volume_nfs_requests_total${sel}[20s]))`,
    // NFSv4.1 볼륨에만 있다. NFSv3 볼륨은 계열이 없어 선도 없다(설계 결정 5)
    ops: `sum by (op) (rate(anf_volume_nfs_operations_total${sel}[20s]))`,
    used: `sum(anf_volume_used_bytes${sel})`,
    size: `sum(anf_volume_size_bytes${sel})`,
  });

  return (
    <Panel title={`Volume ${name}`} state={state}>
      {(data, range) => (
        <>
          <LineChart
            title="Throughput"
            unit="MiB/s"
            range={range}
            lines={[line(data, "read", "read", MIB), line(data, "write", "write", MIB), line(data, "limit", "limit", MIB, true)]}
          />
          <LineChart
            title="IOPS"
            unit="/s"
            range={range}
            lines={[line(data, "requests", "requests"), ...linesBy(data, "ops", "op", " ops")]}
          />
          <LineChart
            title="Usage"
            unit="GiB"
            range={range}
            lines={[line(data, "used", "used", GIB), line(data, "size", "size", GIB, true)]}
          />
        </>
      )}
    </Panel>
  );
}

/** anf-api의 요청률(상태 코드별)과 진행 중인 비동기 작업 수. */
export function ApiMetrics() {
  const state = useMetrics({
    requests: "sum by (status) (rate(anf_api_http_requests_total[20s]))",
    inProgress: "sum(anf_api_operations_in_progress)",
  });

  return (
    <Panel title="anf-api" state={state}>
      {(data, range) => (
        <>
          <LineChart title="Requests" unit="/s" range={range} lines={linesBy(data, "requests", "status")} />
          <LineChart title="Operations in progress" unit="" range={range} lines={[line(data, "inProgress", "in progress")]} />
        </>
      )}
    </Panel>
  );
}
