import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { App } from "./App";
import type { ResourceTreeState } from "./useResourceTree";
import { useResourceTree } from "./useResourceTree";

vi.mock("./useResourceTree");
const hook = vi.mocked(useResourceTree);

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

beforeEach(() => {
  hook.mockReset();
  hook.mockReturnValue(NOTHING);
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
