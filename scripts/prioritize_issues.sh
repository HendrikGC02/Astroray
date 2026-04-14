#!/usr/bin/env bash
# =============================================================================
# prioritize_issues.sh
#
# Run this AFTER create_cycles_parity_issues.sh to add milestones and
# priority labels to the existing issues.
#
# Creates 6 milestones (sequential phases) and 4 priority labels.
# Assigns each issue to its milestone and priority based on the
# dependency graph.
#
# Usage:
#   chmod +x scripts/prioritize_issues.sh
#   ./scripts/prioritize_issues.sh
# =============================================================================
set -euo pipefail

echo "=== Creating priority labels ==="
gh label create "P0-critical"  --description "Do first — blocks everything else"  --color "B60205" 2>/dev/null || true
gh label create "P1-high"      --description "Core functionality, do early"       --color "D93F0B" 2>/dev/null || true
gh label create "P2-medium"    --description "Important but not blocking"          --color "FBCA04" 2>/dev/null || true
gh label create "P3-low"       --description "Nice to have, do when time allows"  --color "0E8A16" 2>/dev/null || true

echo ""
echo "=== Creating milestones ==="
gh api repos/{owner}/{repo}/milestones -f title="M1: Foundation" \
  -f description="Pipeline fixes that affect ALL subsequent work. Do these first, in order." \
  -f state=open 2>/dev/null || echo "  (M1 may already exist)"

gh api repos/{owner}/{repo}/milestones -f title="M2: Core Integrator" \
  -f description="Path tracing loop improvements: bounce limits, clamping, caustics, transparency." \
  -f state=open 2>/dev/null || echo "  (M2 may already exist)"

gh api repos/{owner}/{repo}/milestones -f title="M3: Materials & Textures" \
  -f description="BSDF parity, texture nodes, normal/bump maps. The biggest visual impact phase." \
  -f state=open 2>/dev/null || echo "  (M3 may already exist)"

gh api repos/{owner}/{repo}/milestones -f title="M4: Lighting & World" \
  -f description="Proper light shapes, sun/spot lights, world volumes, environment settings." \
  -f state=open 2>/dev/null || echo "  (M4 may already exist)"

gh api repos/{owner}/{repo}/milestones -f title="M5: Render Passes & Post" \
  -f description="Component passes, data passes, Cryptomatte, OIDN denoiser." \
  -f state=open 2>/dev/null || echo "  (M5 may already exist)"

gh api repos/{owner}/{repo}/milestones -f title="M6: Advanced & Polish" \
  -f description="Motion blur, hair, tiled rendering, persistent data, view layers." \
  -f state=open 2>/dev/null || echo "  (M6 may already exist)"

echo ""
echo "=== Assigning issues to milestones and priorities ==="
echo ""
echo "NOTE: This uses keyword search on issue titles."
echo "If titles differ from the script, adjust the search terms."
echo ""

# Helper: find issue number by title keyword, assign milestone + priority
assign() {
    local keyword="$1"
    local milestone="$2"
    local priority="$3"

    local num
    num=$(gh issue list --search "$keyword" --json number -q '.[0].number' 2>/dev/null)
    if [ -n "$num" ] && [ "$num" != "null" ]; then
        echo "  #$num: $keyword → $milestone + $priority"
        gh issue edit "$num" --milestone "$milestone" --add-label "$priority" 2>/dev/null || true
    else
        echo "  SKIP: No issue found matching '$keyword'"
    fi
    sleep 0.5
}

echo "--- M1: Foundation (P0) ---"
assign "Proper linear output"                        "M1: Foundation"        "P0-critical"
assign "Per-face material"                           "M1: Foundation"        "P0-critical"
assign "Per-corner normals"                          "M1: Foundation"        "P0-critical"
assign "Film exposure setting"                       "M1: Foundation"        "P0-critical"

echo ""
echo "--- M2: Core Integrator (P1) ---"
assign "Per-bounce-type max bounces"                 "M2: Core Integrator"   "P1-high"
assign "Separate direct and indirect clamping"       "M2: Core Integrator"   "P1-high"
assign "Caustics control"                            "M2: Core Integrator"   "P1-high"
assign "Seed control"                                "M2: Core Integrator"   "P2-medium"
assign "Transparent/alpha shadows"                   "M2: Core Integrator"   "P1-high"
assign "Transparent film"                            "M2: Core Integrator"   "P1-high"
assign "Pixel filter type"                           "M2: Core Integrator"   "P2-medium"
assign "Adaptive sampling matching Cycles"           "M2: Core Integrator"   "P2-medium"

echo ""
echo "--- M3: Materials & Textures (P1-P2) ---"
assign "Multi-scatter GGX"                           "M3: Materials & Textures" "P1-high"
assign "All standalone BSDF shader nodes"            "M3: Materials & Textures" "P1-high"
assign "Mix Shader and Add Shader"                   "M3: Materials & Textures" "P1-high"
assign "Principled Volume"                           "M3: Materials & Textures" "P1-high"
assign "Normal Map and Bump"                         "M3: Materials & Textures" "P1-high"
assign "procedural texture nodes"                    "M3: Materials & Textures" "P2-medium"
assign "Texture coordinate node"                     "M3: Materials & Textures" "P2-medium"
assign "Color processing nodes"                      "M3: Materials & Textures" "P2-medium"
assign "Converter nodes"                             "M3: Materials & Textures" "P2-medium"
assign "Image texture interpolation"                 "M3: Materials & Textures" "P2-medium"
assign "Image texture projection"                    "M3: Materials & Textures" "P3-low"
assign "F82 tint"                                    "M3: Materials & Textures" "P2-medium"
assign "Diffuse roughness"                           "M3: Materials & Textures" "P2-medium"
assign "Thin film iridescence"                       "M3: Materials & Textures" "P3-low"
assign "Volumetric absorption"                       "M3: Materials & Textures" "P2-medium"

echo ""
echo "--- M4: Lighting & World (P1-P2) ---"
assign "Area lights with shapes"                     "M4: Lighting & World"  "P1-high"
assign "Spot lights"                                 "M4: Lighting & World"  "P1-high"
assign "Sun light with angular"                      "M4: Lighting & World"  "P1-high"
assign "World volume"                                "M4: Lighting & World"  "P2-medium"
assign "World settings — MIS"                        "M4: Lighting & World"  "P2-medium"
assign "IES light"                                   "M4: Lighting & World"  "P3-low"
assign "Light portals"                               "M4: Lighting & World"  "P3-low"

echo ""
echo "--- M5: Render Passes & Post (P2) ---"
assign "Full render pass support"                    "M5: Render Passes & Post" "P2-medium"
assign "Data passes"                                 "M5: Render Passes & Post" "P2-medium"
assign "Cryptomatte"                                 "M5: Render Passes & Post" "P3-low"
assign "OIDN denoiser"                               "M5: Render Passes & Post" "P2-medium"

echo ""
echo "--- M6: Advanced & Polish (P2-P3) ---"
assign "View layer support"                          "M6: Advanced & Polish" "P2-medium"
assign "Holdout and indirect-only"                   "M6: Advanced & Polish" "P3-low"
assign "Motion blur"                                 "M6: Advanced & Polish" "P3-low"
assign "Hair/curves"                                 "M6: Advanced & Polish" "P3-low"
assign "Subdivision surface"                         "M6: Advanced & Polish" "P2-medium"
assign "Smooth shading interpolation"                "M6: Advanced & Polish" "P2-medium"
assign "Output format cooperation"                   "M6: Advanced & Polish" "P2-medium"
assign "Tiled rendering"                             "M6: Advanced & Polish" "P3-low"
assign "Persistent data"                             "M6: Advanced & Polish" "P3-low"
assign "Displacement"                                "M6: Advanced & Polish" "P3-low"
assign "Vertex colors"                               "M6: Advanced & Polish" "P3-low"

echo ""
echo "============================================"
echo "  Prioritization complete!"
echo "============================================"
echo ""
echo "View your milestones:  gh api repos/{owner}/{repo}/milestones -q '.[].title'"
echo "View P0 issues:        gh issue list --label P0-critical"
echo "View M1 issues:        gh issue list --milestone 'M1: Foundation'"
echo ""
echo "ASSIGNMENT ORDER:"
echo "  1. Assign ALL M1 issues to @copilot first (there are only 4)"
echo "  2. Wait for M1 PRs to merge"
echo "  3. Assign M2 P1-high issues (5 issues)"
echo "  4. While M2 is in progress, start M3 P1-high issues (they're independent)"
echo "  5. Continue down the milestones"
echo ""
