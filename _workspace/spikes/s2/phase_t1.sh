#!/bin/bash
# T1 measurement phase (Git Bash on Windows).
set -euo pipefail
cd "$(dirname "$0")"
WDIR=$(wsl -d Ubuntu -e wslpath -a "$(pwd -W)")
export MSYS_NO_PATHCONV=1
P=/c/Users/mkimh/Projects/ANF-clone/.venv-win/Scripts/python.exe
T1="wsl -d Ubuntu -u root -e bash $WDIR/t1.sh"

$T1 on 10 0 >/dev/null 2>&1
# v3 client (separate TCP connection per volume IP)
$P s2run.py measure T1-10-v3-write s2-c2 /mnt/a/w.dat write 150 5
$P s2run.py measure T1-10-v3-read  s2-c2 /mnt/a/r.dat read  150 5 --drop
# isolation: a saturated at its limit, b (no limit) measured at the same time
$P s2run.py noisy   T1-10-v3-b-while-a-write "s2-c2:/mnt/a/n.dat:write:30:16" s2-c2 /mnt/b/w.dat write 1024 3
# read+write together on the limited volume (one bucket for both directions)
$P s2run.py mixed   T1-10-v3-mixed s2-c2 /mnt/a/r.dat /mnt/a/w.dat 15 3 --drop
# live change 10 -> 30 MiB/s
$T1 change 11 30 >/dev/null
$P s2run.py measure T1-30-v3-write s2-c2 /mnt/a/w.dat write 450 5
$P s2run.py measure T1-30-v3-read  s2-c2 /mnt/a/r.dat read  450 5 --drop
# v4.1 client: b is mounted through .12 but trunked onto the .11 connection
$T1 change 11 10 >/dev/null
$P s2run.py measure T1-10-v41-a-write s2-c1 /mnt/a/w.dat write 150 3
$P s2run.py measure T1-10-v41-b-write s2-c1 /mnt/b/w.dat write 150 3
$T1 show
$T1 off
echo T1 done
