#!/bin/bash
# T1n: one knfsd instance per volume, each in its own network namespace (a privileged
# container), shaped on that container's host-side veth (both directions -> one IFB).
#   t1n.sh up                      start s2-srv-a (.21, exports mnt/a) and s2-srv-b (.22, mnt/b)
#   t1n.sh limit <a|b> <MiB/s>     (0 = remove)
#   t1n.sh show | down
set -uo pipefail
ROOT=/var/lib/anf-clone/spike-s2/mnt
bits() { echo $(( $1 * 1048576 * 8 )); }
veth_of() { local idx; idx=$(docker exec "s2-srv-$1" cat /sys/class/net/eth0/iflink); ip -o link | awk -F': ' -v i="$idx" '$1==i {sub(/@.*/,"",$2); print $2}'; }

start_srv() {
  local v=$1 ip=$2
  docker rm -f "s2-srv-$v" >/dev/null 2>&1
  docker run -d --name "s2-srv-$v" --hostname "s2-srv-$v" --network s2-net --ip "$ip" --privileged \
    -v "$ROOT/$v:/vol/$v" anf-s2-client:spike sleep infinity >/dev/null
  # The container root is overlayfs, which mountd cannot use as the NFSv4 pseudo-root,
  # so a tmpfs /export is the fsid=0 root: v4 path ip:/$v, v3 path ip:/export/$v.
  docker exec "s2-srv-$v" sh -c "
    set -e
    mount -t nfsd nfsd /proc/fs/nfsd
    mkdir -p /var/lib/nfs/rpc_pipefs /var/lib/nfs/v4recovery /export
    mount -t tmpfs -o size=1m tmpfs /export && mkdir /export/$v && mount --bind /vol/$v /export/$v
    rpcbind -w
    exportfs -o ro,fsid=0,crossmnt,no_subtree_check 172.31.0.0/24:/export
    exportfs -o rw,sync,no_subtree_check,no_root_squash,fsid=$3 172.31.0.0/24:/export/$v
    rpc.mountd
    rpc.nfsd -V 3 -V 4.1 4
    echo Y > /proc/fs/nfsd/v4_end_grace 2>/dev/null || true
    echo \"$v: threads=\$(cat /proc/fs/nfsd/threads) versions=\$(cat /proc/fs/nfsd/versions)\"
    exportfs -v | tr -s '\t\n' ' '; echo"
}

case "$1" in
  up)
    start_srv a 172.31.0.21 101
    start_srv b 172.31.0.22 102 ;;
  limit)
    v=$2 veth=$(veth_of "$2") ifb="ifb-s2$2"
    tc qdisc del dev "$veth" clsact 2>/dev/null; ip link del "$ifb" 2>/dev/null
    [ "$3" = 0 ] && { echo "$v: unlimited"; exit 0; }
    modprobe ifb numifbs=0; modprobe sch_htb; modprobe cls_matchall; modprobe act_mirred
    ip link add "$ifb" type ifb && ip link set "$ifb" txqueuelen 1000 up
    tc qdisc add dev "$veth" clsact
    tc filter add dev "$veth" ingress matchall action mirred egress redirect dev "$ifb"
    tc filter add dev "$veth" egress  matchall action mirred egress redirect dev "$ifb"
    tc qdisc add dev "$ifb" root handle 1: htb default 1 2>/dev/null
    tc class add dev "$ifb" parent 1: classid 1:1 htb rate "$(bits $3)bit" ceil "$(bits $3)bit" 2>/dev/null
    tc qdisc add dev "$ifb" parent 1:1 handle 10: fq_codel
    echo "$v: $veth -> $ifb $3 MiB/s" ;;
  change)
    tc class change dev "ifb-s2$2" parent 1: classid 1:1 htb rate "$(bits $3)bit" ceil "$(bits $3)bit" 2>/dev/null
    echo "$2: changed to $3 MiB/s" ;;
  show)
    for v in a b; do echo "== $v veth=$(veth_of $v)"; tc -s class show dev "ifb-s2$v" 2>/dev/null | grep -E "class|Sent"; done ;;
  down)
    for v in a b; do
      veth=$(veth_of $v 2>/dev/null); [ -n "$veth" ] && tc qdisc del dev "$veth" clsact 2>/dev/null
      ip link del "ifb-s2$v" 2>/dev/null
      docker exec "s2-srv-$v" sh -c "rpc.nfsd 0; exportfs -ua" >/dev/null 2>&1
      docker rm -f "s2-srv-$v" >/dev/null 2>&1
    done
    echo "T1n down" ;;
esac
