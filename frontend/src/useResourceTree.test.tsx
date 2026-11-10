import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { fetchTree, type TreeNode } from "./armClient";
import { useResourceTree } from "./useResourceTree";

vi.mock("./armClient");
const load = vi.mocked(fetchTree);

function tree(state: string): TreeNode[] {
  return [{ resource: { id: "/a1", name: "a1", type: "t", properties: { provisioningState: state } }, children: [] }];
}

/** 대기 중인 promise를 흘려보낸 뒤 가짜 시계를 ms만큼 돌린다. */
async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  load.mockReset();
});
afterEach(() => vi.useRealTimers());

test("loads at once, then again every 2 s without a page reload", async () => {
  load.mockResolvedValueOnce(tree("Creating")).mockResolvedValue(tree("Succeeded"));

  const { result } = renderHook(() => useResourceTree("sub1"));
  expect(result.current.tree).toBeNull();

  await advance(0);
  expect(result.current.tree).toEqual(tree("Creating"));
  expect(result.current.updatedAt).not.toBeNull();

  await advance(1999);
  expect(load).toHaveBeenCalledTimes(1);
  await advance(1);
  expect(load).toHaveBeenCalledTimes(2);
  expect(result.current.tree).toEqual(tree("Succeeded"));
});

test("reads never overlap: the 2 s wait starts when a read ends", async () => {
  let finish!: (value: TreeNode[]) => void;
  load.mockReturnValueOnce(new Promise((resolve) => (finish = resolve))).mockResolvedValue(tree("Succeeded"));

  renderHook(() => useResourceTree("sub1"));
  await advance(10_000); // 첫 읽기가 10초째 끝나지 않는다
  expect(load).toHaveBeenCalledTimes(1);

  await act(async () => finish(tree("Creating")));
  await advance(1999);
  expect(load).toHaveBeenCalledTimes(1);
  await advance(1);
  expect(load).toHaveBeenCalledTimes(2);
});

test("a failed read keeps the last tree, shows the error, and recovers on the next success", async () => {
  load
    .mockResolvedValueOnce(tree("Creating"))
    .mockRejectedValueOnce(new Error("Failed to fetch"))
    .mockResolvedValue(tree("Succeeded"));

  const { result } = renderHook(() => useResourceTree("sub1"));
  await advance(0);
  await advance(2000);
  expect(result.current.error).toBe("Failed to fetch");
  expect(result.current.tree).toEqual(tree("Creating"));

  await advance(2000);
  expect(result.current.error).toBeNull();
  expect(result.current.tree).toEqual(tree("Succeeded"));
});

test("no subscription means no requests", async () => {
  const { result } = renderHook(() => useResourceTree(""));
  await advance(5000);
  expect(load).not.toHaveBeenCalled();
  expect(result.current.tree).toBeNull();
});

test("changing the subscription drops the old tree and ignores the old read's late answer", async () => {
  let finishOld!: (value: TreeNode[]) => void;
  load.mockImplementation((sub) =>
    sub === "old" ? new Promise((resolve) => (finishOld = resolve)) : Promise.resolve(tree("Succeeded")),
  );

  const { result, rerender } = renderHook(({ sub }) => useResourceTree(sub), { initialProps: { sub: "old" } });
  await advance(0);
  rerender({ sub: "new" });
  await advance(0);
  expect(result.current.tree).toEqual(tree("Succeeded"));

  await act(async () => finishOld(tree("Failed")));
  expect(result.current.tree).toEqual(tree("Succeeded"));
});

test("unmounting stops the polling", async () => {
  load.mockResolvedValue(tree("Succeeded"));
  const { unmount } = renderHook(() => useResourceTree("sub1"));
  await advance(0);
  unmount();
  await advance(10_000);
  expect(load).toHaveBeenCalledTimes(1);
});
