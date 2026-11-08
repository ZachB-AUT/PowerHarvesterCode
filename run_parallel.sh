#!/usr/bin/env bash
# Run a whole parameter sweep in parallel.
#
#   ./run_parallel.sh coarse|fine|light [jobs]
#
# A slice is one (inner radius, core thickness) of the sweep; sweep_worker.py
# runs each on a private copy of FEMM, JOBS at a time (default 8). The slices'
# results are then merged into femm_work/parameter_sweep_progress.csv, and the
# phase's normal script runs once more: it finds every design already done
# (and simulates any a failed slice missed) and writes the usual results file.
#
# A watchdog restarts a slice whose FEMM has hung (no solver running and no
# result saved for IDLE_MIN minutes). Logs: femm_work/workers/<slice>.log.
# Safe to stop and rerun: finished designs are never simulated twice.
set -u
cd "$(dirname "$0")" || exit 1

PHASE=${1:?usage: ./run_parallel.sh coarse|fine|light [jobs]}
JOBS=${2:-8}
IDLE_MIN=${IDLE_MIN:-10}
SLICE_TIMEOUT=${SLICE_TIMEOUT:-6h}
case $PHASE in
  coarse) SCRIPT=harvester-reimplementation.py ;;
  fine) SCRIPT=fine_sweep.py ;;
  light) SCRIPT=light_sweep.py ;;
  *) echo "unknown phase '$PHASE' (coarse, fine or light)"; exit 1 ;;
esac

export WINEDEBUG=-all MPLBACKEND=Agg
export DISPLAY=${DISPLAY:-:0}  # FEMM needs an X display even when minimised
PY="uv run python"
WORKERS=femm_work/workers
mkdir -p "$WORKERS"
log() { echo "$(date '+%F %T') $*"; }

watchdog() {
  declare -A idle
  while true; do
    while read -r pid r t; do
      name="${PHASE}_r${r}_t${t}"
      progress=$WORKERS/$name/parameter_sweep_progress.csv
      saved_ago=$(( ($(date +%s) - $(stat -c %Y "$progress" 2>/dev/null || date +%s)) / 60 ))
      if pgrep -f "femm42_${name}[\\\\/]bin[\\\\/]fkn" >/dev/null || [ "$saved_ago" -lt 2 ]; then
        idle[$name]=0
      else
        idle[$name]=$(( ${idle[$name]:-0} + 1 ))
      fi
      if [ "${idle[$name]}" -ge "$IDLE_MIN" ]; then
        log "watchdog: $name looks hung, restarting it" | tee -a "$WORKERS/$name.log"
        kill "$pid"
        pkill -f "femm42_${name}/bin/femm\\.exe"
        idle[$name]=0
      fi
    done < <(pgrep -af "^[^ ]*python[0-9.]* sweep_worker.py $PHASE " | awk '{print $1, $(NF-1), $NF}')
    sleep 60
  done
}

log "$PHASE sweep: $($PY sweep_worker.py slices "$PHASE" | wc -l) slices, $JOBS at a time"
watchdog &
WATCHDOG=$!
trap 'kill $WATCHDOG 2>/dev/null' EXIT

$PY sweep_worker.py slices "$PHASE" | xargs -P "$JOBS" -L 1 bash -c '
  log='"$WORKERS/$PHASE"'_r$0_t$1.log
  for attempt in 1 2 3; do
    timeout '"$SLICE_TIMEOUT"' '"$PY"' sweep_worker.py '"$PHASE"' "$0" "$1" >> "$log" 2>&1 && exit 0
    echo "attempt $attempt failed" >> "$log"
  done
  echo "slice r$0 t$1 failed 3 times, see $log" >&2
  exit 1'
log "slices finished (status $?)"

$PY sweep_worker.py merge
log "collating with $SCRIPT"
$PY "$SCRIPT"
