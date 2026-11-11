---
paths:
  - "backend/storage_agent/volume_metrics.py"
  - "backend/anf_api/api_metrics.py"
  - "backend/tests/**/*metrics*.py"
  - "deploy/prometheus/**"
  - "scripts/run-prometheus.sh"
  - "frontend/src/promClient*"
  - "frontend/src/useMetrics*"
  - "frontend/src/MetricsPanels*"
  - "frontend/src/LineChart*"
---

# Metrics decisions (FR-12)

- Metrics (FR-12, spike S8 `_workspace/spikes/S8.md`): the storage agent and anf-api each serve `GET /metrics` (Prometheus text, `prometheus_client`); Prometheus runs as a container (`prom/prometheus:v3.15.1`, host network, `127.0.0.1:9090`, 5 s scrape) and the dashboard reads only its query API. The agent reads everything at scrape time and changes nothing: per-volume read/write bytes from the knfsd `io` line and request counts from the `rpc` line of `/proc/<instance pid>/net/rpc/nfsd` (per network namespace, so per volume; `io` equals fio's bytes exactly), read/write operation counts from `proc4ops` for NFSv4.1 volumes only (the `proc3` line is the sum over all namespaces, so an NFSv3 volume gets no per-volume read/write ops), usage and inodes from `statvfs`, the limit from the `anf_qos` tag, and aggregate (thin pool) usage from `dmsetup status`. Names follow Prometheus conventions (`anf_volume_write_bytes_total`, …; raw counters, `rate()` in queries), with labels `volume_uuid`, `creation_token`, `protocol`; the dashboard joins on `creationToken`. Differences from ANF's Azure Monitor metrics: volume used size excludes snapshot space (it shows up in the aggregate metric instead), throughput is data bytes without metadata, ANF's values are 5-minute averages, and there is no latency or throughput-limit-reached metric (HTB `overlimits` rises even at half load). Instance restarts reset the knfsd counters; `rate()` handles it. anf-api counts requests by route template (never raw paths) and operations by handler key and result, with an in-progress gauge. Design: `_workspace/metrics/02_main_design.md`.
