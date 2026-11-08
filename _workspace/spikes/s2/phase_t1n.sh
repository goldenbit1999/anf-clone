#!/bin/bash
# T1n measurement phase: per-volume knfsd in its own netns, tc on its veth.
# Client s2-c3 mounts a (.21) and b (.22) over v4.1 and a over v3 (/mnt/a3).
set -euo pipefail
cd "$(dirname "$0")"
WDIR=$(wsl -d Ubuntu -e wslpath -a "$(pwd -W)")
export MSYS_NO_PATHCONV=1
P=/c/Users/mkimh/Projects/ANF-clone/.venv-win/Scripts/python.exe
W="wsl -d Ubuntu -u root -e bash $WDIR"

$W/t1n.sh change a 10
$P s2run.py measure T1n-10-v41-write s2-c3 /mnt/a/w.dat write 150 5
$P s2run.py measure T1n-10-v41-read  s2-c3 /mnt/a/r.dat read  150 5 --drop
$P s2run.py measure T1n-10-v3-write  s2-c3 /mnt/a3/w.dat write 150 3
# same client, two volumes: a saturated at its limit, b (no limit) measured
$P s2run.py noisy   T1n-10-v41-b-while-a-write "s2-c3:/mnt/a/n.dat:write:30:16" s2-c3 /mnt/b/w.dat write 1024 3
$P s2run.py mixed   T1n-10-v41-mixed s2-c3 /mnt/a/r.dat /mnt/a/w.dat 15 3 --drop
$W/t1n.sh change a 30
$P s2run.py measure T1n-30-v41-write s2-c3 /mnt/a/w.dat write 450 5
$P s2run.py measure T1n-30-v41-read  s2-c3 /mnt/a/r.dat read  450 5 --drop
$W/t1n.sh show
wsl -d Ubuntu -u root -e tc -s qdisc show dev ifb-s2a
echo T1n done
