#!/usr/bin/env bash
# =============================================================================
# autonomous_loop.sh
# The "Ralph Wiggum" Autonomous Engineering Loop
#
# Pattern: think → plan → code → test → fix → (repeat until green)
#          Only commits to Git when tests pass.
#
# Usage:
#   ./scripts/autonomous_loop.sh [docs/PRD.md] [max_iterations]
#
# Dependencies: aider-local (wrapper created by setup_tools.sh), bd (beads),
#               git, and a running vLLM server (launch_vllm.sh)
# =============================================================================
set -euo pipefail

# --- Colours -----------------------------------------------------------------
RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
info()    { echo -e "${GREEN}[RALPH]${NC} $*"; }
warn()    { echo -e "${YELLOW}[RALPH]${NC} $*"; }
loop_hdr(){ echo -e "${CYAN}${BOLD}════════════════════════════════════════${NC}"; \
            echo -e "${CYAN}${BOLD}  Iteration $1 / $2${NC}"; \
            echo -e "${CYAN}${BOLD}════════════════════════════════════════${NC}"; }

# =============================================================================
# CONFIGURATION
# =============================================================================
PRD_FILE="${1:-docs/PRD.md}"
MAX_ITERATIONS="${2:-20}"

VLLM_BASE_URL="http://localhost:8080/v1"
MODEL_ID="QuantTrio/Qwen3.5-35B-A3B-AWQ"

# The test command to run after each code generation attempt.
# Build the C++ project first, then run pytest.
TEST_CMD="${TEST_CMD:-cmake --build build --parallel $(nproc) && python -m pytest tests/ -x -q --tb=short}"

# Aider will be given these files as context in addition to auto-detected ones.
WATCH_FILES="${WATCH_FILES:-include/raytracer.h include/advanced_features.h apps/main.cpp module/blender_module.cpp}"

# Maximum consecutive failures before Ralph gives up on the current task
MAX_FAILURES=5

# vLLM health check before starting
VLLM_CHECK_TIMEOUT=10

# Beads task prefix for this project (keeps issue IDs short and readable)
BD_PREFIX="${BD_PREFIX:-Astroray}"

# Git branch prefix for task branches
GIT_BRANCH_PREFIX="ralph/"

# =============================================================================
# PRE-FLIGHT CHECKS
# =============================================================================
info "=== PRE-FLIGHT ==="

# 1. Confirm we are inside a Git repo
git rev-parse --git-dir &>/dev/null \
    || { echo -e "${RED}[FATAL]${NC} Not in a git repo. Run: git init"; exit 1; }

# 2. PRD file exists
[[ -f "${PRD_FILE}" ]] \
    || { echo -e "${RED}[FATAL]${NC} PRD file '${PRD_FILE}' not found.
Create it with a description of the project requirements."; exit 1; }

# 3. aider-local is on PATH
command -v aider-local &>/dev/null \
    || { echo -e "${RED}[FATAL]${NC} aider-local not found. Run setup_tools.sh first."; exit 1; }

# 4. bd (beads) is on PATH
command -v bd &>/dev/null \
    || { echo -e "${RED}[FATAL]${NC} bd (beads) not found. Run setup_tools.sh first."; exit 1; }

# 5. vLLM server is reachable
info "Checking vLLM server at ${VLLM_BASE_URL}..."
if ! curl -sf --max-time "${VLLM_CHECK_TIMEOUT}" \
        "${VLLM_BASE_URL}/models" -o /dev/null; then
    echo -e "${RED}[FATAL]${NC} vLLM server is not reachable at ${VLLM_BASE_URL}."
    echo "Start it with: ./launch_vllm.sh"
    exit 1
fi
info "vLLM server OK."

# 6. Working tree is clean (no uncommitted changes that could be clobbered)
if git rev-parse --verify HEAD >/dev/null 2>&1 && ! git diff --quiet HEAD 2>/dev/null; then
    warn "You have uncommitted changes. Ralph will not commit partial work,"
    warn "but aider may modify tracked files. Consider committing or stashing."
    sleep 3
fi

# =============================================================================
# BEADS INITIALISATION
# =============================================================================
info "=== BEADS INIT ==="

# Initialise beads silently if not already set up in this repo
if [[ ! -d ".beads" ]]; then
    info "Initialising beads in this repo..."
    bd init --quiet
    # Set a short project prefix so issue IDs stay readable in logs
    git config beads.prefix "${BD_PREFIX}" 2>/dev/null || true
    info "Beads initialised with prefix '${BD_PREFIX}-'"
else
    info "Beads already initialised."
fi

# Create (or retrieve) the root epic for this PRD
ROOT_EPIC_TITLE="Ralph loop: $(basename "${PRD_FILE}" .md)"
EXISTING_EPIC=$(bd list --json 2>/dev/null \
    | python3 -c "
import sys, json
raw = sys.stdin.read().strip()
items = json.loads(raw) if raw else []
for i in items:
    if '${ROOT_EPIC_TITLE}' in i.get('title',''):
        print(i['id'])
        break
" 2>/dev/null || true)

if [[ -z "${EXISTING_EPIC}" ]]; then
    ROOT_EPIC_ID=$(bd create "${ROOT_EPIC_TITLE}" \
        --description "Autonomous loop driven by ${PRD_FILE}" \
        --priority 0 \
        --type epic \
        --json 2>/dev/null | python3 -c "import sys,json; raw=sys.stdin.read().strip(); print(json.loads(raw)['id'] if raw else '')")
    info "Created root epic: ${ROOT_EPIC_ID}"
else
    ROOT_EPIC_ID="${EXISTING_EPIC}"
    info "Using existing root epic: ${ROOT_EPIC_ID}"
fi

# =============================================================================
# HELPER: DECOMPOSE PRD INTO BEADS TASKS (one-shot if tasks don't exist yet)
# =============================================================================
decompose_prd_into_tasks() {
    local ready_count
    ready_count=$(bd ready --json 2>/dev/null | python3 -c \
        "import sys,json; raw=sys.stdin.read().strip(); print(len(json.loads(raw)) if raw else 0)" 2>/dev/null || echo "0")

    if [[ "${ready_count}" -gt 0 ]]; then
        info "Beads already has ${ready_count} ready tasks — skipping decomposition."
        return
    fi

    info "No tasks found. Asking the agent to decompose the PRD into Beads tasks..."

    # We call aider in message-only mode to decompose the PRD.
    # --message instructs it to just output bd commands; we execute them.
    DECOMPOSE_PROMPT="Read ${PRD_FILE} carefully.
Then output ONLY a series of 'bd create' shell commands (one per line, no
explanation, no markdown fences) to create tasks in the beads issue tracker.
Each task should:
- Have a clear, actionable title
- Include --priority (0=critical, 1=high, 2=medium, 3=low)
- Use '--parent ${ROOT_EPIC_ID}' for all tasks
- Use '--dep TASK_ID' where one task blocks another
Do not output anything except the bd commands."

    TMPFILE=$(mktemp /tmp/ralph_decompose_XXXXXX.sh)
    trap "rm -f ${TMPFILE}" EXIT
    aider-local \
        --message "${DECOMPOSE_PROMPT}" \
        --read "${PRD_FILE}" \
        --yes \
        2>/dev/null \
        | grep '^bd create' \
        > "${TMPFILE}" || true

    TASK_COUNT=$(wc -l < "${TMPFILE}")
    if [[ "${TASK_COUNT}" -gt 0 ]]; then
        info "Executing ${TASK_COUNT} task creation commands..."
        bash "${TMPFILE}"
    else
        warn "Agent did not emit any 'bd create' commands. Creating a single task."
        bd create "Implement: $(head -1 "${PRD_FILE}")" \
            --parent "${ROOT_EPIC_ID}" \
            --priority 1
    fi
    rm -f "${TMPFILE}"
}

# =============================================================================
# HELPER: PICK NEXT TASK
# =============================================================================
get_next_task_id() {
    # 'bd ready --json' returns tasks with no open blockers, sorted by priority.
    bd ready --json 2>/dev/null \
        | python3 -c "
import sys, json
raw = sys.stdin.read().strip(); tasks = json.loads(raw) if raw else []
# Pick the highest-priority unassigned task
for t in tasks:
    if t.get('assignee', '') == '':
        print(t['id'])
        break
" 2>/dev/null || true
}

get_task_title() {
    local task_id="$1"
    bd show "${task_id}" --json 2>/dev/null \
        | python3 -c "import sys,json; raw=sys.stdin.read().strip(); print(json.loads(raw).get('title','') if raw else '')" \
        2>/dev/null || echo "unknown task"
}

# =============================================================================
# HELPER: RECORD TEST OUTPUT IN BEADS
# =============================================================================
record_failure_in_beads() {
    local task_id="$1"
    local iteration="$2"
    local test_output="$3"
    # Truncate to avoid hitting Beads comment size limits
    TRUNCATED=$(echo "${test_output}" | tail -50)
    bd comment "${task_id}" \
        "Iteration ${iteration} test FAILED:\n\`\`\`\n${TRUNCATED}\n\`\`\`" \
        2>/dev/null || true
}

record_success_in_beads() {
    local task_id="$1"
    local git_sha="$2"
    bd update "${task_id}" --status done \
        --resolution "Tests passed. Committed: ${git_sha}" \
        2>/dev/null || true
}

# =============================================================================
# MAIN LOOP
# =============================================================================
info "=== STARTING RALPH LOOP ==="
info "PRD          : ${PRD_FILE}"
info "Max iters    : ${MAX_ITERATIONS}"
info "Test command : ${TEST_CMD}"
echo ""

# Decompose the PRD on first run
decompose_prd_into_tasks

ITERATION=0
FAILURES=0
CURRENT_TASK_ID=""

while [[ "${ITERATION}" -lt "${MAX_ITERATIONS}" ]]; do
    ITERATION=$((ITERATION + 1))
    loop_hdr "${ITERATION}" "${MAX_ITERATIONS}"

    # ------------------------------------------------------------------
    # PHASE 1: PICK A TASK
    # ------------------------------------------------------------------
    if [[ -z "${CURRENT_TASK_ID}" ]]; then
        CURRENT_TASK_ID=$(get_next_task_id)
        if [[ -z "${CURRENT_TASK_ID}" ]]; then
            info "🎉 No more ready tasks in Beads. All work is complete!"
            bd list --status open 2>/dev/null | head -20 || true
            break
        fi
        TASK_TITLE=$(get_task_title "${CURRENT_TASK_ID}")
        info "📋 Picked task: [${CURRENT_TASK_ID}] ${TASK_TITLE}"
        # Claim the task so multi-agent setups know it's taken
        bd update "${CURRENT_TASK_ID}" \
            --status in_progress \
            --assignee "ralph-loop" \
            2>/dev/null || true
        # Create a feature branch for this task
        BRANCH_NAME="${GIT_BRANCH_PREFIX}${CURRENT_TASK_ID}"
        if git checkout -b "${BRANCH_NAME}" 2>/dev/null; then
            info "Created new branch: ${BRANCH_NAME}"
        elif git checkout "${BRANCH_NAME}" 2>/dev/null; then
            info "Checked out existing branch: ${BRANCH_NAME}"
        else
            warn "Failed to checkout/branch ${BRANCH_NAME}. Current branch unchanged."
            exit 1
        fi
        FAILURES=0
    fi

    # ------------------------------------------------------------------
    # PHASE 2: THINK + PLAN + CODE  (aider)
    # ------------------------------------------------------------------
    TASK_TITLE=$(get_task_title "${CURRENT_TASK_ID}")

    # Build the aider prompt.  On a failure, we feed back the test output.
    if [[ "${FAILURES}" -eq 0 ]]; then
        AIDER_MSG="Task [${CURRENT_TASK_ID}]: ${TASK_TITLE}

Refer to ${PRD_FILE} for full project context.
Your goal: implement the changes needed to complete this task.
After writing code, make sure all public functions have docstrings.
Do not modify test files unless the test is clearly wrong."
    else
        AIDER_MSG="Task [${CURRENT_TASK_ID}]: ${TASK_TITLE}

The previous implementation FAILED tests (failure ${FAILURES}/${MAX_FAILURES}).
Test output:
---
${LAST_TEST_OUTPUT:-no output captured}
---
Fix the code so the tests pass. Do not give up.
If you suspect a test file is wrong, explain why in a comment but do not modify it."
    fi

    info "🤖 Calling aider for code generation (failure count: ${FAILURES})..."

    # Run aider in --yes mode (non-interactive) with our vLLM backend.
    # We pass the PRD and any watch files as read-only context.
    AIDER_ARGS=(
        --message "${AIDER_MSG}"
        --read "${PRD_FILE}"
        --yes
        --no-auto-commits   # Ralph owns the commit decision
    )
    if [[ -n "${WATCH_FILES}" ]]; then
        AIDER_ARGS+=("--read" ${WATCH_FILES})
    fi

    # Capture aider output for logging; don't fail the loop if aider itself errors
    AIDER_OUTPUT=""
    AIDER_OUTPUT=$(aider-local "${AIDER_ARGS[@]}" 2>&1) || {
        warn "aider exited with non-zero status; reviewing test results anyway."
    }

    info "aider run complete."

    # ------------------------------------------------------------------
    # PHASE 3: TEST
    # ------------------------------------------------------------------
    info "🧪 Running tests: ${TEST_CMD}"
    LAST_TEST_OUTPUT=""
    TEST_EXIT_CODE=0

    # Capture both stdout and stderr; tee so we see it in the terminal too
    LAST_TEST_OUTPUT=$(bash -c "${TEST_CMD}" 2>&1 | tee /dev/tty) \
        || TEST_EXIT_CODE=$?

    # ------------------------------------------------------------------
    # PHASE 4: DECIDE — COMMIT or FIX
    # ------------------------------------------------------------------
    if [[ "${TEST_EXIT_CODE}" -eq 0 ]]; then
        info "✅ Tests PASSED."

        # Stage all changes made by aider
        git add -A

        # Only commit if there are staged changes
        if git diff --cached --quiet; then
            warn "No file changes to commit (aider may have determined no changes needed)."
        else
            COMMIT_MSG="ralph: [${CURRENT_TASK_ID}] ${TASK_TITLE}

Autonomous commit — tests passed on iteration ${ITERATION}.
$(bd show "${CURRENT_TASK_ID}" --json 2>/dev/null \
    | python3 -c "import sys,json; raw=sys.stdin.read().strip(); d=json.loads(raw) if raw else {}; print(d.get('description',''))" \
    2>/dev/null || true)"

            git commit -m "${COMMIT_MSG}"
            GIT_SHA=$(git rev-parse --short HEAD)
            info "🔒 Committed: ${GIT_SHA}"
        fi

        # Mark done in Beads
        record_success_in_beads "${CURRENT_TASK_ID}" "$(git rev-parse --short HEAD)"

        # Reset for next task
        CURRENT_TASK_ID=""
        FAILURES=0

    else
        FAILURES=$((FAILURES + 1))
        warn "❌ Tests FAILED (attempt ${FAILURES}/${MAX_FAILURES})."

        # Record the failure in Beads for audit trail
        record_failure_in_beads "${CURRENT_TASK_ID}" "${ITERATION}" "${LAST_TEST_OUTPUT}"

        if [[ "${FAILURES}" -ge "${MAX_FAILURES}" ]]; then
            warn "Reached max failures (${MAX_FAILURES}) for task [${CURRENT_TASK_ID}]."
            warn "Marking task as blocked and moving to next task."
            bd update "${CURRENT_TASK_ID}" \
                --status blocked \
                --resolution "Exceeded max failures in Ralph loop. Needs human review." \
                2>/dev/null || true

            # Stash unsaved changes so the next task starts clean
            git stash push -m "ralph: failed work on ${CURRENT_TASK_ID}" \
                2>/dev/null || true

            CURRENT_TASK_ID=""
            FAILURES=0
        else
            info "Feeding test output back to agent on next iteration..."
        fi
    fi

    echo ""
done

# =============================================================================
# SUMMARY
# =============================================================================
echo ""
echo -e "${CYAN}${BOLD}════════════════════════════════════════${NC}"
echo -e "${CYAN}${BOLD}  RALPH LOOP COMPLETE — SUMMARY${NC}"
echo -e "${CYAN}${BOLD}════════════════════════════════════════${NC}"
echo ""
info "Iterations run : ${ITERATION}"
info "Git log (last 10 commits):"
git log --oneline -10 2>/dev/null | sed 's/^/  /'
echo ""
info "Open Beads tasks:"
bd list --status open 2>/dev/null | head -20 || true
echo ""
info "To review blocked tasks:"
info "  bd list --status blocked"
info ""
info "To push to remote and open PRs:"
info "  git push origin ${GIT_BRANCH_PREFIX}<task-id>"
