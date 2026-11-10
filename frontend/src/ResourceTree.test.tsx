import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import type { TreeNode } from "./armClient";
import { ResourceTree } from "./ResourceTree";

afterEach(cleanup);

const A1 = "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.NetApp/netAppAccounts/a1";
const GIB = 1024 ** 3;

function sample(volumeState = "Succeeded"): TreeNode[] {
  const snapshot: TreeNode = {
    resource: {
      id: `${A1}/capacityPools/p1/volumes/v1/snapshots/s1`,
      name: "a1/p1/v1/s1",
      type: "Microsoft.NetApp/netAppAccounts/capacityPools/volumes/snapshots",
      properties: { provisioningState: "Succeeded", created: "2026-11-09T09:00:00Z" },
    },
    children: [],
  };
  const volume: TreeNode = {
    resource: {
      id: `${A1}/capacityPools/p1/volumes/v1`,
      name: "a1/p1/v1",
      type: "Microsoft.NetApp/netAppAccounts/capacityPools/volumes",
      properties: {
        provisioningState: volumeState,
        creationToken: "vol-one",
        usageThreshold: 100 * GIB,
        protocolTypes: ["NFSv4.1"],
        actualThroughputMibps: 6.25,
        ...(volumeState === "Succeeded" ? { mountTargets: [{ ipAddress: "172.30.0.130" }] } : {}),
      },
    },
    children: [snapshot],
  };
  const pool: TreeNode = {
    resource: {
      id: `${A1}/capacityPools/p1`,
      name: "a1/p1",
      type: "Microsoft.NetApp/netAppAccounts/capacityPools",
      properties: {
        provisioningState: "Succeeded",
        size: 4 * 1024 * GIB,
        serviceLevel: "Premium",
        qosType: "Auto",
        totalThroughputMibps: 256,
        utilizedThroughputMibps: 6.25,
      },
    },
    children: [volume],
  };
  return [
    {
      resource: {
        id: A1,
        name: "a1",
        type: "Microsoft.NetApp/netAppAccounts",
        location: "eastus",
        properties: { provisioningState: "Succeeded" },
      },
      children: [pool],
    },
  ];
}

function row(name: string) {
  return screen.getByRole("row", { name: new RegExp(`^${name}\\b`) });
}

test("shows the hierarchy with each resource's kind, short name, and nesting level", () => {
  render(<ResourceTree tree={sample()} />);

  expect(within(row("a1")).getByText("NetApp account")).toBeTruthy();
  expect(within(row("p1")).getByText("Capacity pool")).toBeTruthy();
  expect(within(row("v1")).getByText("Volume")).toBeTruthy();
  expect(within(row("s1")).getByText("Snapshot")).toBeTruthy();
  expect(["a1", "p1", "v1", "s1"].map((n) => row(n).getAttribute("aria-level"))).toEqual(["1", "2", "3", "4"]);
  // 문서 순서가 계층 순서다
  expect(screen.getAllByRole("row").slice(1).map((r) => r.getAttribute("aria-level"))).toEqual(["1", "2", "3", "4"]);
});

test("shows provisioningState as the API gave it, classed by outcome", () => {
  const tree = sample("Creating");
  tree[0].children[0].resource.properties.provisioningState = "Failed";
  render(<ResourceTree tree={tree} />);

  expect(within(row("a1")).getByText("Succeeded").className).toContain("ok");
  expect(within(row("p1")).getByText("Failed").className).toContain("failed");
  expect(within(row("v1")).getByText("Creating").className).toContain("busy");
});

test("shows the key properties of each kind", () => {
  render(<ResourceTree tree={sample()} />);

  expect(row("a1").textContent).toContain("rg1");
  expect(row("a1").textContent).toContain("eastus");
  expect(row("p1").textContent).toContain("4 TiB");
  expect(row("p1").textContent).toContain("Premium");
  expect(row("p1").textContent).toContain("Auto QoS");
  expect(row("p1").textContent).toContain("6.25 / 256 MiB/s");
  expect(row("v1").textContent).toContain("172.30.0.130:/vol-one");
  expect(row("v1").textContent).toContain("NFSv4.1");
  expect(row("v1").textContent).toContain("100 GiB");
  expect(row("v1").textContent).toContain("6.25 MiB/s");
  expect(row("s1").textContent).toContain("2026-11-09T09:00:00Z");
});

test("a volume without mountTargets yet shows no mount path", () => {
  render(<ResourceTree tree={sample("Creating")} />);
  expect(row("v1").textContent).not.toContain(":/vol-one");
  expect(row("v1").textContent).toContain("100 GiB");
});

test("an empty tree says there are no accounts", () => {
  render(<ResourceTree tree={[]} />);
  expect(screen.getByText(/No NetApp accounts/)).toBeTruthy();
});
