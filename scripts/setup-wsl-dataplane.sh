#!/bin/bash
# WSL Ubuntu 데이터 플레인 일회성 준비 (볼륨 설계 §6.1). root로 실행하고, 다시 실행해도 된다:
#   MSYS_NO_PATHCONV=1 wsl -d Ubuntu -u root -e bash /mnt/c/<repo>/scripts/setup-wsl-dataplane.sh
# 이름은 WSL이지만 Ubuntu 24.04 호스트(GitHub 호스트 러너 포함)에서도 그대로 쓴다: CI data-plane 작업이 sudo로 부른다 (S3).
# storage agent는 시작할 때 이 준비가 됐는지 확인하고, 아니면 뜨지 않는다 (nfs_instance.check_host).
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
NET=anf-vnet
SUBNET=172.30.0.0/24
GATEWAY=172.30.0.1
IP_RANGE=172.30.0.0/25 # Docker가 클라이언트 컨테이너에 주는 범위. 볼륨 IP .129~.254는 agent가 정한다 (결정 18)

[ "$(id -u)" = 0 ] || { echo "run as root (wsl -d Ubuntu -u root ...)" >&2; exit 1; }
# iptables·nsenter: 되돌리는 동안 볼륨 인스턴스 netns의 입력을 막는다 (되돌리기 결정 3)
# ip·tc: 볼륨 인스턴스 netns에 처리량 한도(IFB + HTB)를 건다 (처리량 결정 9)
for cmd in lvcreate thin_check mkfs.ext4 docker iptables nsenter ip tc; do
  command -v "$cmd" >/dev/null || {
    echo "missing $cmd: apt-get install lvm2 thin-provisioning-tools e2fsprogs docker.io iptables util-linux" \
      "iproute2" >&2
    exit 1; }
done
# 볼륨 인스턴스(컨테이너)의 knfsd는 호스트 커널의 nfsd 모듈을 쓴다. 호스트 nfs-server는 볼륨에 쓰지 않는다
modprobe nfsd
modprobe dm_thin_pool

# NFSv4 delegation을 끈다. 켜져 있으면 되돌린 뒤에도 v4.1 클라이언트가 열어 둔 파일에서 되돌리기 전 캐시를
# 16~32 s 읽는다 (S5). knfsd는 lease를 못 얻으면 delegation을 주지 않는다. WSL 재시작 뒤에도 남게 파일로 둔다
sysctl -qw fs.leases-enable=0
echo "fs.leases-enable = 0" > /etc/sysctl.d/90-anf-clone.conf

docker build -q -t anf-nfs-server "$REPO/backend/storage_agent/nfs_server" >/dev/null
# 검증용 NFS 클라이언트 (통합·E2E 테스트, 볼륨 설계 §8). fio: 처리량 한도 측정 (처리량 결정 19)
docker build -q -t anf-nfs-client - >/dev/null <<'EOF'
FROM alpine:3.20
RUN apk add --no-cache nfs-utils coreutils fio
EOF

if docker network inspect "$NET" >/dev/null 2>&1; then
  got="$(docker network inspect "$NET" -f '{{range .IPAM.Config}}{{.Subnet}} {{.IPRange}}{{end}}')"
  if [ "$got" != "$SUBNET $IP_RANGE" ]; then
    echo "network $NET exists with '$got', expected '$SUBNET $IP_RANGE'." >&2
    echo "Remove its containers and the network (docker network rm $NET), then run this again." >&2
    exit 1
  fi
else
  docker network create --subnet "$SUBNET" --gateway "$GATEWAY" --ip-range "$IP_RANGE" "$NET" >/dev/null
fi

# 앞선 구현 단계(호스트 knfsd가 export하던 방식)가 남긴 설정을 지운다
rm -f /etc/nfs.conf.d/anf-clone.conf /etc/exports.d/anf-clone.exports

echo "data plane ready: images anf-nfs-server, anf-nfs-client; network $NET ($SUBNET, ip-range $IP_RANGE);" \
  "NFSv4 delegations off"
