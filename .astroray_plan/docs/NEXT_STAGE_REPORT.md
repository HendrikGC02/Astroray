# Astroray Next Stage Report

**Date:** 2026-05-10 (revised)
**Prepared by:** Claude (Anthropic Code, Sonnet 4.5 in Max 5x)
**Scope:** post pkg54c verification — handoff playbook of which agent gets
which package next, with the exact prompt to drop into each.

> Strategic gate: Pillar 4 (astrophysics) packages are explicitly **on
> hold**. The current focus is locking in Blender-integration stability,
> measured CPU/GPU parity, and parity with how other production engines
> (Cycles, Octane, V-Ray, LuxCore) integrate into Blender. pkg40 (Kerr
> metric) landed as a one-off because the spec was already Codex-paste-
> ready; pkg41 and the rest of pkg42-51 wait until the Pillar 5 queue
> below clears.
>
> This file is the **action queue**, not the strategy doc. Strategy in
> [`ROADMAP.md`](ROADMAP.md); status in [`STATUS.md`](STATUS.md).

---

## 1. Current state (one screen)

- **Pillars 1, 2, 3** complete and validated.
- **Pillar 4** parked. Only pkg40 (Kerr + Schwarzschild metric plugins)
  landed (PR #195, BPT 1972 analytic gates green). pkg41-51 wait.
- **Pillar 5 (Blender / parity / perf)** is the active queue.
  - Done: pkg52, pkg53, pkg54, pkg54a, pkg54b, pkg54d, pkg58, pkg59,
    pkg60, pkg61, pkg62, pkg65, pkg66.
  - Pending verification: pkg54c (PR #194; CUDA hardware verification
    in progress — the visible-band SSIM gate at 0.999 is real-fixing,
    not yet green).
  - In flight, blocked by CI: pkg63 (PR #191; the new 9-arg
    `load_environment_map` signature breaks an old mock-asserting test).
  - Open and prioritised below: pkg57, pkg63 fix, pkg64, pkg68, pkg69,
    pkg70, pkg56, plus a new pkg71 (Cycles parity benchmark framework).

---

## 2. Priority lens (this is the strategic shift)

The user direction: **lock in Blender integration + performance +
GPU/CPU parity + parity with how other Blender engines work, BEFORE
returning to astrophysics**. That ranks the open queue as follows.

### Tier 1 — Blender integration parity (top priority)

| Pkg | Title | Effort | Owner |
|---|---|---|---|
| **pkg63 fix** | Update test for new `load_environment_map` signature | ~1 h | Claude (in existing `pkg63-hdri` worktree) |
| **pkg69** | Albedo pass for Blender compositor denoise node | ~½ day | Codex |
| **pkg57** | Native Astroray shader nodes (post-research-note implementation) | 1.5 weeks | Claude |

These three close the visible "feels like a Cycles workflow" gap.

### Tier 2 — Performance + correctness

| Pkg | Title | Effort | Owner |
|---|---|---|---|
| **pkg68** | OIDN architectural fix (lazy persistent device, CUDA backend) | 1–2 days | Claude |
| **pkg70** | OptiX denoiser backend | 3–5 days | Claude (after pkg68 establishes the pattern) |
| **pkg56** | Incremental scene sync (depsgraph diff, BVH refit) | 5–7 weeks (3 phases) | Claude |

### Tier 3 — Measured parity (new)

| Pkg | Title | Effort | Owner |
|---|---|---|---|
| **pkg71** | Cycles parity benchmark framework | 1 week | Claude (spec writing now, implementation when prioritised) |

Without pkg71, every "performance is fine" or "we match Cycles" claim
is hand-wavy. This package codifies a deterministic CPU/GPU vs Cycles
benchmark suite using Blender Foundation demo scenes (Cycles
opendata.blender.org reference scenes), tracks frame-time + SSIM
deltas in CI, and produces the actual numbers a journal-paper or
release-blog claim can cite.

### Tier 4 — Visual fidelity flagship (deferred until the above settles)

| Pkg | Title | Effort | Owner |
|---|---|---|---|
| **pkg64** | Spectral caustics (SMS + spectral MNEE) | 3–4 weeks | Claude |

Marquee deliverable for the eventual paper, but explicitly deferred
behind the integration/perf/parity work above per the strategic gate.

---

## 3. Recommended order this week + next

Assuming pkg54c verification closes (gate green or scoped follow-up
filed):

**This week, in parallel:**

1. **pkg63 fix** (~1 h) — unblocks PR #191. Existing `pkg63-hdri`
   worktree.
2. **pkg69 Albedo pass** (~½ day) — Codex. Closes Blender compositor
   parity.
3. **pkg68 OIDN fix** (1–2 days) — Claude. Real defect, closes a
   per-frame perf hole.
4. **pkg71 spec writing** (~½ day) — Claude. Codifies what we mean
   by "Cycles parity" so the next round of work has a measurement
   gate.

**Next week:**

5. **pkg70 OptiX denoiser** (3–5 days) — Claude. Layer the perf-win
   backend on top of pkg68's fixed OIDN plumbing.
6. **pkg57 Native shader nodes** (1.5 weeks) — Claude. Biggest
   single-package Blender-integration delivery. Spec is already
   concrete from PR #188 research.

**The week after:**

7. **pkg71 implementation** — once it's spec'd and we can run the
   first benchmark run for pre-pkg56/pkg70 numbers.
8. **pkg56 incremental scene sync** — multi-week, Phase A first.
9. **pkg64 caustics** — flagship visual fidelity, only after the
   above stabilises.

---

## 4. Drop-in prompts per agent

### 4.1 Codex — pkg69 Albedo pass for Blender compositor

```
You are Codex working in the main Astroray directory on commit
9c53b62 or later (post-pkg54c-verification main). Implement pkg69
end to end.

Read first:
  - .astroray_plan/packages/pkg69-albedo-pass-blender-compositor.md
    (the spec — fully concrete)
  - blender_addon/__init__.py (search for _DATA_PASS_SPECS,
    _PASS_SPECS, write_pixels — these are the touch points)
  - module/blender_module.cpp (search for getColorBuffer /
    getNormalBuffer for the binding pattern to mirror)

Implementation:
  1. Add ("Albedo", 3, "RGB", "use_pass_denoising_data") to
     _DATA_PASS_SPECS in blender_addon/__init__.py at line ~556.
  2. If no Python accessor for the albedo Framebuffer buffer
     exists in module/blender_module.cpp, add getAlbedoBuffer()
     mirroring the existing getColorBuffer/getNormalBuffer pattern.
     Bind as Renderer.get_albedo_buffer().
  3. In write_pixels (blender_addon/__init__.py:2706), emit the
     albedo buffer to the new Albedo pass when the user has
     enabled use_pass_denoising_data on the view layer.
  4. Add tests/test_blender_compositor_denoise_passes.py — pure
     Python, mirrors the existing test_blender_view_layers.py
     pattern, asserts that with use_pass_denoising_data=True
     the registered passes include "Albedo" and "Normal" with
     channel counts (3, 3).

Verify:
  - python scripts\dev\run_tests.py --
      tests/test_blender_compositor_denoise_passes.py
      tests/test_blender_view_layers.py
    -v --tb=short
  - Both green.

When done:
  - pkg69 spec status -> done.
  - STATUS.md: pkg69 entry done in the Cycles-parity table.
  - Commit on a fresh branch:
      feat(pkg69): Albedo pass for Blender compositor denoise node
  - PR against main with the test results in the body. DO NOT merge.

Constraints (CLAUDE.md sections 2, 3, 6):
  - Stay narrow: only blender_addon/__init__.py, possibly
    module/blender_module.cpp + the new test.
  - Cite Cycles' sync.cpp + line range for the
    `DENOISING_PASS_*` pattern in a code comment per CLAUDE.md §6
    (Apache-2.0, mirroring permitted).
  - No OIDN or OptiX changes (those are pkg68/70).
```

### 4.2 Claude Code (worktree `pkg68-oidn`) — OIDN architectural fix

```
You are Claude Code in the worktree .claude/worktrees/pkg68-oidn,
branched from current main (commit 9c53b62 or later, post-pkg54c
verification). Implement pkg68 end to end.

Read first:
  - .astroray_plan/packages/pkg68-oidn-architectural-fix.md (the spec)
  - plugins/passes/oidn_denoiser.cpp (the file to surgically refactor)
  - .astroray_plan/docs/oidn-fact-finding-report-2026-05-10.md if
    present (the report that surfaced the issues)
  - include/raytracer.h — search for "albedo" and "normal" buffer
    population inside the Renderer's render loop. Confirm the
    Framebuffer's "albedo" and "normal" buffers are populated
    UNCONDITIONALLY by the integrator, not only when the user
    explicitly registers an albedo_aov / normal_aov pass. If they
    are conditional, that is the silent-bug path you fix as part
    of this package (the existing OIDN guard `fb.hasBuffer(...)`
    silently degrades to color-only denoising in that case).

Implementation outline (read the spec for full detail):
  1. Move oidn::DeviceRef and oidn::FilterRef from local variables
     in execute() to class members in OIDNDenoiser.
  2. Lazy-init the device on first execute() call. Try
     oidn::DeviceType::CUDA first; if device.getError() is
     non-None after commit(), fall back to oidn::DeviceType::CPU.
     Log which was selected (printf "[OIDN] Using %s device\n").
  3. Cache buffer-binding state (last bound pointers + dimensions);
     re-bind via setImage() + commit() only when those change.
  4. If the integrator audit in step 1 found conditional
     population of "albedo"/"normal", fix it to be unconditional.
  5. Bump CMakeLists.txt FetchContent fallback URL from
     oidn-2.3.3.x64.windows.zip to oidn-2.4.1.x64.windows.zip.
  6. Add tests/test_oidn_denoiser_persistence.py with three
     tests per the spec (device-init runs once across N frames;
     CUDA-capable build reports CUDA device; albedo guides are
     fed even without explicit AOV pass).

Reference (Apache-2.0, mirrorable patterns):
  - Cycles intern/cycles/integrator/denoiser_oidn_*.cpp — caches
    device + filter as members of the denoiser class. Mirror the
    create_device() helper for the CUDA-then-CPU fallback shape.

OIDN API references (open these, do not guess):
  - https://www.openimagedenoise.org/documentation.html
  - https://github.com/RenderKit/oidn/blob/master/include/OpenImageDenoise/oidn.hpp

Constraints:
  - Do NOT add OptiX (pkg70). Do NOT add temporal mode (out of
    scope per spec design decision #4 — OIDN does not have a
    color1 previous-frame input).
  - You will likely not have CUDA at this implementation site;
    that is OK. The CUDA-path SSIM/timing gates skip cleanly,
    and the verifier session runs them on hardware. Mark in the
    PR body: "CUDA verification pending."

Verify:
  - cmake build standard (no CUDA needed).
  - python -m pytest tests/test_oidn_denoiser_persistence.py
      tests/test_oidn_denoiser.py tests/test_aov_passes.py
    -v --tb=short
  - All green.

When done:
  - pkg68 spec status -> "implemented (pending CUDA verification)".
  - STATUS.md updated.
  - Commit on this branch:
      feat(pkg68): OIDN persistent device + CUDA backend selection
  - PR. DO NOT merge.
```

### 4.3 Claude Code (existing `pkg63-hdri` worktree) — fix PR #191

```
You are Claude Code returning to the existing worktree
.claude/worktrees/pkg63-hdri (branch claude/amazing-ride-2f0790).
PR #191 is open but red — CI fails on
tests/test_blender_view_layers.py::
  test_setup_world_loads_hdri_with_blender_x_rotation_correction
  AssertionError: assert ('//env.hdr', 0.25, 1.0, ...)
                  == ('//env.hdr', 1.5, 0.25, True)

The test asserts the OLD 4-arg load_environment_map signature
(path, strength, rotation, blender_x_rotation_bool). pkg63
changed the signature to 9 args (path, strength, rx, ry, rz,
tr, tg, tb, blender_convention).

Decide which of the following is the correct fix and apply
exactly that fix:

  (a) The addon-side setup_world should still call
      load_environment_map with the legacy 4-arg shape when
      no XYZ rotation and no color tint are configured (i.e.,
      the user's Blender world is just a plain HDRI with no
      Mapping rotation). In that case the failing test is
      asserting correct backward-compat behaviour and the
      bug is in the addon: it always emits the 9-arg form
      now. Fix the addon to detect the no-mapping-no-tint
      case and use the 4-arg path.

  (b) The legacy 4-arg call shape is intentionally retired
      and the addon always emits the 9-arg form. In that
      case the failing test is testing for old behaviour
      and needs updating to assert the new 9-arg tuple.

Read these to decide:
  - tests/test_blender_view_layers.py around the failing test
    (line ~206) — what is it really verifying?
  - blender_addon/__init__.py setup_world — what does the
    new code path emit?
  - module/blender_module.cpp load_environment_map signature —
    are both shapes accepted, or only the 9-arg form?

Recommendation: option (b) is almost certainly correct. The
test exists to verify the addon correctly forwards Blender's
"X-axis rotation correction" toggle. Under pkg63, that toggle
is now baked into the 3x3 rotation matrix on the C++ side, so
the test's assertion shape needs to update to match the new
signature, not the old one. Verify by reading the test's
intent comment if present.

If (b): update the test's expected tuple to match the new
9-arg form. The test still fundamentally verifies that the
blender_x_convention input is correctly routed; just to the
new signature.

If (a): fix the addon. Smaller diff but more test coverage
needed to confirm the legacy path still works.

Verify:
  - python -m pytest tests/test_blender_view_layers.py -v
  - python -m pytest tests/test_world_hdri_parity.py -v
  - Existing GPU-skip behaviour still in place.

When green:
  - Commit to the same branch claude/amazing-ride-2f0790:
      fix(pkg63): update test_setup_world_loads_hdri to
      match new 9-arg load_environment_map signature
  - Push. PR #191 CI re-runs automatically.
  - DO NOT merge — owner does that once green.
```

### 4.4 Claude Code (worktree `research-pkg71`) — write pkg71 Cycles parity benchmark spec

```
You are Claude Code in the worktree
.claude/worktrees/research-pkg71, branched from current main.
RESEARCH + SPEC session — no implementation code. One deliverable.

Deliverable: create
.astroray_plan/packages/pkg71-cycles-parity-benchmark.md
following the format of pkg54-gpu-multiwavelength-integrator.md.

Why this matters: every claim we make about "Astroray matches
Cycles" or "Astroray is competitive on a single RTX 5070 Ti"
is currently anecdotal. Without a reproducible benchmark we
cannot publish parity numbers, cannot regression-test perf
in CI, and cannot honestly tune the wavefront refactor (pkg55)
when it lands. pkg71 fixes that.

Required reading (use WebFetch — do NOT clone):

Blender Foundation reference scenes:
  - https://www.blender.org/download/demo-files/ — confirm which
    demo files are CC0 (free to redistribute) vs CC-BY-NC
    (cannot ship in our repo, can be downloaded by user).
  - https://opendata.blender.org/ — Cycles' canonical perf
    benchmark. Their scene set: BMW (Mike Pan, CC-BY), Classroom
    (Christophe Seux, CC-0), Junkshop (Alex Treviño, CC-BY),
    Pabellon Barcelona (Claudio Andres, CC-BY), Victor (Juan
    Pablo Bouza, CC-BY-NC).
  - Blender benchmark code: https://projects.blender.org/blender/blender-benchmark
    License: Apache-2.0. Read for the harness pattern.

Cycles' performance test infrastructure:
  - intern/cycles/test/integration/ in the Blender mono-repo.
    https://projects.blender.org/blender/blender/src/branch/main/intern/cycles/test/integration
    License: Apache-2.0, mirrorable.

LuxCoreRender's benchmark suite (open-source third-party
engine — closest precedent):
  - https://github.com/LuxCoreRender/LuxCore-Benchmark
    Read for the third-party-engine-benchmark pattern.
    License: Apache-2.0.

The pkg71 spec should answer:

  1. Scene set — recommend 3-5 Blender Foundation demo scenes
     based on license compatibility. Cornell box (we already
     have one), BMW (CC-BY, attribution OK), Classroom (CC-0).
     Each scene tests a different stress: Cornell = simple
     light transport; BMW = many materials + glossy paint;
     Classroom = large geometry + complex lighting.
  2. Engine matrix — Cycles CPU, Cycles CUDA, Astroray CPU,
     Astroray GPU. Skip Cycles OptiX for now (different
     denoiser path muddles the comparison).
  3. Metrics per scene per engine:
       - Time to first sample (warm-up cost)
       - Time to N samples (where N matches Cycles benchmark
         reference, e.g., 1024 spp for BMW)
       - Peak memory (resident set)
       - Output SSIM vs Cycles' published reference image
         from opendata.blender.org
       - For viewport: time per progressive accumulation step
  4. Output format — a CSV
     `benchmarks/cycles-parity/<date>-<machine>.csv`:
       scene,engine,samples,time_ms,peak_mem_mb,ssim_to_cycles
     Plus a Markdown summary auto-generated from the CSV.
  5. CI integration — does this run in CI or only on demand?
     Recommend: weekly on a self-hosted runner + on-demand
     via PR comment trigger. Numbers stored in
     `benchmarks/cycles-parity/` with date + git-SHA tags.
  6. Acceptance — first run of the framework produces a
     baseline CSV; SSIM gates of >= 0.95 between Astroray
     and Cycles output on each scene; frame-time results
     simply recorded (no perf-regression gates this round —
     that comes after pkg55/pkg56 land).
  7. Non-goals — no benchmark of Cycles features Astroray
     does not support (volumetrics, hair, etc.); no
     animation/motion-blur benchmarking; no GPU-vendor
     comparison (NVIDIA only this round).
  8. Reference Implementations table per the pkg40 / pkg54
     pattern: licenses, commit SHAs, what we mirror, what
     we do not.

Front-matter:
  - Pillar: 5
  - Track: A (or Codex once spec is concrete enough)
  - Status: open
  - Estimated effort: 1 week (~25 h, multi-session)
  - Depends on: nothing hard (could run today); pkg63
    landing makes the HDRI-using scenes more meaningful;
    pkg54c landing makes the GPU spectral output stable
    enough to compare.

Length: spec should be 6-8 pages. Include the scene-license
audit explicitly.

When done:
  - Commit on this branch:
      docs(pkg71): Cycles parity benchmark framework spec
  - PR against main. Body summarises the recommendation in
    5 lines and lists the recommended scene set.
    DO NOT merge.

Constraints:
  - CLAUDE.md sections 2, 3, 6 apply.
  - No source code changes (this is spec-writing).
  - Cite Cycles + LuxCore + Blender benchmark commit SHAs.
  - Be explicit about which demo scenes can be checked into
    our repo (CC-0 only) vs which the user must download
    separately (CC-BY can be redistributed with attribution
    but our repo would balloon; CC-BY-NC cannot be shipped
    at all).
```

---

## 5. Coordination

**File-touching map** (zero hard collisions):

| Session | Files |
|---|---|
| Codex pkg69 | `blender_addon/__init__.py`, `module/blender_module.cpp` (small binding), `tests/test_blender_compositor_denoise_passes.py` (new), pkg69 spec, STATUS.md |
| Claude pkg68 | `plugins/passes/oidn_denoiser.cpp`, possibly `include/raytracer.h` (Framebuffer-population audit), `CMakeLists.txt` (FetchContent URL bump), `tests/test_oidn_denoiser_persistence.py` (new), pkg68 spec, STATUS.md |
| Claude pkg63-fix | `tests/test_blender_view_layers.py` (test update only), possibly `blender_addon/__init__.py` (option (a) only) |
| Claude pkg71 spec | `.astroray_plan/packages/pkg71-cycles-parity-benchmark.md` (new) |

Three sessions touch STATUS.md (pkg68, pkg69, pkg63-fix). Trivial
three-way merge — separate paragraphs.

Two sessions may both touch `blender_addon/__init__.py` (pkg69 +
pkg63-fix option (a)). pkg69 modifies the `_DATA_PASS_SPECS` table
and `write_pixels`; pkg63-fix would only modify `setup_world` if
option (a) is taken (option (b) is more likely and would not
touch the addon). Trivial merge if both happen.

Recommended merge order: pkg63-fix first (smallest), then pkg71
spec (docs only), then Codex pkg69, then Claude pkg68.

---

## 6. Research notes the project still needs (Pillar-5-only)

Most Pillar 5 research is now done. Remaining unblockers:

| File | Unblocks | Status |
|---|---|---|
| `blender-shader-nodes-research.md` | pkg57 | **Done** (PR #188) |
| `blender-depsgraph-sync-research.md` | pkg56 | **Done** (PR #192) |
| `wavefront-gpu-research.md` | pkg55 | **Done** (PR #189) |
| `cycles-world-parity-research.md` | pkg63 | **Done** (PR #191) |
| (pkg71 spec doubles as its own research note) | pkg71 | Will land with prompt 4.4 above |

Pillar 4 research (Kerr / metric-aware / accretion-emission /
Pillar 4 I/O) all landed during the pre-strategic-shift rounds;
they sit waiting for when astrophysics resumes. **Do not start
new astrophysics research sessions in this round.**

---

## 7. Track assignments going forward

| Track | Agent | Now owns |
|---|---|---|
| A. Core quality | Claude Code | pkg54c verification, pkg68, pkg57, pkg56, pkg64, pkg70, pkg71 implementation. Per-package research noted in §6. |
| B. Feature breadth | (currently inactive) | — |
| C. Experiments | (currently inactive) | — |
| D. Grind work | (currently inactive) | — |
| E. Coordination/review | Codex | pkg69 (and pkg47/pkg40-pattern Pillar 4 packages when astrophysics resumes). PR review. |

---

## 8. Verification posture (carry-forward)

Same lessons from the pkg54a/b/c verification cycles:

1. Implementation session writes code + parity test gate.
2. Verification session on CUDA hardware builds, runs, reports
   numbers verbatim.
3. Close-but-not-quite gates → report and ask, never silently
   relax. (Caught the D65 over-bright stand-in this way; will
   probably catch more such bugs going forward.)
4. Confounded "is dispatch alive?" gates → file a follow-up
   package for an unconfounded test (pkg54d pattern), don't
   loosen the gate.
5. New: any package that claims "matches Cycles" or "competitive
   with Cycles" must produce numbers from the pkg71 framework
   when it lands. Anecdotal claims do not satisfy acceptance.

---

## 9. Practical conclusion

Tier 1+2 cleared (pkg63 fix, pkg69, pkg68, pkg57, pkg70) plus
the pkg71 spec gives us:

- Blender shader-node integration delivered (pkg57).
- OIDN at full speed on the user's RTX (pkg68 + pkg70 give
  CUDA-OIDN and OptiX as backend choices).
- Compositor denoise workflow drop-in (pkg69).
- Measured parity numbers (pkg71).
- Clean HDRI parity (pkg63 once fixed).

Then pkg56 (incremental scene sync) is the last big Blender-
integration package; pkg64 (caustics) is the visual flagship.
Only after both of those will we revisit Pillar 4 — at which
point the pkg41/pkg42/pkg43/pkg44/pkg47/pkg48/pkg49 specs are
already Codex-paste-ready.

Bump this report's date and rewrite when the queue moves
substantially (likely after pkg57 lands, or when pkg56 starts).
