#!/bin/bash
# Check the T1n layout the volume design will use:
#  host: <root>/ns/<token> is a mounted fs; instance container binds <root>/ns -> /export (rslave)
#  instance nfs.conf [exports] rootdir=/export, export "/<token>" with mp,fsid; clients "*"
#  Q1: v3 and v4.1 both mount <ip>:/<token>
#  Q2: per-instance NFS versions (v3-only instance refuses v4.1, v4.1-only refuses v3 and v4.0)
#  Q3: a filesystem mounted on the host under ns/<token> AFTER the instance started is visible to clients
set -uo pipefail
R=/var/lib/anf-clone/spike-s2b
NET=s2-net

up_fs() {  # token
  truncate -s 256M "$R/$1.img"; mkfs.ext4 -q -F "$R/$1.img"
  mkdir -p "$R/ns/$1"; mount -o loop,nodelalloc "$R/$1.img" "$R/ns/$1"
  echo "hello-$1" > "$R/ns/$1/hello.txt"
}
instance() {  # name ip token fsid nfsd-version-args
  docker rm -f "$1" >/dev/null 2>&1
  docker run -d --name "$1" --network $NET --ip "$2" --privileged \
    --mount "type=bind,src=$R/ns,dst=/export,bind-propagation=rslave" anf-s2-client:spike sleep infinity >/dev/null
  docker exec "$1" sh -c "
    set -e
    printf '[exports]\nrootdir=/export\n' > /etc/nfs.conf
    mount -t nfsd nfsd /proc/fs/nfsd
    mkdir -p /var/lib/nfs/rpc_pipefs /var/lib/nfs/v4recovery
    rpcbind -w
    exportfs -o rw,sync,no_subtree_check,no_root_squash,secure,crossmnt,mp,fsid=$4 '*:/$3'
    rpc.mountd
    rpc.nfsd $5 4
    echo Y > /proc/fs/nfsd/v4_end_grace 2>/dev/null || true
    echo \"$1: versions=\$(cat /proc/fs/nfsd/versions) exports=\$(exportfs | tr -s ' \n' ' ')\""
}
try() {  # label ip path opts
  if out=$(timeout 30 docker exec s2-vc sh -c "mkdir -p /m && mount -t nfs -o $4,retry=0,timeo=50,retrans=1 $2:$3 /m && cat /m/hello.txt; r=\$?; umount /m 2>/dev/null; exit \$r" 2>&1); then
    echo "  $1: OK ($out)"; else echo "  $1: FAIL ($(echo "$out" | tail -1))"; fi
}

case "${1:-run}" in
run)
  mkdir -p "$R/ns"
  # WSL's / is a private mount; make ns its own shared mount so later mounts under it
  # propagate into instance containers (rslave).
  mountpoint -q "$R/ns" || mount --bind "$R/ns" "$R/ns"
  mount --make-rshared "$R/ns"
  findmnt -no TARGET,PROPAGATION "$R/ns"
  docker network inspect $NET >/dev/null 2>&1 || docker network create --subnet 172.31.0.0/24 --ip-range 172.31.0.0/25 -o com.docker.network.bridge.name=s2-br $NET >/dev/null
  up_fs vt1; up_fs vt2
  instance s2-nfs-vt1 172.31.0.131 vt1 201 "-V 3 -N 4"
  instance s2-nfs-vt2 172.31.0.132 vt2 202 "-N 3 -N 4.0 -V 4.1"
  docker rm -f s2-vc >/dev/null 2>&1; docker run -d --name s2-vc --network $NET --privileged anf-s2-client:spike sleep infinity >/dev/null
  echo "Q1/Q2 vt1 (v3-only instance):"
  try "v3   .131:/vt1" 172.31.0.131 /vt1 vers=3,nolock
  try "v4.1 .131:/vt1" 172.31.0.131 /vt1 vers=4.1
  echo "Q1/Q2 vt2 (v4.1-only instance):"
  try "v4.1 .132:/vt2" 172.31.0.132 /vt2 vers=4.1
  try "v3   .132:/vt2" 172.31.0.132 /vt2 vers=3,nolock
  try "v4.0 .132:/vt2" 172.31.0.132 /vt2 vers=4.0
  echo "isolation: vt2 not exported by vt1's instance:"
  try "v3   .131:/vt2" 172.31.0.131 /vt2 vers=3,nolock
  echo "Q3: mount on host under ns/vt2 after the instance started:"
  truncate -s 64M "$R/snap.img"; mkfs.ext4 -q -F "$R/snap.img"; mkdir -p "$R/ns/vt2/.snapshot/s1"
  mount -o loop,ro "$R/snap.img" "$R/ns/vt2/.snapshot/s1"
  docker exec s2-vc sh -c "mkdir -p /m && mount -t nfs -o vers=4.1 172.31.0.132:/vt2 /m && ls -la /m/.snapshot/s1 | head -3; umount /m"
  ;;
down)
  docker rm -f s2-vc s2-nfs-vt1 s2-nfs-vt2 >/dev/null 2>&1
  for m in "$R/ns/vt2/.snapshot/s1" "$R/ns/vt1" "$R/ns/vt2" "$R/ns"; do
    for _ in $(seq 60); do mountpoint -q "$m" || break; umount "$m" 2>/dev/null && break; sleep 1; done
    mountpoint -q "$m" && echo "STILL MOUNTED $m"
  done
  losetup -a | grep spike-s2b | cut -d: -f1 | while read -r d; do losetup -d "$d"; done
  mountpoint -q "$R/ns/vt1" || mountpoint -q "$R/ns/vt2" || rm -rf "$R"
  docker network rm $NET >/dev/null 2>&1
  echo "left: $(ls $R 2>&1 | head -1); $(losetup -a | grep -c spike-s2b) loops; $(docker ps -a --filter name=s2- -q | wc -l) containers"
  ;;
esac
