import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import { LineChart } from "./LineChart";

afterEach(cleanup);

const RANGE = { start: 1000, end: 1300 };

test("draws one line per series, scaled to the time range and the largest value", () => {
  render(
    <LineChart
      title="Throughput"
      unit="MiB/s"
      range={RANGE}
      lines={[
        { name: "write", points: [[1000, 0], [1150, 5], [1300, 10]] },
        { name: "limit", points: [[1000, 10], [1300, 10]], dashed: true },
      ]}
    />,
  );

  const lines = screen.getByRole("img", { name: "Throughput" }).querySelectorAll("polyline");
  expect(lines).toHaveLength(2);
  // 가로 300, 세로 100: 시각 1000~1300 → 0~300, 값 0~10 → 100~0
  expect(lines[0].getAttribute("points")).toBe("0,100 150,50 300,0");
  expect(lines[1].getAttribute("points")).toBe("0,0 300,0");
  expect(lines[1].getAttribute("stroke-dasharray")).toBeTruthy();
  expect(lines[0].getAttribute("stroke-dasharray")).toBeNull();
});

test("shows each line's last value and the top of the scale", () => {
  render(
    <LineChart
      title="IOPS"
      unit="/s"
      range={RANGE}
      lines={[
        { name: "requests", points: [[1000, 12], [1300, 1234.56]] },
        { name: "read ops", points: [] },
      ]}
    />,
  );
  expect(screen.getByText("requests").parentElement?.textContent).toContain("1234.6 /s");
  expect(screen.getByText("read ops").parentElement?.textContent).toContain("—");
  expect(screen.getByText(/max 1234\.6 \/s/)).toBeTruthy();
});

test("skips points Prometheus returned as NaN", () => {
  render(<LineChart title="T" unit="" range={RANGE} lines={[{ name: "x", points: [[1000, NaN], [1300, 4]] }]} />);
  expect(screen.getByRole("img", { name: "T" }).querySelector("polyline")?.getAttribute("points")).toBe("300,0");
});

test("a chart without any points says so", () => {
  render(<LineChart title="Usage" unit="GiB" range={RANGE} lines={[{ name: "used", points: [] }]} />);
  expect(screen.getByText("No data yet")).toBeTruthy();
  expect(screen.queryByRole("img", { name: "Usage" })).toBeNull();
});
