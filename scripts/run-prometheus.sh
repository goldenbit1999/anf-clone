#!/bin/bash
# Prometheus를 컨테이너로 띄운다 (FR-12, 메트릭 설계 §3·결정 11). WSL에서 일반 사용자(docker 그룹)나 root로 실행한다.
#
#   scripts/run-prometheus.sh        띄운다. 이미 있으면 지우고 다시 만든다(수집한 데이터는 버린다)
#   scripts/run-prometheus.sh stop   지운다
#
# host 네트워크라 127.0.0.1의 anf-api(8080)와 storage agent(8090)를 긁고 127.0.0.1:9090에서 듣는다.
# Windows에서도 WSL localhost 전달로 http://127.0.0.1:9090 에 닿는다 (대시보드의 Vite 프록시가 쓴다).
set -euo pipefail

NAME=anf-prometheus
IMAGE=prom/prometheus:v3.15.1
CONFIG="$(cd "$(dirname "$0")/.." && pwd)/deploy/prometheus/prometheus.yml"

docker rm -f "$NAME" >/dev/null 2>&1 || true
if [ "${1:-}" = stop ]; then
  exit 0
fi

docker run -d --name "$NAME" --network host \
  -v "$CONFIG:/etc/prometheus/prometheus.yml:ro" \
  "$IMAGE" --config.file=/etc/prometheus/prometheus.yml --storage.tsdb.path=/prometheus \
  --web.listen-address=127.0.0.1:9090 >/dev/null

for _ in $(seq 150); do
  if curl -sf -o /dev/null http://127.0.0.1:9090/-/ready; then
    echo "Prometheus is ready at http://127.0.0.1:9090"
    exit 0
  fi
  sleep 0.2
done
echo "Prometheus did not become ready in 30 s; see: docker logs $NAME" >&2
exit 1
