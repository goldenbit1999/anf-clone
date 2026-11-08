#!/bin/bash
# Remove everything S2 created. Touches only s2-* resources and VG anfs2.
# The per-netns knfsd keeps the volume filesystem busy for a while after its
# container is removed, so wait for the LVs to close before removing the VG,
# and stop (without deleting files) if they never close.
set -uo pipefail
export LVM_SUPPRESS_FD_WARNINGS=1
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=/var/lib/anf-clone/spike-s2

docker rm -f s2-c1 s2-c2 s2-c3 >/dev/null 2>&1          # clients first, while servers still answer
bash "$HERE/t1n.sh" down
bash "$HERE/t1.sh" off
bash "$HERE/t2.sh" off 2>/dev/null
for v in a b c; do exportfs -u "172.31.0.0/24:$ROOT/mnt/$v" 2>/dev/null; done
for v in a b c; do mountpoint -q "$ROOT/mnt/$v" && umount "$ROOT/mnt/$v"; done

if vgs anfs2 >/dev/null 2>&1; then
  for _ in $(seq 120); do vgchange -q -an anfs2 2>/dev/null && break; sleep 1; done
  vgs --noheadings -o lv_active anfs2 2>/dev/null | grep -q active && { echo "anfs2 still busy; nothing deleted"; exit 1; }
  vgremove -q -f anfs2 && pvremove -q "$(cat $ROOT/pool.loopdev)"
fi
losetup -a | grep "$ROOT" | cut -d: -f1 | while read -r d; do losetup -d "$d"; done
docker network rm s2-net >/dev/null 2>&1
rm -rf "$ROOT"

echo "== left behind (expect none):"
docker ps -a --filter name=s2- --format '{{.Names}}'; docker network ls --filter name=s2- --format '{{.Name}}'
dmsetup ls | grep anfs2; losetup -a | grep spike-s2; ip link | grep -E "ifb-s2|s2-br"; ls /sys/fs/cgroup | grep s2-
