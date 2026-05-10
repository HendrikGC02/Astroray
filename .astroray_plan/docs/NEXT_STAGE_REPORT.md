# Astroray Next Stage Report

**Date:** 2026-05-10 (post-pkg68/69/71 round)
**Prepared by:** Claude (Anthropic Code, Sonnet 4.5 in Max 5x)
**Scope:** post-pkg68 + pkg69 + pkg71-spec round; next deployable
parallel set focused on Pillar-5 stability.

> Strategic gate (unchanged): Pillar 4 (astrophysics) packages on
> hold. Focus is locking in Blender integration + measured CPU/GPU
> parity + parity with how other production engines integrate into
> Blender. Strategy in [`ROADMAP.md`](ROADMAP.md), status in
> [`STATUS.md`](STATUS.md).

---

## 1. Current state (one screen)

**Done since the previous report (2026-05-10 morning):**

- pkg68 OIDN architectural fix landed (PR #200) — member-cached
  device, lazy-init, CUDA-first with CPU fallback, FetchContent
  bumped to OIDN 2.4.1. CUDA hardware verification still pending.
- pkg69 Albedo pass for compositor (PR #201) — Codex. RGB Albedo +
  Normal guide passes registered behind `use_pass_denoising_data`,
  Cycles-compatible.
- pkg71 spec landed (PR #199) — Cycles parity benchmark framework
  fully spec'd. Cornell + Classroom + Monster (CC-0 / ships) and
  Junkshop + BMW27 (CC-BY, user-downloaded with auto-attribution),
  Victor (CC-BY-NC) excluded with defence-in-depth. Implementation
  is the next Codex-friendly pickup.

**In flight / blocked:**

- pkg54c CUDA verification — last status: visible-band SSIM 0.9902
  (gate 0.999). FMA experiment + diagnostic-binding plan was given
  to the verifier session; outcome unknown to this report. If the
  diagnostic landed bad, the package may need a small follow-up
  (FMA-strict mode or texture-object port).
- pkg68 CUDA verification — pending. Same shape as pkg54a/b
  verification: build on the RTX, run the new persistence tests,
  record `[OIDN] Using CUDA device` first-line + 100-frame timing
  against pre-pkg68 baseline.

**Open Pillar 5 (this is the queue):**

| Pkg | Title | Effort | Status |
|---|---|---|---|
| **pkg70** | OptiX denoiser backend | 3–5 days | Spec landing this PR |
| **pkg57** | Native Astroray shader nodes | 1.5 weeks | Research signed off (#188), spec concrete, ready to implement |
| **pkg71** impl | Cycles parity benchmark framework | 1 week | Spec landed (#199), ready to implement |
| **pkg56** | Incremental scene sync (depsgraph diff) | 5–7 weeks | Spec + research signed off (#192), staged in 3 phases |
| **pkg64** | Spectral caustics (SMS + spectral MNEE) | 3–4 weeks | Research signed off, deferred behind integration work |

---

## 2. Recommended next deployable set

Three Claude tech sessions + one Codex session, all parallel-safe:

| # | Agent | Worktree / location | Package | Effort |
|---|---|---|---|---|
| 1 | Claude tech | `pkg70-optix` (new) | pkg70 OptiX denoiser | 3–5 days |
| 2 | Claude tech | `pkg57-shader-nodes` (new) | pkg57 native shader nodes | 1.5 weeks |
| 3 | Codex | main directory | pkg71 implementation | 1 week |
| 4 | Codex or Claude | (CUDA hardware) | pkg68 verification + pkg54c verification follow-through | ½ day |

Two more sessions could run in parallel as research/spec polish if
the user wants more breadth, but with the previous research rounds,
the Pillar 5 spec backlog is essentially clear. The active work is
implementation.

---

## 3. Drop-in prompts per agent

### 3.1 Claude tech (worktree `pkg70-optix`) — pkg70 OptiX denoiser

```
You are Claude Code in worktree .claude/worktrees/pkg70-optix,
branched from current main. Implement pkg70 end to end.

Read first:
  - .astroray_plan/packages/pkg70-optix-denoiser-backend.md (the spec)
  - plugins/passes/oidn_denoiser.cpp (the post-pkg68 implementation
    you mirror — same shape: member-cached state, lazy init, CUDA
    detection, buffer caching)
  - src/gpu/cuda_renderer.cu (where the CUDA context lives — your
    OptiX denoiser shares it, no separate context needed)
  - tests/test_oidn_denoiser_persistence.py (mirror its test pattern)

Implementation outline (subject to the spec):
  1. cmake/FindOptiX.cmake — adapt from NVIDIA OptiX SDK's
     SDK/CMake/FindOptiX.cmake or use OPTIX_INSTALL_DIR env var.
     Default install path on Windows:
     C:\ProgramData\NVIDIA Corporation\OptiX SDK 8.1.0\
  2. CMakeLists.txt — add ASTRORAY_ENABLE_OPTIX flag (default AUTO,
     enabled when SDK found). Define ASTRORAY_OPTIX_ENABLED for
     conditional compilation.
  3. plugins/passes/optix_denoiser.cpp — OptiXDenoiser class with:
     - Persistent OptixDeviceContext + OptixDenoiser handle as members
     - Lazy init on first execute()
     - Model selection: HDR if no guides, AOV if albedo+normal present
     - State + scratch device buffers cached, reallocated only on
       dimension change
     - "[OptiX] Using <device>" log line at first invocation
  4. module/blender_module.cpp — add gpu_optix_available() Python
     query so the addon can detect runtime support.
  5. blender_addon/__init__.py — backend-selection logic: when both
     OIDN and OptiX are available, default to OptiX in viewport
     mode. UI dropdown for user override.
  6. tests/test_optix_denoiser.py — skip-if-OptiX-unavailable test
     mirroring tests/test_oidn_denoiser_persistence.py shape.

OptiX API references (open these, do not guess):
  - https://raytracing-docs.nvidia.com/optix8/guide/index.html#ai_denoiser
  - https://raytracing-docs.nvidia.com/optix8/api/optix__host_8h.html

Cycles reference (Apache-2.0, mirrorable): intern/cycles/device/optix/
  in the Blender mono-repo. OptiXDevice::denoise() and denoise_buffer()
  for the per-frame invocation shape.

Constraints:
  - CLAUDE.md sections 2, 3, 6.
  - DO NOT bundle OptiX SDK headers (NVIDIA license forbids
    redistribution) — find_package only.
  - DO NOT enable temporal mode (requires motion vectors —
    out of scope per pkg70 design decision #4).
  - DO NOT touch path_trace_kernel.cu or multiwavelength_kernel.cu.
  - You will likely not have OptiX SDK locally; the test will skip
    cleanly. Mark in PR body: "OptiX SDK + CUDA hardware
    verification pending."

When done:
  - pkg70 spec status -> "implemented (pending verification)".
  - STATUS.md entry for pkg70.
  - Commit on this branch:
      feat(pkg70): OptiX AI denoiser backend (HDR/AOV, persistent
      state, fallback to OIDN)
  - PR. DO NOT merge.
```

### 3.2 Claude tech (worktree `pkg57-shader-nodes`) — pkg57 native shader nodes

```
You are Claude Code in worktree .claude/worktrees/pkg57-shader-nodes,
branched from current main. This is the biggest single Blender-
integration delivery in the queue. Implement pkg57 end to end.

Read first (in order):
  - .astroray_plan/packages/pkg57-native-shader-nodes.md (the spec —
    rewritten in PR #188 to be implementation-concrete, with file-
    by-file plan)
  - .astroray_plan/docs/blender-shader-nodes-research.md (the
    research note that backs the spec — has the BlendLuxCore /
    Cycles / Octane / PBRT-v4 reference reading already done)
  - blender_addon/__init__.py — search for convert_node_material
    and _principled_shader_spec to understand the existing
    Cycles auto-conversion path you must preserve

Per the research recommendation (PR #188), use:
  - bpy.types.ShaderNode subclasses for all 5 Astroray nodes
    (NOT ShaderNodeCustomGroup — orphan-data-block risk)
  - PointerProperty on bpy.types.Material for engine-switch survival
    (mirrors Cycles' properties.py Apache-2.0 pattern)
  - AstroraySellmeierSocket(bpy.types.NodeSocket) custom socket
    for Sellmeier-coefficient typed inputs
  - Conversion path: extend existing convert_node_material with a
    one-line AstrorayOutputNode pre-check; dispatch to new
    _astroray_*_spec() helpers, same pattern as
    _principled_shader_spec()

Five nodes per pkg57 spec:
  1. AstrorayOutputNode (companion to OUTPUT_MATERIAL)
  2. AstroraySpectralProfile (picks from
     astroray.spectral_profile_names())
  3. AstroraySellmeierGlass (B/C coeff triples, dispersive IOR)
  4. AstrorayIRUVResponse (extends base BSDF with IR/UV reflectance band)
  5. AstrorayNRCCacheHint (per-material flag for the neural cache
     integrator)

Acceptance gates (per spec):
  - All 5 nodes appear in Add menu when engine == ASTRORAY,
    absent otherwise.
  - Existing Cycles BsdfPrincipled scenes render identically
    (within Monte Carlo noise) before and after this package.
  - AstrorayOutputNode + SellmeierGlass produces dispersive
    refraction in a prism scene that the existing flat-IOR
    Cycles converter cannot.
  - tests/test_blender_native_nodes.py covers node registration,
    Cycles-fallback path, Astroray-takes-precedence path.
  - mat.astroray PropertyGroup registers without error in a
    blend file with no Astroray materials.

Constraints:
  - CLAUDE.md sections 2, 3, 6.
  - License hygiene per the research note: BlendLuxCore is GPL-3.0,
    NO code mirroring — patterns referenced architecturally only.
    Cycles is Apache-2.0, mirroring permitted with citation.
  - Cite Cycles file:line for any pattern mirrored in code comments.
  - Multi-session work — Max 5x makes this feasible in one focused
    push. Estimated 1.5 weeks of focused effort.

When done:
  - pkg57 spec status -> done.
  - STATUS.md entry: pkg57 done.
  - Commit on this branch (squash later as needed):
      feat(pkg57): native Astroray shader nodes (Spectral Profile,
      Sellmeier Glass, IR/UV Response, NRC Hint, Output) with
      engine-switch survival and Cycles-precedence fallback
  - PR. DO NOT merge.
```

### 3.3 Codex — pkg71 Cycles parity benchmark framework

```
Implement pkg71 end to end against current main.

Read first:
  - .astroray_plan/packages/pkg71-cycles-parity-benchmark.md (the
    spec — fully concrete, recommends the scene set, license policy,
    and CSV layout)

Required to implement (per the spec):
  1. benchmarks/cycles-parity/ directory structure:
     - scenes/ — Cornell box (ships in repo, MIT)
     - scripts/fetch_scenes.py — downloads CC-0 (Classroom,
       Monster) into a gitignored cache dir; for CC-BY (Junkshop,
       BMW27) downloads with auto-generated attribution file.
       VICTOR IS EXPLICITLY EXCLUDED — defence in depth: assert
       on URL match in the fetch script.
  2. scripts/run_parity.py — runs each (scene, engine) tuple
     three times via subprocess isolation, takes the median time,
     measures peak memory (psutil resident set), computes SSIM
     vs Cycles-CPU EXR reference at canonical sample count.
     Output: benchmarks/cycles-parity/<date>-<machine>.csv
     with columns: scene,engine,samples,time_ms,peak_mem_mb,
     ssim_to_cycles
  3. scripts/summarize_parity.py — reads the CSV, produces a
     Markdown table for inclusion in PR comments / CHANGELOG.
  4. .github/workflows/cycles-parity.yml — weekly cron + on-demand
     trigger via PR comment; runs on a self-hosted runner with
     CUDA + Cycles 4.x installed.
  5. Reference rendering: Cycles-CPU EXR at canonical sample count
     (NOT opendata.blender.org PNGs — quantisation eats the gate).
  6. SSIM gate: ≥ 0.95 between Astroray and Cycles outputs per
     scene. Perf is recorded but not gated yet (perf gates wait
     for pkg55/pkg56).

Reference (Apache-2.0, mirrorable):
  - Cycles intern/cycles/test/integration/ — the harness pattern.
  - Blender benchmark code:
    https://projects.blender.org/blender/blender-benchmark
  - LuxCoreRender benchmark suite (Apache-2.0):
    https://github.com/LuxCoreRender/LuxCore-Benchmark

Constraints:
  - CLAUDE.md sections 2, 3, 6.
  - VICTOR (CC-BY-NC) is excluded with defence in depth — assert in
    fetch_scenes.py that the URL is not in the disallowed list, and
    that the disallowed list cannot be empty (a sentinel test value
    must always be in it).
  - Do not commit any non-MIT scene data to the repo.
  - Codex-paste-ready: spec is concrete enough that no more research
    is needed.

When done:
  - First baseline run: produce one CSV from this implementer's
    machine (or skip with "pending hardware" if Cycles unavailable).
  - pkg71 spec status -> implemented.
  - STATUS.md entry: pkg71 implementation done; first baseline CSV
    pending CUDA hardware.
  - Commit on a fresh branch:
      feat(pkg71): Cycles parity benchmark framework
      (Cornell+Classroom+Monster+Junkshop+BMW27, 4-engine matrix)
  - PR. DO NOT merge.
```

### 3.4 Verification session — pkg68 + pkg54c CUDA gates

```
You are a CUDA verification session on the user's RTX 5070 Ti
Windows workstation. Two packages need verification.

Step 1: pull latest main.
  git fetch origin && git checkout main && git pull --ff-only

Step 2: pkg68 verification.
  scripts\build\build_cuda.bat
  python scripts\dev\run_tests.py --build-dir build_cuda --
    tests/test_oidn_denoiser_persistence.py
    tests/test_oidn_denoiser.py
    tests/test_aov_passes.py
  -v --tb=short

  Report:
  - First "[OIDN] Using <device>" line in the test output. Should
    be "Using CUDA device" on this machine.
  - All 12+1 tests green.
  - If you have time: time 100 viewport frames at 256x256 with
    OIDN enabled vs the same on origin/main^ (pre-pkg68). Compute
    per-frame mean. Acceptance was "≥2× faster"; record actual
    numbers.

Step 3: pkg54c verification follow-through (if not already done).
  Check the prior FMA experiment results. If pkg54c is still red
  per the diagnostic plan from the previous round, follow steps
  1-3 of that plan (FMA experiment, then diagnostic-binding eval
  if FMA wasn't the cause).

Step 4: report verbatim. Do NOT promote any package status without
  green gates. If pkg68 is green, promote it to "done" in the spec
  + STATUS.md and commit on a verify branch:
    verify(pkg68): CUDA gates green; OIDN-CUDA timing measured

Constraints:
  - Do NOT modify implementation code.
  - Do NOT relax any gate.
  - If close-but-not-quite, report and ask.
```

---

## 4. Coordination

**File-touching map** (zero hard collisions):

| Session | Files |
|---|---|
| pkg70 OptiX | new `cmake/FindOptiX.cmake`, new `plugins/passes/optix_denoiser.cpp`, `CMakeLists.txt` (build flag), `module/blender_module.cpp` (gpu_optix_available binding), `blender_addon/__init__.py` (backend selection), new test, pkg70 spec, STATUS.md |
| pkg57 shader nodes | `blender_addon/` heavily, `module/blender_module.cpp` (new bindings), Astroray-side material conversion, pkg57 spec, STATUS.md |
| pkg71 implementation | new `benchmarks/cycles-parity/`, new `scripts/run_parity.py` + `summarize_parity.py` + `fetch_scenes.py`, new `.github/workflows/cycles-parity.yml`, pkg71 spec, STATUS.md |
| Verification | only diagnostic + verify-branch commits |

Three sessions touch `module/blender_module.cpp` (pkg70 + pkg57) and
`blender_addon/__init__.py` (pkg70 + pkg57). pkg70's additions are
small (one binding + a backend-selection block); pkg57's are
extensive. Recommend pkg70 lands first to clear the blender_module
binding additions, then pkg57 rebases — that's a smaller delta than
the reverse.

Recommended merge order: pkg71 (benchmark framework, mostly new
files, lowest collision risk) → pkg70 OptiX → pkg57 shader nodes.

---

## 5. Practical conclusion

After this round lands:

- pkg70 → both denoiser backends shipped; user picks OIDN or OptiX.
- pkg57 → biggest Blender-integration package done; Astroray nodes
  in the shader editor; engine-switch survival.
- pkg71 → measured Cycles parity numbers in CI; the "matches Cycles"
  claim has data behind it.
- pkg68 verification → CUDA-OIDN performance numbers recorded.

Then the open Pillar 5 set is just pkg56 (incremental scene sync,
multi-week) and pkg64 (spectral caustics flagship). Both are
multi-week; do them sequentially or in parallel based on capacity.

Only after pkg56 + pkg64 land do we revisit Pillar 4 — at which
point pkg41 (Kerr validation, follows pkg40) and the Codex-paste-
ready specs for pkg42-49 are waiting.

Bump this report when pkg57 lands or when pkg56 starts.
