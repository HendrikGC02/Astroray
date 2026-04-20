#!/usr/bin/env bash
# Ralph loop (Track D). Reads scripts/ralph_queue.txt, attempts one
# task per iteration using a local Ollama model, commits on success,
# logs everything to logs/ralph-YYYYMMDD-HHMMSS.md.
#
# Usage: bash .astroray_plan/scripts/ralph_loop.sh [--model MODEL]
#
# Requires: aider, git, cmake, pytest all on PATH.
# Ollama must be running (Windows host or localhost) at OLLAMA_HOST.
# Run from the repo root.

set -euo pipefail

# ── Config ──────────────────────────────────────────────────────────────────
QUEUE=".astroray_plan/scripts/ralph_queue.txt"
GRADUATED=".astroray_plan/scripts/ralph_graduated.txt"
LOGS_DIR="logs"
MODEL="${RALPH_MODEL:-qwen2.5-coder:7b}"
OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"
MAX_FAIL=3

while [[ $# -gt 0 ]]; do
  case "$1" in
    --model) MODEL="$2"; shift 2 ;;
    --ollama-host) OLLAMA_HOST="$2"; shift 2 ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

mkdir -p "$LOGS_DIR"

# ── Helpers ──────────────────────────────────────────────────────────────────
die() { echo "ERROR: $*" >&2; exit 1; }

# Return the first non-blank, non-comment line from the queue, or empty.
pick_task() {
  grep -m1 -E '^[^#[:space:]]' "$QUEUE" 2>/dev/null || true
}

# Count how many times a task has failed (stored as a comment above it).
# Format: "# FAIL <n> | <task line>"
fail_count_for() {
  local task="$1"
  grep -c "^# FAIL [0-9]* | $(echo "$task" | sed 's/[.[\*^$]/\\&/g')" "$QUEUE" 2>/dev/null || echo 0
}

# Remove the first occurrence of a line from the queue.
remove_task() {
  local task="$1"
  # Use temp file to avoid in-place issues on Windows paths
  local tmp; tmp=$(mktemp)
  grep -v -F "$task" "$QUEUE" > "$tmp" || true
  mv "$tmp" "$QUEUE"
}

# Increment the fail counter for a task: replace the raw line with a
# "# FAIL n | <task>" comment line above a copy of the raw line.
increment_fail() {
  local task="$1"
  local n="$2"
  local tmp; tmp=$(mktemp)
  # Replace the first matching raw line with the annotated version
  awk -v task="$task" -v n="$n" '
    !done && $0 == task {
      print "# FAIL " n " | " task
      done=1
      next
    }
    { print }
  ' "$QUEUE" > "$tmp"
  mv "$tmp" "$QUEUE"
}

# Build the prompt for Ollama.
make_prompt() {
  local category="$1"
  local description="$2"
  cat <<PROMPT
You are working on Astroray, a C++/CUDA path tracer.

Your task category is: ${category}
Your task is: ${description}

Rules:
1. Do only what the task says. Nothing else.
2. Run \`cmake --build build -j && pytest tests/ -v\` after your change.
   If either fails, revert all changes and stop.
3. Do not modify files outside the scope of the task.
4. Do not add abstractions or refactor adjacent code.
5. Commit your changes with message: "ralph: ${description}"
6. If you are not confident the change is correct, stop without
   committing and output: "RALPH_FAIL: <reason>"

Physics invariants (never alter):
- GR capture threshold: r < 2.5M
- Dormand-Prince coefficients match Python reference exactly
- Double precision in GR integrator, float elsewhere
PROMPT
}

# ── Trap for clean Ctrl-C ────────────────────────────────────────────────────
trap 'echo; echo "Ralph loop interrupted. Queue is intact."; exit 0' INT

# ── Main loop ────────────────────────────────────────────────────────────────
echo "Ralph loop starting. Model: $MODEL  Ollama: $OLLAMA_HOST  Queue: $QUEUE"
echo "Press Ctrl-C to stop cleanly."
echo

while true; do
  TASK=$(pick_task)
  if [[ -z "$TASK" ]]; then
    echo "Queue empty. Ralph is done."
    exit 0
  fi

  TIMESTAMP=$(date '+%Y%m%d-%H%M%S')
  LOGFILE="$LOGS_DIR/ralph-$TIMESTAMP.md"

  # Parse fields: "<priority> | <category> | <description>"
  IFS='|' read -r PRIORITY CATEGORY DESCRIPTION <<< "$TASK"
  PRIORITY="${PRIORITY// /}"
  CATEGORY="${CATEGORY// /}"
  DESCRIPTION="${DESCRIPTION# }"
  DESCRIPTION="${DESCRIPTION% }"

  echo "[$TIMESTAMP] Attempting: $TASK"

  FAIL_N=$(fail_count_for "$TASK")
  PROMPT=$(make_prompt "$CATEGORY" "$DESCRIPTION")

  # Record SHA before aider runs so we can detect if a commit was made.
  PRE_SHA=$(git log -1 --format="%H" 2>/dev/null || echo "")

  # Run aider in one-shot mode against the local Ollama model.
  # aider reads the repo, applies edits, and commits automatically.
  set +e
  MODEL_OUTPUT=$(aider \
    --model "ollama/${MODEL}" \
    --openai-api-base "${OLLAMA_HOST}/v1" \
    --message "$PROMPT" \
    --yes \
    --no-stream \
    2>&1)
  MODEL_EXIT=$?
  set -e

  # Determine outcome: check for RALPH_FAIL marker or model exit error
  if [[ $MODEL_EXIT -ne 0 ]] || echo "$MODEL_OUTPUT" | grep -q "^RALPH_FAIL:"; then
    FAIL_N=$(( FAIL_N + 1 ))
    REASON=$(echo "$MODEL_OUTPUT" | grep "^RALPH_FAIL:" | head -1 || echo "model exit $MODEL_EXIT")

    cat > "$LOGFILE" <<LOG
# Ralph run $TIMESTAMP

## Task
$TASK

## Result
FAIL (attempt $FAIL_N/$MAX_FAIL)

## Reason
$REASON

## Model output (truncated)
$(echo "$MODEL_OUTPUT" | head -60)
LOG

    echo "  FAIL $FAIL_N/$MAX_FAIL: $REASON"

    if [[ $FAIL_N -ge $MAX_FAIL ]]; then
      echo "  Graduating task after $MAX_FAIL failures."
      remove_task "$TASK"
      # Remove any existing FAIL comment lines for this task
      TMPQ=$(mktemp)
      grep -v "^# FAIL .* | $(echo "$TASK" | sed 's/[.[\*^$]/\\&/g')" "$QUEUE" > "$TMPQ" 2>/dev/null || true
      mv "$TMPQ" "$QUEUE"
      {
        echo "## Graduated $(date '+%Y-%m-%d %H:%M')"
        echo "Task: $TASK"
        echo "Reason: failed $MAX_FAIL times. Last: $REASON"
        echo "Logs: $LOGS_DIR/ralph-$TIMESTAMP.md and predecessors"
        echo
      } >> "$GRADUATED"
      echo "  GRADUATED — check $GRADUATED"
    else
      # Update fail count in queue
      remove_task "$TASK"
      TMPQ=$(mktemp)
      # Remove old FAIL comment for this task first
      grep -v "^# FAIL .* | $(echo "$TASK" | sed 's/[.[\*^$]/\\&/g')" "$QUEUE" > "$TMPQ" 2>/dev/null || cp "$QUEUE" "$TMPQ"
      mv "$TMPQ" "$QUEUE"
      # Prepend updated fail-count comment + task back at top
      TMPQ=$(mktemp)
      { echo "# FAIL $FAIL_N | $TASK"; echo "$TASK"; cat "$QUEUE"; } > "$TMPQ"
      mv "$TMPQ" "$QUEUE"
    fi

  else
    # Success path: detect whether aider made a new commit.
    POST_SHA=$(git log -1 --format="%H" 2>/dev/null || echo "")
    if [[ "$POST_SHA" != "$PRE_SHA" ]]; then
      SHORT_SHA="${POST_SHA:0:7}"
      COMMIT_MSG=$(git log -1 --format="%s")
      cat > "$LOGFILE" <<LOG
# Ralph run $TIMESTAMP

## Task
$TASK

## Result
PASS

## Commit
SHA: $SHORT_SHA
Message: $COMMIT_MSG

## Model output (truncated)
$(echo "$MODEL_OUTPUT" | head -60)
LOG
      echo "  PASS  commit $SHORT_SHA  ($COMMIT_MSG)"
    else
      cat > "$LOGFILE" <<LOG
# Ralph run $TIMESTAMP

## Task
$TASK

## Result
PASS (no commit — aider may have decided no changes were needed)

## Model output (truncated)
$(echo "$MODEL_OUTPUT" | head -60)
LOG
      echo "  PASS (no commit)"
    fi

    remove_task "$TASK"
    # Clean any fail-count comments for this task
    TMPQ=$(mktemp)
    grep -v "^# FAIL .* | $(echo "$TASK" | sed 's/[.[\*^$]/\\&/g')" "$QUEUE" > "$TMPQ" 2>/dev/null || cp "$QUEUE" "$TMPQ"
    mv "$TMPQ" "$QUEUE"
  fi

  echo
done
