#!/bin/bash
# S2 setup. Touches only s2-* resources.
#   a, b: thin LVs in VG anfs2 (one thin pool on a loop file) + ext4  -> D-11 candidate C
#   c:    btrfs on its own sparse loop file                           -> D-11 candidate B
# Exported via host knfsd to 172.31.0.0/24 only (exportfs -o, never -ra).
set -euo pipefail
export LVM_SUPPRESS_FD_WARNINGS=1
ROOT=/var/lib/anf-clone/spike-s2
HERE=$(cd "$(dirname "$0")" && pwd)

docker build -q -t anf-s2-client:spike "$HERE/client"

docker network inspect s2-net >/dev/null 2>&1 || \
  docker network create --driver bridge --subnet 172.31.0.0/24 --gateway 172.31.0.1 \
    -o com.docker.network.bridge.name=s2-br s2-net

mkdir -p "$ROOT/mnt/a" "$ROOT/mnt/b" "$ROOT/mnt/c"

if ! vgs anfs2 >/dev/null 2>&1; then
  truncate -s 10G "$ROOT/pool.img"
  dev=$(losetup --find --show "$ROOT/pool.img")
  echo "$dev" > "$ROOT/pool.loopdev"
  pvcreate -q "$dev"
  vgcreate -q anfs2 "$dev"
  lvcreate -q --type thin-pool -L 9G -n pool anfs2
  for v in a b; do
    lvcreate -q -V 4G -T anfs2/pool -n "$v"
    mkfs.ext4 -q "/dev/anfs2/$v"
  done
fi
for v in a b; do
  mountpoint -q "$ROOT/mnt/$v" || mount "/dev/anfs2/$v" "$ROOT/mnt/$v"
done

if ! mountpoint -q "$ROOT/mnt/c"; then
  truncate -s 4G "$ROOT/c.img"
  dev=$(losetup --find --show "$ROOT/c.img")
  echo "$dev" > "$ROOT/c.loopdev"
  mkfs.btrfs -q -f "$dev"
  mount "$dev" "$ROOT/mnt/c"
fi

for v in a b c; do
  exportfs -o rw,sync,no_subtree_check,no_root_squash "172.31.0.0/24:$ROOT/mnt/$v"
done

for c in s2-c1 s2-c2; do
  docker inspect "$c" >/dev/null 2>&1 || \
    docker run -d --name "$c" --network s2-net --privileged anf-s2-client:spike sleep infinity >/dev/null
done

# Per-volume mount IPs (T1 shapes by IP). The bridge is UP once a container joins.
ip addr replace 172.31.0.11/24 dev s2-br
ip addr replace 172.31.0.12/24 dev s2-br
ip addr replace 172.31.0.13/24 dev s2-br

for v in a b c; do
  echo "$v: $(findmnt -no SOURCE,FSTYPE "$ROOT/mnt/$v") dev=$(lsblk -no MAJ:MIN "$(findmnt -no SOURCE "$ROOT/mnt/$v")" | tr -d ' ')"
done
exportfs -v | grep -A1 spike-s2
ip -br addr show s2-br
docker ps --filter name=s2- --format '{{.Names}} {{.Status}}'
