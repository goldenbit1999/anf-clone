// 의존성 없는 SVG 선 차트 (메트릭 설계 결정 12). 가로는 조회 범위, 세로는 0부터 가장 큰 값까지다.
// 축 눈금 대신 세로 최댓값과 선마다 마지막 값을 숫자로 보인다.

export interface Line {
  name: string;
  points: [number, number][]; // [Unix 초, 값]
  dashed?: boolean; // 처리량 한도처럼 기준선인 것
}

interface Props {
  title: string;
  unit: string;
  range: { start: number; end: number };
  lines: Line[];
}

const WIDTH = 300;
const HEIGHT = 100;

/** 1 이상은 소수 한 자리, 그 밑은 세 자리(0.062 MiB/s 같은 한도). 뒤의 0은 뗀다. */
function format(value: number, unit: string): string {
  return `${Number(value.toFixed(Math.abs(value) < 1 ? 3 : 1))} ${unit}`.trim();
}

/** 좌표는 소수 한 자리까지만 쓴다. */
function coord(value: number): string {
  return String(Number(value.toFixed(1)));
}

export function LineChart({ title, unit, range, lines }: Props) {
  // Prometheus는 값을 계산할 수 없을 때 "NaN"을 준다(예: 0/0). 그런 점은 그리지 않는다
  const finite = lines.map((line) => line.points.filter(([, v]) => Number.isFinite(v)));
  const values = finite.flat().map(([, v]) => v);
  const top = values.length ? Math.max(...values) : 0;
  const span = range.end - range.start || 1;
  const x = (t: number) => coord(((t - range.start) / span) * WIDTH);
  const y = (v: number) => coord(HEIGHT - (v / (top || 1)) * HEIGHT);

  return (
    <figure className="chart">
      <figcaption>{title}</figcaption>
      {values.length === 0 ? (
        <p className="empty">No data yet</p>
      ) : (
        <>
          <span className="chart-top">{`max ${format(top, unit)}`}</span>
          <svg role="img" aria-label={title} viewBox={`0 0 ${WIDTH} ${HEIGHT}`} preserveAspectRatio="none">
            {finite.map((points, i) =>
              points.length === 0 ? null : (
                <polyline
                  key={lines[i].name}
                  points={points.map(([t, v]) => `${x(t)},${y(v)}`).join(" ")}
                  style={{ stroke: `var(--series-${i % 4})` }}
                  strokeDasharray={lines[i].dashed ? "6 4" : undefined}
                />
              ),
            )}
          </svg>
        </>
      )}
      <ul className="legend">
        {lines.map((line, i) => {
          const last = finite[i].at(-1);
          return (
            <li key={line.name}>
              <i className="swatch" style={{ background: `var(--series-${i % 4})` }} />
              <span>{line.name}</span> <b>{last ? format(last[1], unit) : "—"}</b>
            </li>
          );
        })}
      </ul>
    </figure>
  );
}
