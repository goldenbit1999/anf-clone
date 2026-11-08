#!/bin/bash
# T2: put the knfsd kernel threads into one cgroup and set io.max per volume
# block device (io.max is keyed by device, so one cgroup gives per-volume limits).
#   t2.sh on                 move nfsd threads into /sys/fs/cgroup/s2-nfsd
#   t2.sh limit MAJ:MIN MIB  set rbps=wbps=MIB MiB/s for that device (0 = max)
#   t2.sh show
#   t2.sh off                clear limits, move threads back to the root cgroup
set -uo pipefail
CG=/sys/fs/cgroup/s2-nfsd

case "$1" in
  on)
    mkdir -p $CG
    for p in $(pgrep -x nfsd); do
      if echo "$p" > $CG/cgroup.procs 2>/tmp/s2-cg.err; then echo "moved $p"; else echo "FAILED $p: $(cat /tmp/s2-cg.err)"; fi
    done
    echo "cgroup.procs: $(tr '\n' ' ' < $CG/cgroup.procs)"
    echo "controllers: $(cat $CG/cgroup.controllers)" ;;
  limit)
    if [ "$3" = 0 ]; then v="rbps=max wbps=max"; else b=$(( $3 * 1048576 )); v="rbps=$b wbps=$b"; fi
    echo "$2 $v" > $CG/io.max
    cat $CG/io.max ;;
  show)
    echo "procs: $(tr '\n' ' ' < $CG/cgroup.procs 2>/dev/null)"
    echo "io.max:"; cat $CG/io.max 2>/dev/null
    echo "io.stat:"; cat $CG/io.stat 2>/dev/null ;;
  off)
    if [ -d $CG ]; then
      while read -r dev _; do [ -n "$dev" ] && echo "$dev rbps=max wbps=max" > $CG/io.max; done < $CG/io.max
      for p in $(cat $CG/cgroup.procs); do echo "$p" > /sys/fs/cgroup/cgroup.procs; done
      rmdir $CG && echo "T2 off"
    fi ;;
esac
