import { expect, test, vi } from "vitest";
import { queryRange } from "./promClient";

function reply(status: number, body: unknown) {
  return vi.fn(async (_url: string) => ({ ok: status >= 200 && status < 300, status, json: async () => body }) as Response);
}

test("asks the Prometheus range API through the /prometheus proxy and turns values into numeric points", async () => {
  const fetchFn = reply(200, {
    status: "success",
    data: {
      resultType: "matrix",
      result: [
        { metric: { creation_token: "vol1", op: "read" }, values: [[1762765200, "1048576"], [1762765205, "2.5e6"]] },
      ],
    },
  });

  const series = await queryRange('rate(x{creation_token="vol1"}[20s])', 1762765000, 1762765300, 5, fetchFn);

  const url = new URL(fetchFn.mock.calls[0][0], "http://dashboard");
  expect(url.pathname).toBe("/prometheus/api/v1/query_range");
  expect(Object.fromEntries(url.searchParams)).toEqual({
    query: 'rate(x{creation_token="vol1"}[20s])',
    start: "1762765000",
    end: "1762765300",
    step: "5",
  });
  expect(series).toEqual([
    { labels: { creation_token: "vol1", op: "read" }, points: [[1762765200, 1048576], [1762765205, 2.5e6]] },
  ]);
});

test("an HTTP failure (Prometheus down behind the proxy) is an error", async () => {
  await expect(queryRange("up", 0, 300, 5, reply(502, {}))).rejects.toThrow("502");
});

test("a Prometheus error body is an error with its message", async () => {
  const fetchFn = reply(200, { status: "error", errorType: "bad_data", error: "parse error at char 3" });
  await expect(queryRange("up{", 0, 300, 5, fetchFn)).rejects.toThrow("parse error at char 3");
});
