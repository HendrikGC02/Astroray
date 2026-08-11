# Repo hygiene run — 2026-08-11/12

Owner-directed comprehensive cleanup (PR #587). This doc is the durable
record; read it before assuming something deleted here is "missing".

## What was removed and why

| Category | Items | Rationale |
|---|---|---|
| Worktrees | 10 of 12 `.claude/worktrees/*` dirs (~7 GB) | branches merged or unregistered leftovers; kept the two open-PR worktrees (#585, #586) |
| Local branches | 75 | merged/closed PR heads + concluded investigation branches |
| Scripts | 31 (diag one-offs, pkg-verify one-offs, superseded wrappers, retired agent tooling) | zero live references; per-script evidence in the PR body |
| Engine | 4 caller-less CUDA kernels + `advancePathSlot` wrapper + uncompiled Phase-A.1 cluster + `blender_integration.h` + `uv_debug_aov` plugin (~1600 lines) | dead code; polluted cuobjdump reports and misled greps |
| CMake | `WIN32_STANDALONE`, `BUILD_TESTS` options; OpenEXR block relocated | dead flags; latent configure hard-fail (EXR writer was silently never compiled) |
| Tool residue | `.beads/`, `.aider.*`, `.clinerules`, copilot files, April multi-track handbooks (archived), `chi2_data.py`, root stray renders | dead workflows / accidental commits |
| Build trees | `build_tcnn/`, `build_blender_addon_tcnn/` (~1.5 GB) | tcnn now opt-in; artifacts were months stale |
| Images | `test_results/` (~500 files), refbank `results/` history, root PNGs → `../Astroray_image_backup_2026-08-11/` | superseded generations; fresh outputs regenerated 2026-08-12 |

## Structural changes

- tcnn/NRC is opt-in everywhere (no default builds it); engine plugin + tests unchanged.
- `benchmarks/showcase/` is the ONE canonical contact-sheet/showcase generator
  (curated presets in `config.MATERIAL_ZOO_VARIANTS`).
- `scripts/README.md` = canonical per-task script index; CLAUDE.md §5b /
  AGENTS.md now require checking it before writing any new script.
- `docs/agent-context/renderer-internals.md` rewritten from current code
  (previous version described the deleted pre-spectral API).
- Both `build_cuda_worktree.bat` copies are intentionally different pipelines
  (root = VS-generator, agent-pinned; `scripts/build/` = Ninja+sccache) — documented, neither deleted.

## Verification

Full clean-build RTX sweep (native sm_120, 2026-08-12): **1848 passed /
1 failed** — the failure is pkg185 (pre-existing on main). Showcase
(`--quick --gpu`, 63 rows) + refbank full run regenerated; refbank's 3
SSIM-only failures are stale pre-pkg181 references (renders visually
verified healthy).

## Findings → action items

1. **pkg185** — GPU glass-sphere caustic parity SSIM 0.01 (pre-existing on
   main, only substantive red in the sweep). Fix first.
2. **pkg183** — incremental-build staleness guard. This run's crash
   investigation was almost entirely phantom failures from ABI-mixed stale
   incremental builds (OneDrive mtimes + layout-changing merges), including
   a fabricated git-bisect first-bad-commit. Clean builds exonerated
   everything. Never baseline a crash investigation on an incremental build.
3. **pkg184** — `HasPhotons` isolation in the REG:254 shade kernel (perf lever).
4. **Refbank re-bless** — references pre-date pkg181's intentional
   brightening; 3 scenes fail SSIM-only while all content gates pass. The
   unmerged local branch `repin-post-pkg181` (owner-decision disney-sweep
   re-bless, 2026-08-09) was never merged — fold it into a refbank re-bless
   round or discard it deliberately.
5. **Remote branches** — 98 merged/closed-PR remote branches remain (bulk
   deletion was left to the owner). One-shot cleanup:
   `gh pr list -s merged -L 600 --json headRefName -q '.[].headRefName' | sort -u | xargs -n1 git push origin --delete`
   (or enable GitHub's "Automatically delete head branches").
6. The `test_python_bindings.py` deferred-xfail cluster (15 RGB-era feature
   xfails) needs an owner keep/abandon decision.
