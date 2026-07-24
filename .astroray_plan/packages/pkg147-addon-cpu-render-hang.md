# pkg147 — Blender addon CPU render hangs at any resolution > 16px

**Pillar:** 5 (Blender addon reliability)
**Track:** A
**Codex-paste-ready:** no (Blender-in-the-loop debugging; needs headless Blender 5.1 + build access)
**Status:** done (PR #520, merged 2026-07-25 squash 0c3b1a3 — root cause confirmed as the suspected OpenMP/GIL precedent; structural guard added; 32px and 256px CPU addon renders both 0.01-0.05s on the currently-deployed build, which was already unaffected). See "Findings (2026-07-25)" below.

<details><summary>Original 2026-07-24 dispatch note</summary>

open — dispatchable. **2026-07-24 re-assessment (architect): overnight-SAFE with guardrails — scheduled as Lane C of the 2026-07-24 overnight run.** The 2026-07-23 "not overnight" call assumed interactive debugging; in practice headless Blender 5.1 is local (memory `blender-5-1-installed-locally`) and the hang IS the observable — every diagnostic is a scriptable pass/timeout. **Mandatory guardrails:** (1) every Blender invocation runs as a subprocess with a hard external timeout (≤120 s per render attempt) and is killed on expiry — never render in the agent's own process, never wait on a hung Blender; (2) first diagnostic is the cheap one: which `.pyd` did the failing repro load (`astroray.__file__`) and was it OpenMP-enabled (the `mingw_openmp_blender_deadlock` / pkg115-generalized MSVC-vcomp precedent — **any addon-use build needs `-DASTRORAY_DISABLE_OPENMP=ON`**); (3) if the OpenMP-free addon build still hangs, bisect the glue per the Suspected-layer list, each probe timeout-bounded; (4) time-box the package to ~3 h — if no root cause by then, write up the bisection state and stop. Files are fully disjoint from Lanes A/B (`blender_addon/`, build scripts/flags).

</details>
**Estimated effort:** S–M (diagnosis-first; the fix is likely a build/threading flag or a glue-loop bug, not new features)
**Depends on:** none

**Origin:** pkg146 investigation (PR #514). Never hit before because every prior
oracle ran `device_mode='gpu'`.

---

## Repro (measured, PR #514)

Addon `render()` with `device_mode='cpu'` inside Blender:

- **16×16 completes in 0.01 s.**
- **32×32 freezes indefinitely** — CPU time pinned for 12+ min, no progress, no error.
- **Direct Python bindings** (same build, outside Blender) render 64×64 CPU scenes
  instantly — the engine's CPU path is fine; the defect is specific to the
  **addon/Blender render glue**.

Repro artifacts: `Astroray-pkg146` worktree,
`test_results/pkg146_oracle/cpu_render_hang_repro/`.
Findings doc: `.astroray_plan/docs/pkg146-equal-wattage-findings.md` (PR #514).

## Suspected layer

Addon render glue and/or an OpenMP/threading interaction inside Blender. This
smells like the known precedent (memory `mingw_openmp_blender_deadlock`, later
generalized to MSVC/vcomp in the pkg115 diagnosis, PR #471): **any addon-use
`.pyd` must be built with `-DASTRORAY_DISABLE_OPENMP=ON`** — an OpenMP-enabled
build deadlocks inside Blender on the CPU path while the GPU path (no OpenMP
loops) masks it. First diagnostic step: confirm which `.pyd` the failing repro
loaded (`astroray.__file__`) and whether it was an OpenMP-enabled build. If the
OpenMP-free addon build still hangs, bisect the glue: tile/chunk loop, progress
callback, GIL interaction, or a threads-vs-Blender-job conflict in
`blender_addon/` render dispatch. The 16px-works/32px-hangs threshold suggests a
thread-count or tiling boundary (e.g. work splitting kicks in above one tile).

## Acceptance gate

- A 32×32 **and** a 256×256 CPU addon render (`device_mode='cpu'`, headless
  Blender 5.1) complete within a sane walltime bound (seconds, not minutes),
  verified in the repro harness; root cause written up.
- GPU addon path and direct-bindings CPU path unchanged (regression suite green).
- If the root cause is the OpenMP build flag: the guard becomes structural
  (build-time check or runtime assert in the addon), not tribal knowledge.

## Non-goals

- No CPU-path performance work beyond un-hanging it.
- Does not block pkg146 — its oracle runs GPU.

## Findings (2026-07-25)

**Root cause confirmed: hypothesis (a), the OpenMP/GIL precedent, generalized
to BOTH MinGW (libgomp) and MSVC (vcomp).**

1. **The currently-deployed addon `.pyd`** (`.../extensions/user_default/astroray`,
   build-ID `5503ee2+20260612T143020Z`, tcnn/CUDA backend) is **already
   OpenMP-disabled** (`build_report.json` cmake_flags includes
   `-DASTRORAY_DISABLE_OPENMP=ON` — `build_blender_addon.py`'s `common_opts`
   applies this flag unconditionally for every backend). Measured directly in
   headless Blender 5.1, `device_mode='cpu'`: 16×16 = 0.042s, 32×32 = 0.010s,
   256×256 = 0.053s. **No hang on the deployed build, at any size tested.**
2. **Mechanism, isolated Blender-independently**: `PyRenderer::render()`
   (`module/blender_module.cpp:1655`) does not release the GIL for the
   duration of the call. Its progress-callback lambda does
   `py::gil_scoped_acquire acquire; progressCallback(progress);`
   (`blender_module.cpp:1796-1800`), and `Renderer::render()`
   (`include/raytracer.h:2975` `#pragma omp parallel for schedule(dynamic)
   collapse(2)`, tileSize=16) calls `progress(...)` at
   `raytracer.h:3167` from **whichever OpenMP worker thread finishes a tile**
   — not necessarily the thread that called `render()` and holds the GIL.
   When OpenMP is compiled in, a worker thread's `gil_scoped_acquire`
   deadlocks against the calling thread, which is blocked in the implicit
   end-of-parallel-region barrier while still holding the GIL. Reproduced in
   plain Python (no Blender at all) against a from-scratch OpenMP-enabled
   CPU-only build: hangs with a progress callback (even at 16×16 — the
   16px-safe boundary from the original repro is a race, not a guarantee:
   whichever thread the OpenMP runtime schedules the lone tile onto), renders
   instantly (0.13s @ 32×32) with `progress_callback=None` (matches "direct
   Python bindings ... complete instantly" in the pkg146 repro, since those
   never pass a callback).
3. **The routine dev/CUDA build path (`configure_and_build.bat`,
   `build_cuda_worktree.bat`) also compiles with OpenMP enabled by default**
   (`ASTRORAY_DISABLE_OPENMP` defaults `OFF`) — confirmed by objdump: the
   `astroray.cp313-win_amd64.pyd` built via this repo's own
   `build_cuda_worktree.bat` links `VCOMP140.DLL`. If that `.pyd` is ever
   dropped into the Blender addon directory (a very plausible mistake — this
   is almost certainly what the pkg146 repro's `.pyd` was), it reproduces the
   hang exactly. This is the most likely explanation for how pkg146 hit it in
   the first place.
4. **A latent gap discovered and fixed while building the guard:**
   `OpenMP_CXX_FOUND` (CMakeLists.txt) is only ever set via
   `find_package(OpenMP)` in the GNU/Clang branch; the MSVC branch adds
   `/openmp` directly without touching that variable. A first draft of the
   feature-detection compile-definition, gated on `OpenMP_CXX_FOUND`, silently
   misreported `openmp: False` for the MSVC/CUDA build that actually links
   `VCOMP140.DLL`. Fixed by gating on `ASTRORAY_DISABLE_OPENMP` directly (the
   one option both compiler branches gate their real `/openmp`/`-fopenmp` on).

**Fix shipped:**
- `CMakeLists.txt`: the `astroray` pybind target now gets
  `-DASTRORAY_OPENMP_ENABLED` compiled in whenever `ASTRORAY_DISABLE_OPENMP`
  is not set.
- `module/blender_module.cpp`: `__features__["openmp"]` surfaces that flag to
  Python.
- `blender_addon/__init__.py`: `_check_openmp_disabled()`, called from
  `configure_backend()` at every point CPU mode is actually selected
  (explicit `device_mode='cpu'`, or an auto/gpu→cpu fallback) — **not** from
  `register()`, which would also block legitimate GPU-only use of the same
  ad-hoc build (this over-broad version regressed
  `test_blender_parity_matrix_generation`, a pre-existing GPU-mode test, and
  was corrected before merge). Raises a loud `RuntimeError` naming the fix
  (`build_blender_addon.py`) before any render is attempted, making the guard
  structural rather than tribal knowledge, per the acceptance gate.

**Acceptance gate: met.** 32×32 and 256×256 CPU addon renders complete in
under a second on the deployed build; GPU addon path and direct-bindings CPU
path unchanged (full regression suite green apart from 7 pre-existing,
unrelated failures — see PR for detail); the OpenMP guard is now structural
(compile-time flag → runtime feature dict → addon refusal) and covers both
MinGW and MSVC.
