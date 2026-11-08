#!/bin/bash
# T1: shape per-volume mount IP on s2-br. Both directions go through one IFB
# device so one HTB class per volume bounds read+write together.
#   t1.sh on   <MiB/s for .11> <MiB/s for .12>   (0 = unlimited)
#   t1.sh off
#   t1.sh show
set -euo pipefail
BR=s2-br IFB=ifb-s2
bits() { echo $(( $1 * 1048576 * 8 )); }

off() {
  tc qdisc del dev $BR clsact 2>/dev/null || true
  ip link del $IFB 2>/dev/null || true
}

case "$1" in
  off) off ;;
  show)
    tc -s class show dev $IFB 2>/dev/null | grep -E "class|Sent" || echo "T1 off" ;;
  on)
    off
    modprobe ifb numifbs=0
    modprobe sch_htb; modprobe cls_flower; modprobe act_mirred
    ip link add $IFB type ifb
    ip link set $IFB txqueuelen 1000 up
    tc qdisc add dev $BR clsact
    tc qdisc add dev $IFB root handle 1: htb default 99
    tc class add dev $IFB parent 1: classid 1:99 htb rate 10gbit
    tc qdisc add dev $IFB parent 1:99 handle 99: fq_codel
    for pair in "11 $2" "12 $3"; do
      set -- $pair; id=$1 mib=$2 ip=172.31.0.$1
      # client -> volume IP (writes) and volume IP -> client (reads)
      tc filter add dev $BR ingress protocol ip flower dst_ip $ip action mirred egress redirect dev $IFB
      tc filter add dev $BR egress  protocol ip flower src_ip $ip action mirred egress redirect dev $IFB
      [ "$mib" = 0 ] && continue
      tc class add dev $IFB parent 1: classid 1:$id htb rate $(bits $mib)bit ceil $(bits $mib)bit
      tc qdisc add dev $IFB parent 1:$id handle $id: fq_codel
      tc filter add dev $IFB parent 1: protocol ip prio 1 flower dst_ip $ip classid 1:$id
      tc filter add dev $IFB parent 1: protocol ip prio 1 flower src_ip $ip classid 1:$id
    done
    tc class show dev $IFB ;;
  change)
    # live change of one class: t1.sh change 11 <MiB/s>
    tc class change dev $IFB parent 1: classid 1:$2 htb rate $(bits $3)bit ceil $(bits $3)bit
    tc class show dev $IFB classid 1:$2 ;;
esac
