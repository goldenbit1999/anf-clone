#!/bin/bash
# T2 measurement phase (Git Bash on Windows).
#   a = 254:4 (dm-thin LV + ext4, candidate C), b = 254:5, c = 7:3 (loop + btrfs, candidate B)
set -euo pipefail
cd "$(dirname "$0")"
WDIR=$(wsl -d Ubuntu -e wslpath -a "$(pwd -W)")
export MSYS_NO_PATHCONV=1
P=/c/Users/mkimh/Projects/ANF-clone/.venv-win/Scripts/python.exe
T2="wsl -d Ubuntu -u root -e bash $WDIR/t2.sh"
A=$1 C=$2

trap '$T2 off' EXIT
$T2 on
$T2 limit $A 10
$P s2run.py measure T2-10-v41-write s2-c1 /mnt/a/w.dat write 150 5
$P s2run.py measure T2-10-v41-read  s2-c1 /mnt/a/r.dat read  150 5 --drop
# warm read: file already in the server page cache, no block I/O
$P s2run.py measure T2-10-v41-read-warm s2-c1 /mnt/a/r.dat read 150 3
# isolation: another client saturates a; b has no limit
$P s2run.py noisy   T2-10-b-while-a-write "s2-c1:/mnt/a/n.dat:write:30:16" s2-c2 /mnt/b/w.dat write 1024 3
$P s2run.py mixed   T2-10-v41-mixed s2-c1 /mnt/a/r.dat /mnt/a/w.dat 15 3 --drop
# live change 10 -> 30 MiB/s
$T2 limit $A 30
$P s2run.py measure T2-30-v41-write s2-c1 /mnt/a/w.dat write 450 5
$P s2run.py measure T2-30-v41-read  s2-c1 /mnt/a/r.dat read  450 5 --drop
$T2 limit $A 0
# candidate B: btrfs on a loop device
$T2 limit $C 10
$P s2run.py measure T2-10-btrfs-write s2-c1 /mnt/c/w.dat write 150 3
$P s2run.py measure T2-10-btrfs-read  s2-c1 /mnt/c/r.dat read  150 3 --drop
$T2 show
echo T2 done
