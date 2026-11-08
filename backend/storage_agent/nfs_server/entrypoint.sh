#!/bin/sh
# 볼륨 NFS 서버 인스턴스의 진입점 (볼륨 설계 결정 7, 16, 17).
# agent가 docker run의 환경 변수로 넘긴다:
#   ANF_TOKEN  creationToken. export 경로 /<token> (rootdir 아래 /export/<token>)
#   ANF_FSID   fileSystemId. export의 fsid
#   ANF_PROTO  nfs3 | nfs4.1. 이 버전만 켠다
set -eu

log() { echo "anf-nfs: $*"; }

# 준비 표시. agent는 이 파일이 생길 때까지 job을 끝내지 않는다 (nfs_instance.READY_FILE).
# 컨테이너 파일시스템은 docker stop·start 사이에 남으므로 시작할 때 지운다
READY=/run/anf-ready
rm -f "$READY"

[ "$(nfsconf --get exports rootdir)" = /export ] || { log "rootdir is not /export" >&2; exit 1; }
case "$ANF_PROTO" in
  nfs3) versions="-V 3 -N 4" ;;
  nfs4.1) versions="-N 3 -N 4.0 -V 4.1 -N 4.2" ;;
  *) log "unknown protocol '$ANF_PROTO'" >&2; exit 1 ;;
esac

mount -t nfsd nfsd /proc/fs/nfsd
mkdir -p /var/lib/nfs/rpc_pipefs /var/lib/nfs/nfsdcld
mount -t rpc_pipefs rpc_pipefs /var/lib/nfs/rpc_pipefs
# 컨테이너(init 밖 netns)의 knfsd는 NFSv4 클라이언트 추적에 nfsdcld만 쓸 수 있다. 없으면 추적이 꺼지고
# 90초 유예 기간이 돌아 그동안 v4.1 OPEN이 막힌다. 있으면 되찾을 클라이언트가 없을 때 유예를 건너뛴다.
# 기록은 컨테이너 안에만 있다: 인스턴스를 다시 만들면 이전 NFSv4 상태는 되찾을 수 없다.
nfsdcld
rpcbind -w
# ANF 기본 export 규칙: 모든 클라이언트, 읽기·쓰기, root 허용. 클라이언트는 `*`로 쓴다.
# `0.0.0.0/0`은 어떤 클라이언트와도 맞지 않았다 (mountd "unmatched host", 구현 중 확인).
# mp: /export/<token>이 마운트 지점이 아니면(호스트 마운트 전) export하지 않는다
exportfs -o "rw,sync,no_subtree_check,no_root_squash,secure,crossmnt,mp,fsid=$ANF_FSID" "*:/$ANF_TOKEN"
rpc.mountd
# knfsd가 시작할 때 커널은 nfsdcld가 추적 파이프를 열기를 잠깐(약 1초)만 기다린다. 그 안에 못 열면 추적 없이
# 90초 유예 기간이 돌고, 그동안 NFSv4 OPEN과 잠금이 막힌다(1회차 검증: 인스턴스 시작의 7~8%).
# 유예 기간이 끝났는지(v4_end_grace = Y) 확인하고, 아니면 knfsd를 내렸다가 다시 띄운다. NFSv3 인스턴스도 같다:
# 유예 기간은 같은 netns의 NLM 잠금도 막는다
attempt=1
while :; do
  # shellcheck disable=SC2086
  rpc.nfsd $versions 4
  [ "$(cat /proc/fs/nfsd/v4_end_grace)" = Y ] && break
  if [ "$attempt" -ge 5 ]; then
    log "NFSv4 client tracking did not start after $attempt attempts; giving up" >&2
    exit 1
  fi
  log "NFSv4 client tracking did not start (attempt $attempt); restarting knfsd" >&2
  rpc.nfsd 0
  sleep 1
  attempt=$((attempt + 1))
done
touch "$READY"
log "serving /$ANF_TOKEN ($ANF_PROTO): versions=$(cat /proc/fs/nfsd/versions) attempts=$attempt"

# docker stop(SIGTERM): NFS 잠금·NFSv4 상태를 풀고 knfsd를 내린다 (결정 10 삭제 1단계)
stop() {
  rm -f "$READY"
  echo "/export/$ANF_TOKEN" > /proc/fs/nfsd/unlock_filesystem || true
  rpc.nfsd 0
  exportfs -ua
  log "stopped"
  exit 0
}
trap stop TERM INT
while :; do
  sleep 3600 &
  wait $!
done
