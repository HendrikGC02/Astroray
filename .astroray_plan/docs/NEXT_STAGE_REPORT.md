# Astroray Next Stage Report

**Date:** 2026-05-10
**Prepared by:** Claude (Anthropic Code, Sonnet 4.5 in Max 5x)
**Scope:** post pkg54a/b verification — handoff playbook of which agent
gets which package next, with the exact prompt to drop into each.

> This file is the **action queue**, not the strategy doc. Strategy lives
> in [`ROADMAP.md`](ROADMAP.md); current status in [`STATUS.md`](STATUS.md).
> Use this doc to decide what to spawn into Codex / Claude Code / etc.
> *today*. Bump the date and rewrite when the queue moves.

---

## 1. Current state (one screen)

- **Pillars 1, 2, 3** complete and validated.
- **Pillar 4** entirely open — twelve packages waiting (`pkg40`-`pkg51`).
  Most are physics-heavy with well-published reference implementations,
  so they are excellent Codex food once the spec carries the canonical
  reference.
- **Pillar 5 (Cycles parity / Blender)** is the active queue. Nine of
  thirteen packages done as of this report; pkg54a/b just verified on
  CUDA hardware (commit `b3d59af`). Open: pkg54c, pkg54d, pkg57, pkg63,
  pkg64, pkg67.
- **Two scoped follow-ups created during pkg54 verification:**
  - `pkg54c` — GPU Jakob-Hanika spectral upsampling (lifts visible SSIM
    ceiling 0.985 → 0.999).
  - `pkg54d` — direct `gpu_profile_reflectance` Python binding (turns
    pkg54a liveness gate from a scene-physics-confounded SSIM check
    into a true unit test).
- **Subscription change (2026-05-10):** Anthropic Max 5x. Claude Code
  can now comfortably run 3–4 hour focused sessions, so larger
  multi-session packages (pkg54c, pkg57, pkg64) become reasonable to
  hand to Track A.

---

## 2. Recommended order this week

| # | Package | Owner | Why this slot |
|---|---|---|---|
| 1 | **Research note** `blender-shader-nodes-research.md` | Claude | Unblocks pkg57 (the hardest open Pillar 5 package). ~½ day. |
| 2 | **pkg54d** | Codex | Half-day, fully specified, closes the pkg54 verification story cleanly. |
| 3 | **pkg47** (FITS loader) | Codex | Easiest Pillar 4 onramp — pure I/O, no algorithmic risk. Builds Codex's familiarity with the codebase before the harder physics packages. |

Then next week:

| # | Package | Owner | Why this slot |
|---|---|---|---|
| 4 | **pkg54c** | Claude | Finishes the pkg54 family at full visible-band parity. ~3–5 days. |
| 5 | **pkg63** | Codex (after I write a 1-page Cycles crib) OR Claude | World/HDRI parity. Three concrete features; Cycles has direct counterparts. |
| 6 | **pkg40** + **pkg41** in parallel | Codex | Kerr metric + validation. Pillar 4 ignition. |

Then the flagships (multi-week, Claude-owned):

| # | Package | Owner | Notes |
|---|---|---|---|
| 7 | **pkg57** | Claude | Native shader nodes. Gated on item #1 above. ~2 weeks. |
| 8 | **pkg64** | Claude | Spectral caustics. Research already signed off. ~3–4 weeks. The marquee deliverable for the eventual paper. |

---

## 3. Drop-in prompts per agent

### 3.1 Codex — pkg54d (do first, half-day)

```
Read .astroray_plan/packages/pkg54d-gpu-profile-lookup-binding.md and
implement it end to end against the current main (commit b3d59af or
later — pkg54a/b are merged and verified).

Required reading before writing code:
  - src/gpu/multiwavelength_kernel.cu (g_profileTable + gpu_profile_reflectance)
  - src/gpu/scene_upload.cu (profile dedup table builder)
  - module/blender_module.cpp (where pybind11 bindings are declared)
  - tests/test_multiwavelength.py (existing CPU spectral_profile_reflectance
    test for reference equality)

Implementation outline:
  - Add a one-thread CUDA kernel `gpu_profile_lookup_kernel(int profileIndex,
    float lambda, float* out)` to multiwavelength_kernel.cu that just calls
    gpu_profile_reflectance and writes the result to *out.
  - Add a CUDARenderer::lookupProfileReflectance(int idx, float lambda)
    host method that allocates a float on device, launches the kernel,
    copies back, frees, returns.
  - Bind it through PyRenderer in module/blender_module.cpp as
    `_gpu_profile_lookup(int profile_index, float lambda) -> float`.
    Profile index is whatever scene_upload assigned during the most
    recent uploadScene() — there's no name lookup on the GPU side.
  - Test (tests/test_gpu_profile_lookup.py): for every profile in
    spectral_profile_names(), compare CPU spectral_profile_reflectance
    vs GPU lookup at every grid point (300 + 5*k for k in 0..140).
    Gate: |cpu - gpu| < 1e-6 at every point. Skip if no CUDA.

Constraints:
  - Read CLAUDE.md sections 2 and 3 (Simplicity First, Surgical Changes).
  - Do NOT invent algorithms — this is mechanical plumbing.
  - When done: PR against main with the gate green.
```

### 3.2 Codex — pkg47 FITS loader (do second, ~2 days)

```
Read .astroray_plan/packages/pkg47-fits-loader.md and implement it
end to end. This is your Pillar 4 onramp — pure I/O package.

Reference implementations (clone, study, do NOT vendor wholesale):
  - cfitsio (NASA, public domain) — the canonical FITS C library.
    Use it as a system dependency, do NOT mirror.
  - Astropy's astropy.io.fits (BSD-3) — pythonic reference for what
    a clean FITS reader API looks like.

Constraints:
  - cfitsio MUST be a CMake find_package, NOT vendored. Header
    detection via FindCFITSIO.cmake (write one if needed).
  - Add to CMake guarded by ASTRORAY_ENABLE_FITS=ON, default OFF until
    the dependency is sorted on the user's Windows toolchain.
  - One small Python binding: astroray.load_fits_volume(path) -> np.ndarray.
  - Test against tests/data/ — create one tiny synthetic FITS cube
    using astropy at test-write time, no large checked-in binaries.
  - Read CLAUDE.md sections 2, 3, 6 (especially section 6 — cite the
    cfitsio version + commit you tested against in code comments).
  - When done: PR against main, status -> done in pkg47 + STATUS.md.
```

### 3.3 Claude (me) — research note `blender-shader-nodes-research.md`

The prompt to give Claude when starting that session:

```
Write .astroray_plan/docs/blender-shader-nodes-research.md.

Goal: unblock pkg57 (native Astroray shader nodes). The doc must
answer "how do production third-party render engines ship their own
shader nodes inside Blender, survive engine-switching, and stay
non-destructive against Cycles' BsdfPrincipled?"

Required source reading (use WebFetch + git clone in /tmp as needed):
  - Blender source: source/blender/nodes/, source/blender/python/
    (look for ShaderNodeCustomGroup, register_node_categories,
    NodeSocket subclasses).
  - Cycles addon-side: intern/cycles/blender/blender_shader.cpp,
    intern/cycles/blender/blender_session.cpp.
  - BlendLuxCore (MIT, https://github.com/LuxCoreRender/BlendLuxCore)
    — closest precedent: third-party engine, ships custom nodes,
    must coexist with Cycles. Read at least:
      src/properties/node_meta.py
      src/nodes/__init__.py
      src/nodes/output/__init__.py
      src/export/material/__init__.py
  - Octane's Blender addon (proprietary but docs are public) — study
    how they describe their custom node namespace pattern; do NOT
    copy code.
  - PBRT-v4 Blender exporter (Apache-2.0) for a third reference.

Required answers (each gets its own H2 section):
  1. The custom node base class — ShaderNodeCustomGroup vs
     bpy.types.Node subclass; trade-offs.
  2. Engine-switching survival: how does a node tree containing
     Astroray-only nodes behave when the user switches engine to
     Cycles? Three options to evaluate: (a) custom-property stash,
     (b) ID-property mirror, (c) graceful degrade to a fallback
     Cycles node. Recommend one with reasoning.
  3. Per-socket typing for Astroray-specific data (Sellmeier
     coefficient triples, spectral profile names) — bpy.types.NodeSocket
     subclass vs encoding into a string socket.
  4. Conversion path: Astroray addon side reads the node tree via
     depsgraph; mirror Cycles' approach or invent our own?
  5. Open questions list — explicit items pkg57 will need to resolve
     in code that this research could not pin down on paper.

Length: ~3-5 pages. Cite licenses for every external repo referenced.
Save research notes per CLAUDE.md section 6.
```

### 3.4 Claude (me) — pkg54c after the research note lands

```
Implement .astroray_plan/packages/pkg54c-gpu-jakob-hanika-upsampling.md
end to end against current main.

Required reading:
  - src/spectrum.cpp (search for JakobHanikaLut, sigmoidJH,
    evalSigmoidCoeffs — the CPU implementation we're mirroring)
  - data/spectra/rgb_to_spectrum_srgb.coeff (the LUT layout reference)
  - src/gpu/multiwavelength_kernel.cu (where the new path needs to
    replace gpu_spectralChannelWeight for non-illuminant modes)

Key design constraint:
  The Jakob-Hanika LUT for sRGB is 64 x 64 x 64 x 3 channels x 3
  sigmoid coefficients = 2,359,296 floats = 9 MB. This OVERFLOWS
  __constant__ memory (64 KB cap). Two options:

  Option A — cudaTextureObject_t with normalized 3D texture:
    Bind the LUT as three 3D textures (one per RGB-major channel),
    use tex3D<float4>() to fetch (sigmoid coeffs are 3 floats per
    voxel, pack into float4 with the existing scale[] table padded).
    Hardware trilinear interpolation if we want it, though the CPU
    code does manual interpolation, so for parity we'd disable it
    and do nearest-fetch then interpolate in software.

  Option B — global memory + manual interpolation:
    Simpler to implement; cudaMalloc + cudaMemcpy at scene upload,
    pass __device__ const float* into the kernel. Slower per-fetch
    but the LUT is read O(1) times per spectrum-sample so it
    likely doesn't matter.

  Do option B first. Profile against pkg54b's visible-band SSIM gate.
  If the gate is met (>= 0.999) and frame-rate is within 10% of pkg54b
  baseline, ship as-is. If not, switch to option A.

Acceptance:
  - tests/test_gpu_multiwavelength.py test_visible_band_cpu_gpu_ssim
    gate raised from 0.985 to 0.999.
  - No regression on NIR/UV gates (still >= 0.97).
  - Visible-band frame-time within 10% of pkg54b baseline (record
    in the package doc Lessons section).

Constraints:
  - CLAUDE.md sections 2, 3 apply.
  - Cite Jakob & Hanika 2019 ("A Low-Dimensional Function Space for
    Efficient Spectral Upsampling", Eurographics) in the kernel
    header comment.
  - Do NOT touch path_trace_kernel.cu unless the CMF change in
    pkg54b somehow needs to follow through here too — verify first.
  - When done: PR, promote pkg54c to done, update STATUS.md.
```

### 3.5 Codex — pkg40 Kerr metric (after pkg54d + pkg47 land)

```
Read .astroray_plan/packages/pkg40-kerr-metric.md and implement it
end to end. This kicks off Pillar 4.

Reference implementations (study, cite, mirror selectively per
CLAUDE.md section 6 — all three are MIT/BSD-compatible except where
noted):
  - RAPTOR (Bronzwaer et al. 2018, MIT) —
    https://github.com/tbronzwaer/raptor
    The Kerr metric inverse + Christoffel symbols are in
    src/metric.c. This is the cleanest reference.
  - ipole (Mościbrodzka & Gammie 2018, BSD-3) —
    https://github.com/AFD-Illinois/ipole
    Cross-check formulae, especially for Boyer-Lindquist vs
    Kerr-Schild coordinate choice.
  - GYOTO (Vincent et al. 2011) — CeCILL license,
    INCOMPATIBLE WITH OUR MIT. Read for understanding only,
    DO NOT copy code.

Implementation outline (subject to the package spec):
  - include/astroray/metric.h: Metric base class with
    christoffel(t, x, y, z) -> float[4][4][4] and
    inner_product(t, x, y, z, vec_a, vec_b) -> float.
  - plugins/metrics/kerr.cpp: KerrMetric implementing the above,
    parameterized by mass M and spin a.
  - plugins/metrics/schwarzschild.cpp: thin wrapper around
    KerrMetric with a=0; this is the "extraction" deliverable.
  - Tests: analytic checks for ISCO radius, photon sphere radius,
    frame-dragging at Boyer-Lindquist. Gate against published
    values from Bardeen, Press, Teukolsky 1972.

Constraints:
  - CLAUDE.md sections 2, 3, 6.
  - Save research notes to
    .astroray_plan/docs/kerr-metric-research.md before writing code,
    citing all three reference repos with their commit SHAs and
    licenses.
  - When done: PR, mark pkg40 done in pkg file + STATUS.md, file
    pkg41 (Kerr validation) as the natural next step (already exists
    — flip its "depends on pkg40" line to "ready").
```

---

## 4. Research notes the project still needs

These are not packages, they are unblockers. Listed in priority order
with the rough effort and recommended owner.

| # | File | Unblocks | Owner | Effort |
|---|---|---|---|---|
| 1 | `blender-shader-nodes-research.md` | pkg57 | Claude | ½ day |
| 2 | `blender-depsgraph-sync-research.md` | pkg56 (deferred — would unlock pkg52's persistence value on big scenes) | Claude | 1 day |
| 3 | `wavefront-gpu-research.md` | pkg55 (deferred — major GPU architecture pass) | Claude | 1 day |
| 4 | `metric-aware-tracer-research.md` | pkg67 | Claude | 1 day, when pkg67 reaches the top of the queue |
| 5 | `kerr-metric-research.md` | pkg40 | Codex (as part of pkg40 itself, see prompt 3.5 above) | included in pkg40 budget |

Note: `caustics-research.md` already exists and is signed off — pkg64 is
ready to start whenever Claude has a 3–4 week window.

---

## 5. Track assignments going forward

Mostly the same as the original ROADMAP, but with one substantive
change: with Max 5x, **Track A (Claude Code)** can now own multi-day
packages without dropping context, so flagship work (pkg57, pkg64)
shifts onto Track A instead of being broken into many small handoffs.

| Track | Agent | Now owns |
|---|---|---|
| A. Core quality | Claude Code | pkg54c, pkg57, pkg64, all Pillar 4 packages with novel algorithm content (pkg42, pkg50). Multi-session research notes. |
| B. Feature breadth | (currently inactive) | — |
| C. Experiments | (currently inactive) | — |
| D. Grind work | (currently inactive) | — |
| E. Coordination/review | Codex | pkg54d, pkg47, pkg40, pkg41, pkg43, pkg44, pkg45, pkg46, pkg48, pkg49, pkg51 — anything where the spec + reference implementation pin down the answer. PR review. |

Track B/C/D are not staffed right now; nothing is on fire because of
that, but if you want to run Copilot or a Ralph loop, the obvious
candidates are: docstring/comment cleanup, additional GPU smoke tests
mirroring CPU ones, and CHANGELOG.md catch-up.

---

## 6. Verification posture (carry-forward from pkg54a/b lessons)

Every GPU package from here on should follow the verification pattern
that landed pkg54a/b cleanly:

1. **Implementation session** writes code + a parity test scene + a
   parity test gate. Annotates expected SSIM / numerical thresholds
   in the test docstring, not just as bare numbers.
2. **Verification session** on a CUDA-equipped machine builds with
   `scripts/build_cuda.bat`, runs the new tests, reports actual
   numbers verbatim.
3. If a gate is close-but-not-quite, **report and ask** — do not
   silently relax the threshold or boost spp. The pkg54a/b episode
   showed this directly catches real bugs (the D65 over-bright
   stand-in was found this way).
4. If a gate uses a "dispatch is alive" assertion that turns out to
   be confounded by scene physics (the pkg54a UV ratio episode),
   file a follow-up package for an unconfounded test instead of
   loosening the gate.

---

## 7. Practical conclusion

The next move is the research note in 3.3 — without it, pkg57 is the
biggest blocker and would burn 2–3 implementation days on Blender API
trial-and-error. After that, the queue self-pipelines: Codex on
pkg54d → pkg47 → pkg40/41, Claude on pkg54c → pkg57 → pkg64.

Bump this report's date and rewrite it the next time the queue moves
substantially (after pkg54c lands, or when pkg64 starts).
