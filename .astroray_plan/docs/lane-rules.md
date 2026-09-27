# Lane rules (lead-run batched lanes)

Brief every implementation lane with this file. Proven over the 2026-09-24..27 session
(Batches U..AH). Main checkout = `C:\Users\hgcom\OneDrive\Astroray\Astroray_repo\Astroray`.

1. Work ONLY in your worktree, with absolute paths. Never edit the main checkout: the shell
   cwd resets to main, and .NET/relative paths have silently edited it. Run
   `git -C <main> status --porcelain` after scripted edits if in doubt.
2. Read `CLAUDE.md` and `AGENTS.md`. Run `python scripts/project_index.py query <topic>` before
   grepping `.astroray_plan/` or `scripts/`. Check `scripts/README.md` before writing a script.
3. Non-trivial physics/sampling: `cite-algorithm` (CLAUDE.md §6) — cite paper / licence-compatible
   reference in code, short note under `.astroray_plan/docs/`.
4. Compile-check every C++ commit with a CPU/MinGW build (`cmake --build <wt>\build_blender_addon
   --target astroray -j 6`). **Never build CUDA and never poll builds.** Commit, then end your turn
   with `BUILD REQUEST <full sha>`; the lead builds (`scripts/build/lead_build_queue.py`) and resumes you.
5. GPU runs only through `python <main>\scripts\build\gpu_locked_run.py <lane> -- <cmd>`. CPU-only
   runs take no lock. Never write/delete lock files, never run two GPU jobs, never kill processes by
   command-line match.
6. Commit WIP early; explicit paths only (never `add -A` / `commit -a`). Don't push or open PRs unless
   the lead says so.
7. Evidence (renders, tables, logs) under `C:\Users\hgcom\OneDrive\Astroray\astra_run\<batch>\<lane>\`.
   Look at every visual result yourself.
8. Every fix needs a test that fails before and passes after. Don't loosen thresholds to pass.
9. **Stale tests (owner 2026-09-25):** if a correct fix fails an existing test, investigate both sides.
   A test calibrated on an older, broken engine is corrected (re-pinned against Cycles or an analytic
   reference) in the same branch, with the reason in the commit message. Never revert a correct fix to
   keep a stale test green.
10. Attribute failures against a baseline build, never by reasoning about the diff.
11. Before done: list changed signatures, grep all callers (tests, mocks, bindings, conftest).
12. **Machine load (2026-09-26, two hardware resets):** OMP_NUM_THREADS=8, MinGW `-j 6`, no stress
    loops over ~10 min, small renders. The lead never overlaps a GPU suite with a build.
13. GPU shade kernel is register-saturated (REG 254): no new per-hit live state there; describe the
    expected register impact of GPU changes (the lead measures with cuobjdump).
14. Concise writing. Final report ≤ 25 lines: files, tests + numbers, evidence paths, risks, build need.
