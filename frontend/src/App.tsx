import { useState } from "react";
import { ResourceTree } from "./ResourceTree";
import { useResourceTree } from "./useResourceTree";

// 구독 ID는 URL에 둔다. 새로 고침과 링크로 유지된다 (대시보드 설계 결정 4).
function subscriptionFromUrl(): string {
  return new URLSearchParams(window.location.search).get("subscription") ?? "";
}

export function App() {
  const [subscriptionId, setSubscriptionId] = useState(subscriptionFromUrl);
  const [draft, setDraft] = useState(subscriptionId);
  const { tree, error, updatedAt } = useResourceTree(subscriptionId);

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
      {tree && <ResourceTree tree={tree} />}
      {updatedAt && <p className="updated">Updated {updatedAt.toLocaleTimeString()} · refreshes every 2 s</p>}
    </main>
  );
}
