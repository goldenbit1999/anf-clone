#!/bin/bash
# compose의 init 서비스 (FR-13, 설계 _workspace/containers/02_main_design.md §1·결정 2, 스파이크 S9 P1).
# 호스트 준비를 한 번 하고 끝난다. 특권, 호스트 pid 네임스페이스, 네트워크 없음(그래서 hostname이 컨테이너 ID다).
#
# 1. scripts/setup-wsl-dataplane.sh를 호스트의 네임스페이스(nsenter -t 1 -a)에서 그대로 돌린다: 모듈, sysctl,
#    이미지 anf-nfs-server·anf-nfs-client, 네트워크 anf-vnet. 준비 로직을 compose 쪽에 한 벌 더 두지 않는다.
#    스크립트의 호스트 경로는 이 컨테이너의 /repo 바인드 원본이다(compose가 상대 경로 ..를 절대 경로로 바꿔 둔다).
# 2. 호스트의 ns를 rshared 바인드로 만든다. 그래야 storage-agent 컨테이너의 rshared 바인드가 받아들여지고, agent가
#    컨테이너 안에서 한 마운트가 호스트와 볼륨 인스턴스로 간다. agent의 ensure_shared_ns와 같은 순서다
#    (마운트 지점이 아니면 바인드하고 private로 떼어 낸 뒤 rshared). 다시 해도 바뀌는 것이 없다.
set -euo pipefail

NS=/var/lib/anf-clone/ns
self="$(hostname)"
repo="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/repo"}}{{.Source}}{{end}}{{end}}' "$self")"
[ -n "$repo" ] || { echo "init: cannot find the host path of the repository (bind mount /repo)" >&2; exit 1; }

host() { nsenter -t 1 -a -- "$@"; }

host bash "$repo/scripts/setup-wsl-dataplane.sh"

host mkdir -p "$NS"
if ! host findmnt --mountpoint "$NS" > /dev/null; then
  host mount --bind "$NS" "$NS"
  host mount --make-private "$NS"
fi
host mount --make-rshared "$NS"
echo "init: $(host findmnt -no TARGET,PROPAGATION --mountpoint "$NS" | tr '\n' ' ')"
