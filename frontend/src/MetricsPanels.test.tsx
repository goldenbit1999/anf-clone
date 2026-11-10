import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { ApiMetrics, VolumeMetrics } from "./MetricsPanels";
import type { Series } from "./promClient";
import { useMetrics, type MetricsState } from "./useMetrics";

vi.mock("./useMetrics");
const hook = vi.mocked(useMetrics);

const MIB = 1024 ** 2;
const GIB = 1024 ** 3;
const RANGE = { start: 1000, end: 1300 };

function one(value: number, labels: Record<string, string> = {}): Series {
  return { labels, points: [[1000, 0], [1300, value]] };
}

function loaded(data: Record<string, Series[]>): MetricsState {
  return { data, range: RANGE, error: null };
}

const V41: Record<string, Series[]> = {
  read: [one(2 * MIB)],
  write: [one(8 * MIB)],
  limit: [one(10 * MIB)],
  requests: [one(1500)],
  ops: [one(1200, { op: "read" }), one(300, { op: "write" })],
  used: [one(1.5 * GIB)],
  size: [one(98.4 * GIB)],
};

/** 범례 항목 "이름 값". */
function legend(name: string): string | undefined {
  return screen.getByText(name).parentElement?.textContent ?? undefined;
}

beforeEach(() => {
  hook.mockReset();
  hook.mockReturnValue({ data: null, range: null, error: null });
});
afterEach(cleanup);

test("a volume panel asks Prometheus for that volume's series by creation token", () => {
  render(<VolumeMetrics name="v1" token="vol-one" />);
  const sel = '{creation_token="vol-one"}';
  expect(hook).toHaveBeenLastCalledWith({
    read: `sum(rate(anf_volume_read_bytes_total${sel}[20s]))`,
    write: `sum(rate(anf_volume_write_bytes_total${sel}[20s]))`,
    limit: `sum(anf_volume_throughput_limit_bytes_per_second${sel})`,
    requests: `sum(rate(anf_volume_nfs_requests_total${sel}[20s]))`,
    ops: `sum by (op) (rate(anf_volume_nfs_operations_total${sel}[20s]))`,
    used: `sum(anf_volume_used_bytes${sel})`,
    size: `sum(anf_volume_size_bytes${sel})`,
  });
  expect(screen.getByText(/Loading metrics/)).toBeTruthy();
});

test("throughput is in MiB/s with the limit as a dashed line, usage in GiB", () => {
  hook.mockReturnValue(loaded(V41));
  render(<VolumeMetrics name="v1" token="vol-one" />);

  expect(legend("read")).toContain("2 MiB/s");
  expect(legend("write")).toContain("8 MiB/s");
  expect(legend("limit")).toContain("10 MiB/s");
  const throughput = screen.getByRole("img", { name: "Throughput" });
  expect(throughput.querySelectorAll("polyline")[2].getAttribute("stroke-dasharray")).toBeTruthy();

  expect(legend("used")).toContain("1.5 GiB");
  expect(legend("size")).toContain("98.4 GiB");
});

test("IOPS shows NFS requests, plus read and write operations when the volume has them (NFSv4.1)", () => {
  hook.mockReturnValue(loaded(V41));
  render(<VolumeMetrics name="v1" token="vol-one" />);
  expect(legend("requests")).toContain("1500 /s");
  expect(legend("read ops")).toContain("1200 /s");
  expect(legend("write ops")).toContain("300 /s");
});

test("an NFSv3 volume has no operation series, so IOPS shows requests only", () => {
  hook.mockReturnValue(loaded({ ...V41, ops: [] }));
  render(<VolumeMetrics name="v1" token="vol-one" />);
  expect(legend("requests")).toContain("1500 /s");
  expect(screen.queryByText("read ops")).toBeNull();
});

test("a failed read shows the error and keeps the charts of the last good read", () => {
  hook.mockReturnValue({ ...loaded(V41), error: "Prometheus query_range returned 502" });
  render(<VolumeMetrics name="v1" token="vol-one" />);
  expect(screen.getByRole("alert").textContent).toContain("Cannot read metrics: Prometheus query_range returned 502");
  expect(screen.getByRole("img", { name: "Throughput" })).toBeTruthy();
});

test("a failed first read shows only the error", () => {
  hook.mockReturnValue({ data: null, range: null, error: "Failed to fetch" });
  render(<VolumeMetrics name="v1" token="vol-one" />);
  expect(screen.getByRole("alert").textContent).toContain("Cannot read metrics: Failed to fetch");
  expect(screen.queryByText(/Loading metrics/)).toBeNull();
  expect(screen.queryByRole("img")).toBeNull();
});

test("the API panel shows request rates by status and operations in progress", () => {
  hook.mockReturnValue(
    loaded({ requests: [one(4, { status: "200" }), one(0.5, { status: "202" })], inProgress: [one(1)] }),
  );
  render(<ApiMetrics />);

  expect(hook).toHaveBeenLastCalledWith({
    requests: "sum by (status) (rate(anf_api_http_requests_total[20s]))",
    inProgress: "sum(anf_api_operations_in_progress)",
  });
  expect(legend("200")).toContain("4 /s");
  expect(legend("202")).toContain("0.5 /s");
  expect(legend("in progress")).toContain("1");
});
