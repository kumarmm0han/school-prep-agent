#!/usr/bin/env bash
# ============================================================================
# convert_batch.sh — run the convert pipeline DETACHED from any coding session.
#
# Why (AGENTS.md "Session & GPU Discipline"): this host is a single-GPU machine.
# The agent's own inference (OLLAMA qwen3.8:27b) and the pipeline's models
# (docling-serve, VLM qwen3-vl:8b) share that GPU. A long conversion started
# inside a session queues behind — or starves — the agent, and a slow agent
# stalls the review work. So conversions run here, detached, one book at a time,
# and the session only ever LAUNCHES, CHECKS, or STOPS the batch.
#
# Usage:
#   scripts/convert_batch.sh [start] [options]     launch detached (default verb)
#   scripts/convert_batch.sh status                is a batch running? tail its log
#   scripts/convert_batch.sh stop                   SIGTERM the batch (then SIGKILL)
#   scripts/convert_batch.sh -h | --help
#
# start options:
#   --all                       convert every book dir under books/ (default)
#   --book-dir DIR              convert only this book dir (repeatable)
#   --chapter N                 convert one chapter per book (pipelined flag)
#   --force                     re-convert even when up to date (pipelined flag)
#   --pipeline standard|vlm     docling pipeline (pipelined flag, default standard)
#   --foreground                run inline in THIS terminal (debug only —
#                               keeps the GPU busy while you're here)
#
# Internals:
#   logs/batch/convert-batch-<UTC stamp>.log   one log per launch
#   logs/batch/.pid                            single-instance lock (process group)
#   logs/batch/current                         log path of the latest launch
# Exit codes: 0 launched/fine · 2 usage · 3 doctor preflight failed · 4 already running
# ============================================================================
set -u

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SELF_DIR/.." && pwd)"
BATCH_DIR="$REPO/logs/batch"
PIDFILE="$BATCH_DIR/.pid"
CURRENT="$BATCH_DIR/current"
PYTHON="${PYTHON:-python3}"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$BATCH_DIR/convert-batch-$STAMP.log"

usage() {
  cat <<'EOF'
convert_batch.sh — run the convert pipeline detached from any coding session.
(See the header of scripts/convert_batch.sh for the why: single-GPU host —
agent inference and pipeline models share the GPU; sessions only
launch/check/stop batches, never run them inline.)

Usage:
  scripts/convert_batch.sh [start] [options]   launch detached (default verb)
  scripts/convert_batch.sh status              is a batch running? tail its log
  scripts/convert_batch.sh stop                SIGTERM the batch (then SIGKILL)
  scripts/convert_batch.sh -h | --help

start options:
  --all                      convert every book dir under books/ (default)
  --book-dir DIR             convert only this book dir (repeatable)
  --chapter N                convert one chapter per book (pipelined flag)
  --force                    re-convert even when up to date (pipelined flag)
  --pipeline standard|vlm    docling pipeline (default: standard)
  --foreground               run inline in THIS terminal (debug only — keeps the
                             GPU busy while you're here)

Files:
  logs/batch/convert-batch-<UTC stamp>.log   one log per launch
  logs/batch/.pid                            single-instance lock (process group)
  logs/batch/current                         log path of the latest launch

Exit codes: 0 launched/fine · 2 usage · 3 doctor preflight failed · 4 already running
EOF
  exit "${1:-0}"
}

die() { # die <exitcode> <message...>
  local code="$1"; shift
  printf 'convert_batch: %s\n' "$*" >&2
  exit "$code"
}

pid_alive() { kill -0 "$1" 2>/dev/null; }

load_dotenv() {
  # DESIGN S2: shell env always wins — fill only UNSET keys from .env.
  local envfile="$REPO/.env" line key val
  [ -f "$envfile" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    case "$line" in ''|\#*) continue ;; esac
    key="${line%%=*}"; val="${line#*=}"
    case "$key" in *[!A-Za-z0-9_]*|'') continue ;; esac
    val="${val%\"}"; val="${val#\"}"
    if [ -z "${!key:-}" ]; then export "$key=$val"; fi
  done < "$envfile"
}

resolve_books() {
  # Books = depth-2 dirs under books/ that contain at least one PDF.
  if [ "${#BOOKS[@]}" -gt 0 ]; then return 0; fi
  local d
  for d in "$REPO"/books/*/*/; do
    [ -d "$d" ] || continue
    [ -n "$(find "$d" -maxdepth 1 -name '*.pdf' -print -quit 2>/dev/null)" ] && BOOKS+=("${d%/}")
  done
}

preflight() {
  # Read-only HTTP checks (docling-serve /health, ollama /api/tags) — no GPU load.
  if ! "$PYTHON" -m pipeline doctor; then
    die 3 "doctor preflight FAILED — start the service(s) first, then re-run (exit 3). No batch was launched."
  fi
}

worker() {
  # Runs detached in its own process group; one book at a time (GPU-bound,
  # per-chapter isolation inside the pipeline per D4). One book failing never
  # aborts the others.
  mkdir -p "$BATCH_DIR"
  trap 'rm -f "$PIDFILE"' EXIT
  local overall=0 rc d args
  echo "=== convert_batch start $STAMP (pid $$) ==="
  echo "repo=$REPO"
  echo "env: DOCLING_URL=${DOCLING_URL:-(unset)} OLLAMA_URL=${OLLAMA_URL:-(unset)} VLM_MODEL=${VLM_MODEL:-(unset)} LLM_MODEL=${LLM_MODEL:-(unset)}"
  args=()
  [ -n "$chapter" ] && args+=(--chapter "$chapter")
  [ "$force" = "1" ] && args+=(--force)
  args+=(--pipeline "$pipeline")
  for d in "${BOOKS[@]}"; do
    echo "----- book: $d -----"
    rc=0
    "$PYTHON" -m pipeline convert --book-dir "$d" "${args[@]}" || rc=$?
    echo "----- book done: $d (exit $rc) -----"
    [ "$rc" -gt "$overall" ] && overall=$rc
  done
  echo "=== convert_batch COMPLETE overall_exit=$overall stamp=$STAMP ==="
  return "$overall"
}

cmd_start() {
  local foreground=0
  BOOKS=()
  while [ $# -gt 0 ]; do
    case "$1" in
      --all) ;;                                        # keep default
      --book-dir) [ $# -ge 2 ] || die 2 "--book-dir needs a value"; BOOKS+=("$2"); shift 2 ;;
      --chapter) chapter="$2"; shift 2 ;;
      --force) force=1; shift ;;
      --pipeline) pipeline="$2"; shift 2 ;;
      --foreground) foreground=1; shift ;;
      -h|--help) usage 0 ;;
      -*) die 2 "unknown option: $1" ;;
      *) die 2 "unexpected argument: $1 (see --help)" ;;
    esac
  done
  chapter="${chapter:-}"
  force="${force:-0}"
  pipeline="${pipeline:-standard}"
  case "$pipeline" in standard|vlm) ;; *) die 2 "--pipeline must be standard or vlm" ;; esac
  [ "${chapter:-}" = "" ] || { [[ "$chapter" =~ ^[1-9][0-9]*$ ]] || die 2 "--chapter must be a positive integer"; }

  load_dotenv
  resolve_books
  [ "${#BOOKS[@]}" -gt 0 ] || die 2 "no book dirs found under books/ (depth 2, containing a *.pdf)"

  preflight

  if [ -f "$PIDFILE" ] && pid_alive "$(cat "$PIDFILE" 2>/dev/null || echo 0)"; then
    die 4 "a batch is already running (pid $(cat "$PIDFILE")) — use 'scripts/convert_batch.sh status' or 'stop'"
  fi
  rm -f "$PIDFILE"

  local short="" d
  for d in "${BOOKS[@]}"; do short+=" ${d#"$REPO"/}"; done
  local fl="-"
  [ "$force" = "1" ] && fl="yes"
  echo "convert_batch: $STAMP books=${#BOOKS[@]}:$short chapter=${chapter:-*} force=$fl pipeline=$pipeline"
  if [ "$foreground" -eq 1 ]; then
    echo "convert_batch: --foreground: running inline (debug only — GPU busy while you're here)"
    echo "$$" > "$PIDFILE"
    worker
    local rc=$?
    rm -f "$PIDFILE"
    return "$rc"
  fi

  mkdir -p "$BATCH_DIR"
  local setsid_arg=()
  command -v setsid >/dev/null && setsid_arg=(setsid)
  nohup "${setsid_arg[@]}" bash "$SELF_PATH" __worker__ \
      --books "${BOOKS[*]}" --chapter "$chapter" --force "$force" --pipeline "$pipeline" \
      < /dev/null > "$LOG" 2>&1 &
  local pid=$!
  echo "$pid" > "$PIDFILE"
  echo "$LOG" > "$CURRENT"
  sleep 0.3
  if ! pid_alive "$pid"; then
    # The batch already finished (e.g. bad args, nothing to convert) and cleaned its own lock.
    local line overall
    if [ -f "$LOG" ] && grep -q "convert_batch COMPLETE overall_exit=" "$LOG"; then
      line="$(grep "convert_batch COMPLETE" "$LOG" | tail -1)"
      overall="${line##*overall_exit=}"; overall="${overall%% *}"
      echo "convert_batch: finished immediately — $line"
      echo "  log:     $LOG"
      echo "  status:  scripts/convert_batch.sh status"
      return "${overall:-1}"
    fi
    die 4 "batch process died before finishing — see log: $LOG"
  fi
  echo "convert_batch: launched (pid $pid) — GPU will be busy until it finishes."
  echo "  log:     $LOG"
  echo "  follow:  tail -f $LOG"
  echo "  status:  scripts/convert_batch.sh status"
  echo "  stop:    scripts/convert_batch.sh stop"
  return 0
}

cmd_worker_internal() {
  # Launched by cmd_start; parses the internal flag list and runs worker().
  local bc="" bp=standard
  while [ $# -gt 0 ]; do
    case "$1" in
      --books) bc="$2"; shift 2 ;;
      --chapter) [ "$2" != "" ] && chapter="$2"; shift 2 ;;
      --force) [ "$2" = "1" ] && force=1; shift 2 ;;
      --pipeline) bp="$2"; shift 2 ;;
      *) shift ;;
    esac
  done
  IFS=' ' read -r -a BOOKS <<< "$bc"
  chapter="${chapter:-}"
  force="${force:-0}"
  pipeline="$bp"
  worker
}

cmd_status() {
  if [ -f "$PIDFILE" ] && pid_alive "$(cat "$PIDFILE" 2>/dev/null || echo 0)"; then
    local pid; pid="$(cat "$PIDFILE")"
    echo "RUNNING (pid $pid)"
    local log; log="$(cat "$CURRENT" 2>/dev/null)"
    [ -n "${log:-}" ] && [ -f "$log" ] || log="$(ls -1t "$BATCH_DIR"/convert-batch-*.log 2>/dev/null | head -1)"
    [ -n "${log:-}" ] && { echo "log: $log"; echo '--- last 20 lines ---'; tail -n 20 "$log"; }
    return 0
  fi
  # Stale state: report the most recent launch.
  local log; log="$(cat "$CURRENT" 2>/dev/null)"
  [ -n "${log:-}" ] && [ -f "$log" ] || log="$(ls -1t "$BATCH_DIR"/convert-batch-*.log 2>/dev/null | head -1)"
  if [ -z "${log:-}" ]; then
    echo "NOT running; no previous batch found in $BATCH_DIR"
    rm -f "$PIDFILE"
    return 0
  fi
  echo "NOT running (last batch exited — stale lock cleaned)."
  echo "last log: $log"
  echo '--- last 20 lines ---'
  tail -n 20 "$log"
  rm -f "$PIDFILE"
  return 0
}

cmd_stop() {
  [ -f "$PIDFILE" ] || { rm -f "$PIDFILE"; echo "no batch running (no pidfile)"; return 0; }
  local pid; pid="$(cat "$PIDFILE" 2>/dev/null || echo 0)"
  if ! pid_alive "$pid"; then echo "not running (dead pid $pid in pidfile)"; rm -f "$PIDFILE"; return 0; fi
  echo "stopping pid $pid (SIGTERM to process group)…"
  kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null
  local i
  for i in 1 2 3 4 5; do
    sleep 1
    pid_alive "$pid" || { echo "stopped."; rm -f "$PIDFILE"; return 0; }
  done
  echo "still alive — SIGKILL."
  kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null
  rm -f "$PIDFILE"
  echo "killed (pid $pid)."
}

SELF_PATH="$REPO/scripts/convert_batch.sh"
[ $# -eq 0 ] && set -- start
case "$1" in
  __worker__) shift; cmd_worker_internal "$@" ;;
  start)  shift; cmd_start "$@" ;;
  status) cmd_status ;;
  stop)   cmd_stop ;;
  -h|--help|help) usage 0 ;;
  *) usage 2 ;;
esac
