#!/bin/bash
# T3 mechanism check: the I/O path a per-volume userspace NFS server (Ganesha) would have,
# i.e. a process in its own cgroup with io.max on the volume's block device.
# fio stands in for the server process; Ganesha itself is not run here.
set -uo pipefail
DEV=/dev/anfs2/a
VOL=/var/lib/anf-clone/spike-s2/mnt/a
LIM=10mb   # docker: 10 MiB/s
run() {  # label, fio args...
  local label=$1; shift
  docker run --rm --device-read-bps "$DEV:$LIM" --device-write-bps "$DEV:$LIM" -v "$VOL:/data" \
    anf-s2-client:spike fio --bs=1M --ioengine=libaio --iodepth=16 --clocksource=clock_gettime \
    --output-format=terse --terse-version=3 "$@" |
  awk -F';' -v l="$label" '{r+=$7/1024; w+=$48/1024} END {printf "%-34s read %7.1f  write %7.1f  sum %7.1f MiB/s\n", l, r, w, r+w}'
}
drop() { sync; echo 3 > /proc/sys/vm/drop_caches; }

echo "io.max inside the container cgroup:"
docker run --rm --device-read-bps "$DEV:$LIM" --device-write-bps "$DEV:$LIM" anf-s2-client:spike cat /sys/fs/cgroup/io.max
for i in 1; do
  run "direct write" --name=w --filename=/data/t3w.dat --rw=write --direct=1 --size=100M
  run "buffered write + fsync" --name=w --filename=/data/t3w.dat --rw=write --direct=0 --end_fsync=1 --size=100M
  drop; run "direct read (cold)" --name=r --filename=/data/r.dat --rw=read --direct=1 --size=100M
  drop; cat $VOL/r.dat > /dev/null
  run "buffered read (warm page cache)" --name=r --filename=/data/r.dat --rw=read --direct=0 --size=1000M
  drop; run "direct read+write together" --name=r --filename=/data/r.dat --rw=read --direct=1 --size=100M \
                                         --name=w --filename=/data/t3w.dat --rw=write --direct=1 --size=100M
done
rm -f $VOL/t3w.dat
