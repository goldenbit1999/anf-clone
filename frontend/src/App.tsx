import { useState } from "react";
import type { ArmResource, TreeNode } from "./armClient";
import { ApiMetrics, VolumeMetrics } from "./MetricsPanels";
import { ResourceTree } from "./ResourceTree";
import { useResourceTree } from "./useResourceTree";

// 구독 ID는 URL에 둔다. 새로 고침과 링크로 유지된다 (대시보드 설계 결정 4).
function subscriptionFromUrl(): string {
  return new URLSearchParams(window.location.search).get("subscription") ?? "";
}

/** 고른 볼륨을 최신 트리에서 찾는다. 지워졌거나 구독이 바뀌었으면 없다. */
function findResource(nodes: TreeNode[], id: string): ArmResource | undefined {
  for (const { resource, children } of nodes) {
    if (resource.id === id) return resource;
    const found = findResource(children, id);
    if (found) return found;
  }
  return undefined;
}

export function App() {
  const [subscriptionId, setSubscriptionId] = useState(subscriptionFromUrl);
  const [draft, setDraft] = useState(subscriptionId);
  const { tree, error, updatedAt } = useResourceTree(subscriptionId);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = tree && selectedId ? findResource(tree, selectedId) : undefined;

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const next = draft.trim();
    window.history.replaceState(null, "", next ? `?subscription=${encodeURIComponent(next)}` : window.location.pathname);
    setSubscriptionId(next);
  }

  return (
    <main>
      <header>
        <h1>ANF clone</h1>
        <form onSubmit={submit}>
          <label htmlFor="subscription">Subscription ID</label>
          <input id="subscription" value={draft} onChange={(e) => setDraft(e.target.value)} size={40} />
          <button type="submit">Show</button>
        </form>
      </header>

      {error && (
        <p role="alert" className="banner">
          Cannot read from anf-api: {error}. {tree && "Showing the last successful read. "}Retrying every 2 s.
        </p>
      )}

      {!subscriptionId && <p className="empty">Enter a subscription ID to list its NetApp resources.</p>}
      {subscriptionId && !tree && !error && <p className="empty">Loading…</p>}
      {tree && <ResourceTree tree={tree} onSelect={(volume) => setSelectedId(volume.id)} />}
      {updatedAt && <p className="updated">Updated {updatedAt.toLocaleTimeString()} · refreshes every 2 s</p>}

      {/* 메트릭은 Prometheus에서 읽는다. Prometheus가 없어도 위의 트리는 그대로 갱신된다 (메트릭 설계 §3) */}
      {selected && (
        <VolumeMetrics
          key={selected.id}
          name={selected.name.split("/").pop() ?? ""}
          token={String(selected.properties.creationToken)}
        />
      )}
      {tree && <ApiMetrics />}
    </main>
  );
}
