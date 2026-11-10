import { expect, test, vi } from "vitest";
import { fetchTree } from "./armClient";

const SUB = "/subscriptions/sub1";
const ACCOUNTS = `${SUB}/providers/Microsoft.NetApp/netAppAccounts`;
const A1 = `${SUB}/resourceGroups/rg1/providers/Microsoft.NetApp/netAppAccounts/a1`;
const P1 = `${A1}/capacityPools/p1`;
const V1 = `${P1}/volumes/v1`;
const V = "?api-version=2026-08-01";

function res(id: string, state = "Succeeded") {
  return { id, name: id.split("/").pop(), type: "t", properties: { provisioningState: state } };
}

/** URL → [status, body] 표로 답하는 가짜 fetch. 표에 없는 URL은 테스트 실패다. */
function fakeFetch(table: Record<string, [number, unknown]>) {
  return vi.fn(async (url: string) => {
    const hit = table[url];
    if (!hit) throw new Error(`unexpected request: ${url}`);
    return { ok: hit[0] >= 200 && hit[0] < 300, status: hit[0], json: async () => hit[1] } as Response;
  });
}

test("builds account > pool > volume > snapshot from the four list GETs", async () => {
  const fetchFn = fakeFetch({
    [`${ACCOUNTS}${V}`]: [200, { value: [res(A1)] }],
    [`${A1}/capacityPools${V}`]: [200, { value: [res(P1)] }],
    [`${P1}/volumes${V}`]: [200, { value: [res(V1, "Creating")] }],
    [`${V1}/snapshots${V}`]: [200, { value: [res(`${V1}/snapshots/s1`)] }],
  });

  const tree = await fetchTree("sub1", fetchFn);

  expect(tree).toHaveLength(1);
  const volume = tree[0].children[0].children[0];
  expect(tree[0].resource.id).toBe(A1);
  expect(volume.resource.properties.provisioningState).toBe("Creating");
  expect(volume.children.map((s) => s.resource.id)).toEqual([`${V1}/snapshots/s1`]);
  expect(volume.children[0].children).toEqual([]);
});

test("an empty subscription gives an empty tree", async () => {
  const fetchFn = fakeFetch({ [`${ACCOUNTS}${V}`]: [200, { value: [] }] });
  expect(await fetchTree("sub1", fetchFn)).toEqual([]);
});

test("the subscription id is URL-encoded", async () => {
  const fetchFn = fakeFetch({
    [`/subscriptions/a%2Fb/providers/Microsoft.NetApp/netAppAccounts${V}`]: [200, { value: [] }],
  });
  expect(await fetchTree("a/b", fetchFn)).toEqual([]);
});

test("a child list 404 (parent deleted mid-read) is an empty list, not a failure", async () => {
  const fetchFn = fakeFetch({
    [`${ACCOUNTS}${V}`]: [200, { value: [res(A1, "Deleting")] }],
    [`${A1}/capacityPools${V}`]: [404, { error: { code: "ResourceNotFound" } }],
  });
  const tree = await fetchTree("sub1", fetchFn);
  expect(tree[0].children).toEqual([]);
});

test("any other status fails the whole read", async () => {
  const fetchFn = fakeFetch({
    [`${ACCOUNTS}${V}`]: [200, { value: [res(A1)] }],
    [`${A1}/capacityPools${V}`]: [500, {}],
  });
  await expect(fetchTree("sub1", fetchFn)).rejects.toThrow("500");
});

test("a 404 on the account list fails the read", async () => {
  const fetchFn = fakeFetch({ [`${ACCOUNTS}${V}`]: [404, {}] });
  await expect(fetchTree("sub1", fetchFn)).rejects.toThrow("404");
});
