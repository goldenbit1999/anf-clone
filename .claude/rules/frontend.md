---
paths:
  - "frontend/**"
---

# Architecture: `frontend/src/`

Commands are in the root `CLAUDE.md` ("Dashboard").

- **Architecture (`frontend/src/`)**: a read-only dashboard (FR-09). `armClient.ts` reads the whole tree with the four list GETs (accounts in the subscription → pools → volumes → snapshots; a child list `404` is an empty list, any other failure fails the read). `useResourceTree.ts` polls it every 2 s without overlap, keeps the last good tree on failure, and drops answers for an old subscription. `ResourceTree.tsx` renders the rows and the `provisioningState` badge (the API's string as is). `App.tsx` has the subscription input (kept in the URL) and the error banner. Charts (FR-12): clicking a `Succeeded` volume opens its panel (`MetricsPanels.tsx`) with throughput (plus the limit line), IOPS, and usage, and an anf-api panel shows request rate and operations in progress. `promClient.ts` calls `query_range` through the `/prometheus` proxy (`ANF_PROMETHEUS_URL`, default `http://127.0.0.1:9090`), `useMetrics.ts` polls every 5 s over the last 5 minutes with `rate(...[20s])`, and `LineChart.tsx` draws SVG without a chart library. Without Prometheus the charts show an error and the tree keeps working. It cannot show why a resource is `Failed`: the error is only in the operation status, whose URL only the requester knows. Design: `_workspace/dashboard/02_main_design.md`.
