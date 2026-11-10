#!/bin/sh
# 볼륨 NFS 서버 인스턴스의 진입점 (볼륨 설계 결정 7, 16, 17, 스냅샷 설계 결정 1, 7).
# agent가 docker run의 환경 변수로 넘긴다:
#   ANF_TOKEN  creationToken. 볼륨 경로 /<token> (rootdir 아래 /export/<token>)
#   ANF_PROTO  nfs3 | nfs4.1. 이 버전만 켠다
# export 표는 agent가 쓰는 /etc/exports.d/volume.exports다(호스트 <root>/exports/<uuid>/를 읽기 전용 바인드).
# 볼륨 줄과 스냅샷 줄이 있다. agent는 스냅샷을 넣고 뺄 때 이 파일을 바꾸고 `exportfs -ra`를 부른다
set -eu

log() { echo "anf-nfs: $*"; }

# 준비 표시. agent는 이 파일이 생길 때까지 job을 끝내지 않는다 (nfs_instance.READY_FILE).
# 컨테이너 파일시스템은 docker stop·start 사이에 남으므로 시작할 때 지운다
READY=/run/anf-ready
rm -f "$READY"

[ "$(nfsconf --get exports rootdir)" = /export ] || { log "rootdir is not /export" >&2; exit 1; }
[ -f /etc/exports.d/volume.exports ] || { log "/etc/exports.d/volume.exports is missing" >&2; exit 1; }
case "$ANF_PROTO" in
  nfs3) versions="-V 3 -N 4" ;;
  nfs4.1) versions="-N 3 -N 4.0 -V 4.1 -N 4.2" ;;
  *) log "unknown protocol '$ANF_PROTO'" >&2; exit 1 ;;
esac

# rpcbind는 자기 마운트 네임스페이스에서 돈다(netns는 같다). nfsd 파일시스템을 마운트하기 전에 띄우고 /export를 떼어 낸다.
# docker rm -f(SIGKILL)에서 rpcbind가 마지막으로 끝나는 프로세스면, 그 exit가 nfsd 파일시스템을 내려 knfsd 종료가
# 시작된다. knfsd는 rpcbind에 등록 해제를 보내고, 아직 닫히지 않은 rpcbind 자신의 소켓에서 답을 기다린다(호출마다
# 10 s, 2~3분). 그동안 컨테이너가 끝나지 않아 docker rm -f가 실패했다 (FR-11 data-plane 검증 2회차).
# /export를 남기면 그 아래 볼륨 마운트가 rpcbind 쪽에 남아 볼륨 LV를 잡는다 (삭제·되돌리기의 lvremove가 실패한다)
unshare -m --propagation private sh -c 'umount -l /export && exec rpcbind -w'
mount -t nfsd nfsd /proc/fs/nfsd
# ONTAP 기본값: NFSv4 lease 30초, grace 45초 (knfsd 기본값은 90초·90초). knfsd가 돌기 전에만 바꿀 수 있다.
# 재시작 뒤 클라이언트가 상태를 되찾는 유예 기간이 짧아진다 (스냅샷 결정 1)
echo 30 > /proc/fs/nfsd/nfsv4leasetime
echo 45 > /proc/fs/nfsd/nfsv4gracetime
mkdir -p /var/lib/nfs/rpc_pipefs /var/lib/nfs/nfsdcld
mount -t rpc_pipefs rpc_pipefs /var/lib/nfs/rpc_pipefs
# 컨테이너(init 밖 netns)의 knfsd는 NFSv4 클라이언트 추적에 nfsdcld만 쓸 수 있다. 없으면 추적이 꺼지고
# 유예 기간이 돌아 그동안 v4.1 OPEN이 막힌다. 있으면 되찾을 클라이언트가 없을 때 유예를 건너뛴다.
# 기록은 컨테이너 안에 있다: docker stop·start 사이에는 남고, 인스턴스를 다시 만들면 사라진다.
nfsdcld
# mp 옵션: /export/<token>이 마운트 지점이 아니면(호스트 마운트 전) export하지 않는다
exportfs -ra
rpc.mountd

# nfsdcld가 이번 유예 기간에 되찾게 할 NFSv4 클라이언트 수. nfsdcld는 시대(epoch)마다 기록 표
# rec-<시대, 16자리 hex>를 두고, grace.recovery는 되찾을 시대다 (0이면 없음)
DB=/var/lib/nfs/nfsdcld/main.sqlite
reclaimable() {
  rec=$(sqlite3 "$DB" "select recovery from grace" 2>/dev/null) || rec=0
  if [ -z "$rec" ] || [ "$rec" = 0 ]; then echo 0; return; fi
  sqlite3 "$DB" "select count(*) from \"rec-$(printf %016x "$rec")\"" 2>/dev/null || echo 0
}

# rpc.nfsd 뒤 유예 기간(v4_end_grace = N)에는 두 경우가 있다.
# (1) 되찾을 클라이언트 기록이 있다: 재시작 전에 마운트한 NFSv4 클라이언트가 상태를 되찾는 정상 유예 기간이다.
#     모두 되찾거나 grace 45초가 지나면 끝나므로 기다린다. 죽은 클라이언트 기록이 있으면 끝까지 기다린다.
# (2) 기록이 없다: knfsd가 시작할 때 nfsdcld가 추적 파이프를 제때(약 1초) 열지 못해 추적 없이 시작했다.
#     유예 기간 동안 NFSv4 OPEN과 잠금이 막히므로 knfsd를 내렸다가 다시 띄운다(볼륨 1회차 검증: 시작의 7~8%).
# NFSv3 인스턴스도 같다: 유예 기간은 같은 netns의 NLM 잠금도 막는다
attempt=1
while :; do
  # shellcheck disable=SC2086
  rpc.nfsd $versions 4
  [ "$(cat /proc/fs/nfsd/v4_end_grace)" = Y ] && break
  clients=$(reclaimable)
  if [ "$clients" -gt 0 ]; then
    log "grace period: waiting for $clients NFSv4 client(s) to reclaim state"
    waited=0
    while [ "$(cat /proc/fs/nfsd/v4_end_grace)" != Y ]; do
      if [ "$waited" -ge 200 ]; then  # 0.5초 × 200 = 100초. grace 45초보다 넉넉하다
        log "grace period did not end after 100 s; giving up" >&2
        exit 1
      fi
      sleep 0.5
      waited=$((waited + 1))
    done
    log "grace period ended after $((waited / 2)) s"
    break
  fi
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
log "serving /$ANF_TOKEN ($ANF_PROTO): versions=$(cat /proc/fs/nfsd/versions) attempts=$attempt" \
  "lease=$(cat /proc/fs/nfsd/nfsv4leasetime) grace=$(cat /proc/fs/nfsd/nfsv4gracetime)"

# docker stop(SIGTERM): NFS 잠금·NFSv4 상태를 풀고 knfsd를 내린다 (결정 10 삭제 1단계).
# exportfs -ua는 커널 export만 지운다. 파일은 남아 다음 시작 때 그대로 적용된다
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
