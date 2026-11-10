import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { App } from "./App";
import type { TreeNode } from "./armClient";
import { useMetrics } from "./useMetrics";
import type { ResourceTreeState } from "./useResourceTree";
import { useResourceTree } from "./useResourceTree";

vi.mock("./useResourceTree");
vi.mock("./useMetrics");
const hook = vi.mocked(useResourceTree);
const metrics = vi.mocked(useMetrics);

const NOTHING: ResourceTreeState = { tree: null, error: null, updatedAt: null };
const ONE: ResourceTreeState = {
  tree: [
    {
      resource: {
        id: "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.NetApp/netAppAccounts/a1",
        name: "a1",
        type: "Microsoft.NetApp/netAppAccounts",
        location: "eastus",
        properties: { provisioningState: "Creating" },
      },
      children: [],
    },
  ],
  error: null,
  updatedAt: new Date("2026-11-09T09:00:00Z"),
};

const A1 = ONE.tree![0].resource.id;

/** 계정 a1 > 풀 p1 > 볼륨 v1(creationToken vol-one). */
function withVolume(state = "Succeeded"): ResourceTreeState {
  const volume: TreeNode = {
    resource: {
      id: `${A1}/capacityPools/p1/volumes/v1`,
      name: "a1/p1/v1",
      type: "Microsoft.NetApp/netAppAccounts/capacityPools/volumes",
      properties: { provisioningState: state, creationToken: "vol-one", usageThreshold: 0, protocolTypes: ["NFSv3"] },
    },
    children: [],
  };
  const pool: TreeNode = {
    resource: {
      id: `${A1}/capacityPools/p1`,
      name: "a1/p1",
      type: "Microsoft.NetApp/netAppAccounts/capacityPools",
      properties: { provisioningState: "Succeeded" },
    },
    children: [volume],
  };
  return { ...ONE, tree: [{ resource: ONE.tree![0].resource, children: [pool] }] };
}

beforeEach(() => {
  hook.mockReset();
  hook.mockReturnValue(NOTHING);
  metrics.mockReset();
  metrics.mockReturnValue({ data: null, range: null, error: null });
  window.history.replaceState(null, "", "/");
});
afterEach(cleanup);

test("without a subscription it asks for one and reads nothing", () => {
  render(<App />);
  expect(hook).toHaveBeenLastCalledWith("");
  expect(screen.getByText(/Enter a subscription ID/)).toBeTruthy();
});

test("takes the subscription from the URL", () => {
  window.history.replaceState(null, "", "/?subscription=sub1");
  hook.mockReturnValue(ONE);
  render(<App />);

  expect(hook).toHaveBeenLastCalledWith("sub1");
  expect((screen.getByLabelText("Subscription ID") as HTMLInputElement).value).toBe("sub1");
  expect(screen.getByText("Creating")).toBeTruthy();
  expect(screen.getByText(/Updated/)).toBeTruthy();
});

test("submitting the form switches the subscription and records it in the URL", () => {
  render(<App />);
  fireEvent.change(screen.getByLabelText("Subscription ID"), { target: { value: " sub2 " } });
  expect(hook).toHaveBeenLastCalledWith(""); // 입력 중에는 읽지 않는다
  fireEvent.click(screen.getByRole("button", { name: "Show" }));

  expect(hook).toHaveBeenLastCalledWith("sub2");
  expect(window.location.search).toBe("?subscription=sub2");
});

test("before the first read finishes it says loading", () => {
  window.history.replaceState(null, "", "/?subscription=sub1");
  render(<App />);
  expect(screen.getByText(/Loading/)).toBeTruthy();
});

test("a failed read shows a banner and keeps the last tree", () => {
  window.history.replaceState(null, "", "/?subscription=sub1");
  hook.mockReturnValue({ ...ONE, error: "Failed to fetch" });
  render(<App />);

  expect(screen.getByRole("alert").textContent).toContain("Failed to fetch");
  expect(screen.getByText("Creating")).toBeTruthy();
});

test("a failed first read shows the banner instead of loading", () => {
  window.history.replaceState(null, "", "/?subscription=sub1");
  hook.mockReturnValue({ ...NOTHING, error: "GET /x returned 500" });
  render(<App />);

  expect(screen.getByRole("alert").textContent).toContain("500");
  expect(screen.queryByText(/Loading/)).toBeNull();
});

test("once the tree is read the page ends with the anf-api metrics panel", () => {
  window.history.replaceState(null, "", "/?subscription=sub1");
  hook.mockReturnValue(ONE);
  render(<App />);
  expect(screen.getByRole("region", { name: "anf-api" })).toBeTruthy();
});

test("without a subscription there are no metrics panels", () => {
  render(<App />);
  expect(screen.queryByRole("region")).toBeNull();
  expect(metrics).not.toHaveBeenCalled();
});

test("choosing a volume opens its metrics panel, which closes when the volume leaves the tree", () => {
  window.history.replaceState(null, "", "/?subscription=sub1");
  hook.mockReturnValue(withVolume());
  const { rerender } = render(<App />);
  expect(screen.queryByRole("region", { name: "Volume v1" })).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "v1" }));
  expect(screen.getByRole("region", { name: "Volume v1" })).toBeTruthy();
  expect(metrics.mock.calls.some(([q]) => q?.read?.includes('creation_token="vol-one"'))).toBe(true);

  // 다음 갱신에서도 그대로다(상태가 바뀌어도 같은 볼륨이면 남는다)
  hook.mockReturnValue(withVolume("Updating"));
  rerender(<App />);
  expect(screen.getByRole("region", { name: "Volume v1" })).toBeTruthy();

  hook.mockReturnValue(ONE); // 볼륨이 지워졌다
  rerender(<App />);
  expect(screen.queryByRole("region", { name: "Volume v1" })).toBeNull();
});
