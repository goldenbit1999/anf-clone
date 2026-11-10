import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { queryRange, type Series } from "./promClient";
import { useMetrics } from "./useMetrics";

vi.mock("./promClient");
const query = vi.mocked(queryRange);

const QUERIES = { read: "rate(r[20s])", write: "rate(w[20s])" };
const NOW = 1762765300; // Unix 초

function series(value: number): Series[] {
  return [{ labels: {}, points: [[NOW, value]] }];
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW * 1000);
  query.mockReset();
});
afterEach(() => vi.useRealTimers());

test("reads every query over the last 5 minutes at a 5 s step, then again every 5 s", async () => {
  query.mockImplementation(async (q) => series(q === QUERIES.read ? 1 : 2));

  const { result } = renderHook(() => useMetrics(QUERIES));
  expect(result.current.data).toBeNull();
  await advance(0);

  expect(query).toHaveBeenCalledWith(QUERIES.read, NOW - 300, NOW, 5);
  expect(query).toHaveBeenCalledWith(QUERIES.write, NOW - 300, NOW, 5);
  expect(result.current.data).toEqual({ read: series(1), write: series(2) });
  expect(result.current.range).toEqual({ start: NOW - 300, end: NOW });
  expect(result.current.error).toBeNull();

  await advance(4999);
  expect(query).toHaveBeenCalledTimes(2);
  await advance(1);
  expect(query).toHaveBeenCalledTimes(4);
  expect(query).toHaveBeenLastCalledWith(QUERIES.write, NOW + 5 - 300, NOW + 5, 5);
});

test("reads never overlap: the 5 s wait starts when a read ends", async () => {
  let finish!: (value: Series[]) => void;
  query.mockReturnValueOnce(new Promise((resolve) => (finish = resolve))).mockResolvedValue(series(1));

  renderHook(() => useMetrics({ read: QUERIES.read }));
  await advance(20_000); // 첫 읽기가 20초째 끝나지 않는다
  expect(query).toHaveBeenCalledTimes(1);

  await act(async () => finish(series(1)));
  await advance(4999);
  expect(query).toHaveBeenCalledTimes(1);
  await advance(1);
  expect(query).toHaveBeenCalledTimes(2);
});

test("a failed read keeps the last data, shows the error, and recovers on the next success", async () => {
  query
    .mockResolvedValueOnce(series(1))
    .mockRejectedValueOnce(new Error("Prometheus query_range returned 502"))
    .mockResolvedValue(series(3));

  const { result } = renderHook(() => useMetrics({ read: QUERIES.read }));
  await advance(0);
  await advance(5000);
  expect(result.current.error).toBe("Prometheus query_range returned 502");
  expect(result.current.data).toEqual({ read: series(1) });

  await advance(5000);
  expect(result.current.error).toBeNull();
  expect(result.current.data).toEqual({ read: series(3) });
});

test("no queries means no requests", async () => {
  const { result } = renderHook(() => useMetrics(null));
  await advance(20_000);
  expect(query).not.toHaveBeenCalled();
  expect(result.current.data).toBeNull();
});

test("other queries drop the old data and ignore the old read's late answer", async () => {
  let finishOld!: (value: Series[]) => void;
  query.mockImplementation((q) =>
    q === "old" ? new Promise((resolve) => (finishOld = resolve)) : Promise.resolve(series(9)),
  );

  const { result, rerender } = renderHook(({ q }) => useMetrics({ v: q }), { initialProps: { q: "old" } });
  await advance(0);
  rerender({ q: "new" });
  await advance(0);
  expect(result.current.data).toEqual({ v: series(9) });

  await act(async () => finishOld(series(1)));
  expect(result.current.data).toEqual({ v: series(9) });
});

test("unmounting stops the polling", async () => {
  query.mockResolvedValue(series(1));
  const { unmount } = renderHook(() => useMetrics({ read: QUERIES.read }));
  await advance(0);
  unmount();
  await advance(20_000);
  expect(query).toHaveBeenCalledTimes(1);
});
