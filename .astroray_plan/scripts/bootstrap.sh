#!/usr/bin/env bash
# One-time setup for Astroray development tracks.
# Run from the repo root: bash .astroray_plan/scripts/bootstrap.sh
#
# What this does:
#   1. Copies Copilot agent files into .github/
#   2. Verifies gh CLI is installed and authenticated
#   3. Prompts to trigger the copilot-setup-steps workflow manually

set -euo pipefail

die() { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }
ok()   { echo "    OK: $*"; }

# ── Paths ─────────────────────────────────────────────────────────────────────
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" \
  || die "Must be run from inside the Astroray git repository."

PLAN="$REPO_ROOT/.astroray_plan/agents"
GITHUB="$REPO_ROOT/.github"
WORKFLOWS="$GITHUB/workflows"

# ── Step 1: Copy Copilot files ────────────────────────────────────────────────
info "Copying Copilot agent files..."

mkdir -p "$WORKFLOWS"

SRC_INSTRUCTIONS="$PLAN/copilot-instructions.md"
DST_INSTRUCTIONS="$GITHUB/copilot-instructions.md"

SRC_WORKFLOW="$PLAN/copilot-setup-steps.yml"
DST_WORKFLOW="$WORKFLOWS/copilot-setup-steps.yml"

[[ -f "$SRC_INSTRUCTIONS" ]] || die "Missing: $SRC_INSTRUCTIONS"
[[ -f "$SRC_WORKFLOW" ]]     || die "Missing: $SRC_WORKFLOW"

if [[ -f "$DST_INSTRUCTIONS" ]]; then
  echo "    $DST_INSTRUCTIONS already exists. Overwrite? [y/N]"
  read -r REPLY
  [[ "$REPLY" =~ ^[Yy]$ ]] || { echo "    Skipped."; }
  [[ "$REPLY" =~ ^[Yy]$ ]] && cp "$SRC_INSTRUCTIONS" "$DST_INSTRUCTIONS" && ok "Wrote $DST_INSTRUCTIONS"
else
  cp "$SRC_INSTRUCTIONS" "$DST_INSTRUCTIONS"
  ok "Wrote $DST_INSTRUCTIONS"
fi

if [[ -f "$DST_WORKFLOW" ]]; then
  echo "    $DST_WORKFLOW already exists. Overwrite? [y/N]"
  read -r REPLY
  [[ "$REPLY" =~ ^[Yy]$ ]] || { echo "    Skipped."; }
  [[ "$REPLY" =~ ^[Yy]$ ]] && cp "$SRC_WORKFLOW" "$DST_WORKFLOW" && ok "Wrote $DST_WORKFLOW"
else
  cp "$SRC_WORKFLOW" "$DST_WORKFLOW"
  ok "Wrote $DST_WORKFLOW"
fi

# ── Step 2: Verify gh CLI ─────────────────────────────────────────────────────
info "Checking gh CLI..."

if ! command -v gh &>/dev/null; then
  echo
  echo "  gh CLI not found. Install it from https://cli.github.com/"
  echo "  Then run: gh auth login"
  echo "  Then re-run this script."
  exit 1
fi
ok "gh found: $(gh --version | head -1)"

if ! gh auth status &>/dev/null; then
  echo
  echo "  gh is not authenticated. Run: gh auth login"
  exit 1
fi
ok "gh authenticated."

# ── Step 3: Stage new files and summarise ─────────────────────────────────────
info "Staging .github/ files for commit..."
git add "$DST_INSTRUCTIONS" "$DST_WORKFLOW" 2>/dev/null || true

if git diff --cached --quiet; then
  echo "    Nothing new to stage (files already committed)."
else
  echo
  echo "  The following files are staged and ready to commit:"
  git diff --cached --name-only | sed 's/^/    /'
  echo
  echo "  Commit them with:"
  echo "    git commit -m \"chore: add Copilot agent files\""
fi

# ── Step 4: Prompt to trigger workflow ───────────────────────────────────────
echo
info "To verify the build environment, trigger the workflow manually:"
echo
echo "    gh workflow run copilot-setup-steps.yml"
echo
echo "  Check the result with:"
echo "    gh run list --workflow=copilot-setup-steps.yml --limit=5"
echo

info "Bootstrap complete."
