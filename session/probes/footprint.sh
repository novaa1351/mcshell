#!/bin/sh
# How much memory the shell itself is using, per part. The instrument for
# changing the footprint: run it before, change one thing, run it after.
#
#   footprint.sh              one table, now
#   footprint.sh --line       the same, as one line, for logging over time
#   footprint.sh --watch 60   a line every 60s until interrupted
#
# Memory is PSS (shared pages split between the processes sharing them), so
# the column adds up to something real. But a library's share moves with
# whoever *else* has it open, so a total can rise because a browser closed.
# `own` leaves file-backed pages out — anonymous and shared memory plus GPU,
# which is what the shell itself caused — and is the number to compare. GPU is what the process holds in
# graphics buffers, read from DRM fdinfo: on an integrated GPU that is system
# RAM too, and PSS does not see it. Units are grouped by cgroup rather than
# matched by name, so the game is whatever Java mcshell-client started, and
# the overlay counts under the daemon that spawned it.
#
# The game's heap needs the JDK's jcmd and jstat. Without them those columns
# are blank and everything else still prints.
#
#   heap      committed: what the JVM has taken from the OS for the heap
#   used      live objects plus garbage not yet collected
#   gc        collections since the game started, and the seconds spent
#
# Asks nothing of the game that changes it: no forced collection, no flags.
set -u
mode=${1:-}
every=${2:-60}

pss() {   # KB of PSS over a list of PIDs
	t=0
	for p in "$@"; do
		v=$(awk '/^Pss:/{print $2}' "/proc/$p/smaps_rollup" 2>/dev/null)
		t=$((t + ${v:-0}))
	done
	echo "$t"
}

own() {   # KB of PSS that is not a mapped file, over a list of PIDs
	t=0
	for p in "$@"; do
		v=$(awk '/^Pss_(Anon|Shmem):/{s+=$2} END{print s+0}' "/proc/$p/smaps_rollup" 2>/dev/null)
		t=$((t + ${v:-0}))
	done
	echo "$t"
}

gpu() {   # KB of DRM buffers over a list of PIDs, each client counted once
	for p in "$@"; do
		for f in /proc/"$p"/fdinfo/*; do
			awk '/^drm-client-id:/{id=$2} /^drm-total-(system0|gtt|vram):/{kb=$2} END{if(id!="")print id, kb+0}' "$f" 2>/dev/null
		done
	done | sort -u | awk '{t+=$2} END{print t+0}'
}

unit_pids() {
	cg=$(systemctl --user show -p ControlGroup --value "$1" 2>/dev/null)
	[ -n "$cg" ] && cat "/sys/fs/cgroup$cg/cgroup.procs" 2>/dev/null
}

me=$(id -u)
client=$(unit_pids mcshell-client.service)
daemon=$(unit_pids mcshelld.service)
java=""; prism=""; other=""
for p in $client; do
	case $(cat "/proc/$p/comm" 2>/dev/null) in
	java) java=$p ;;
	prismlauncher) prism="$prism $p" ;;
	*) other="$other $p" ;;
	esac
done
overlay=""; mcshelld=""
for p in $daemon; do
	if tr '\0' ' ' <"/proc/$p/cmdline" 2>/dev/null | grep -q 'overlay\.py'; then
		overlay="$overlay $p"
	else
		mcshelld="$mcshelld $p"
	fi
done
sway=$(pgrep -u "$me" -x sway)
xwayland=$(pgrep -u "$me" -x Xwayland)
swaybg=$(pgrep -u "$me" -x swaybg)

# The game's JVM, from the JDK the instance runs on rather than from PATH,
# which on this machine is a different Java.
heap=""; used=""; meta=""; gcs=""; gct=""; up=""
if [ -n "$java" ]; then
	bin=$(dirname "$(readlink -f "/proc/$java/exe")")
	up=$(ps -o etimes= -p "$java" | tr -d ' ')
	if [ -x "$bin/jcmd" ] && info=$("$bin/jcmd" "$java" GC.heap_info 2>/dev/null); then
		heap=$(echo "$info" | sed -n 's/.*heap *total \([0-9]*\)K, used \([0-9]*\)K.*/\1/p')
		used=$(echo "$info" | sed -n 's/.*heap *total \([0-9]*\)K, used \([0-9]*\)K.*/\2/p')
		meta=$(echo "$info" | sed -n 's/^ *Metaspace *used [0-9]*K, committed \([0-9]*\)K.*/\1/p')
	fi
	if [ -x "$bin/jstat" ] && gc=$("$bin/jstat" -gc "$java" 2>/dev/null); then
		# Columns by name, because they differ between collectors.
		# shellcheck disable=SC2046  # split on purpose: two numbers, into $1 and $2
		set -- $(echo "$gc" | awk 'NR==1{for(i=1;i<=NF;i++)h[$i]=i} NR==2{print $h["YGC"]+$h["FGC"]+$h["CGC"], $h["GCT"]}')
		gcs=${1:-}; gct=${2:-}
	fi
fi

mb() { [ -n "$1" ] && echo $(( ($1 + 512) / 1024 )) || echo "-"; }

j_pss=$(pss $java); j_gpu=$(gpu $java)
x_pss=$(pss $xwayland); x_gpu=$(gpu $xwayland)
o_pss=$(pss $overlay); d_pss=$(pss $mcshelld); p_pss=$(pss $prism $other)
s_pss=$(pss $sway $swaybg); s_gpu=$(gpu $sway)
total=$((j_pss + j_gpu + x_pss + x_gpu + o_pss + d_pss + p_pss + s_pss + s_gpu))
mine=$(( $(own $java $xwayland $overlay $mcshelld $prism $other $sway $swaybg) + j_gpu + x_gpu + s_gpu ))

if [ "$mode" = --line ] || [ "$mode" = --watch ]; then
	line() {
		printf '%s up=%ss own=%s total=%s java=%s gpu=%s heap=%s used=%s meta=%s gc=%s/%ss overlay=%s daemon=%s prism=%s xwayland=%s sway=%s\n' \
			"$(date +%H:%M:%S)" "${up:--}" "$(mb $mine)" "$(mb $total)" "$(mb $j_pss)" "$(mb $j_gpu)" \
			"$(mb "$heap")" "$(mb "$used")" "$(mb "$meta")" "${gcs:--}" "${gct:--}" \
			"$(mb $o_pss)" "$(mb $d_pss)" "$(mb $p_pss)" "$(mb $((x_pss + x_gpu)))" "$(mb $((s_pss + s_gpu)))"
	}
	line
	if [ "$mode" = --watch ]; then
		sleep "$every"
		exec "$0" --watch "$every"
	fi
	exit 0
fi

printf '%-22s %8s %8s\n' "" "PSS MB" "GPU MB"
printf '%-22s %8s %8s\n' "game (java)" "$(mb $j_pss)" "$(mb $j_gpu)"
printf '%-22s %8s\n' "  heap committed" "$(mb "$heap")"
printf '%-22s %8s\n' "  heap used" "$(mb "$used")"
printf '%-22s %8s\n' "  metaspace" "$(mb "$meta")"
printf '%-22s %8s\n' "launcher (prism)" "$(mb $p_pss)"
printf '%-22s %8s\n' "overlay" "$(mb $o_pss)"
printf '%-22s %8s\n' "daemon" "$(mb $d_pss)"
printf '%-22s %8s %8s\n' "Xwayland" "$(mb $x_pss)" "$(mb $x_gpu)"
printf '%-22s %8s %8s\n' "sway, swaybg" "$(mb $s_pss)" "$(mb $s_gpu)"
printf '%-22s %8s\n' "total" "$(mb $total)"
printf '%-22s %8s\n' "own (no libraries)" "$(mb $mine)"
echo
echo "game up ${up:--}s; ${gcs:--} collections, ${gct:--}s in GC"
