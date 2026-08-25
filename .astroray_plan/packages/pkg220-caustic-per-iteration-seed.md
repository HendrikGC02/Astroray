# pkg220 — Progressive GPU photon-caustic seed (caustic noise must average across iterations)

**Pillar:** 3 (light transport / spectral rendering)
**Track:** A
**Status:** open (filed 2026-08-25, architect planning pass)
**Priority:** HIGH — visible correctness/quality bug: caustics are permanently
grainy and never clean up no matter how long the render runs.
**Estimated effort:** S–M (thread one integer through 3 files; no new algorithm,
no register-topology change).
**Implementer tier:** deepseek-v4-pro / sonnet (well-specified, gated). This is a
plumbing + numerics change with clean acceptance gates — NOT Opus-only.

---

## Root cause (CONFIRMED IN CODE this session — do not re-investigate)

The GPU photon-caustic pre-pass rebuilds a **byte-identical photon map on every
progressive iteration**, so its Monte-Carlo noise is *frozen* and the camera-ray
accumulator can never average it down. The caustic stays grainy forever.

Trace:
- `src/gpu/photon_caustic.cu`, kernel `kEmitSceneCaustic` (~line 146): the photon
  wavelength and aperture-disc position are drawn from `pc_jitter(cell, salt)`
  (~line 108), a hash keyed **only** on the thread cell index and a compile-time
  `salt`. There is **no seed / frame / iteration parameter**. Lines 166, 171–172:
  ```
  float uLam = pc_jitter(cell, 101u);
  float jx   = (gx + pc_jitter(cell, 1u)) / float(apertureN);
  float jy   = (gy + pc_jitter(cell, 2u)) / float(apertureN);
  ```
  Every launch produces the same λ and (jx,jy) for a given cell ⇒ identical photon
  set ⇒ identical deposits ⇒ identical grid ⇒ identical caustic.
- `cuda_photon_caustic_build` (`photon_caustic.cu` ~line 339) takes no seed.
- Its caller `cuda_wavefront_render` (`src/gpu/wavefront/gpu_wavefront_snapshot.cu`
  ~line 1448) already receives a per-call `seed` (function signature ~line 1306,
  `uint64_t seed`) but does **not** thread it into `buildCausticAim` (~line 1262)
  or into `cuda_photon_caustic_build`. `buildCausticAim` fixes `std::mt19937
  gen(12345u)` (~line 1291) — correct for the *aim geometry* (sun direction must be
  deterministic frame-to-frame) but the photon **jitter** must vary.

The addon accumulates progressively across successive `cuda_wavefront_render`
calls (pkg191: `renderSeed == 0` → fresh-random per iteration; viewport progressive
refinement and F12 progressive loop both re-call the render with advancing state).
So the *fix hook is per-call*: give each render call an independent photon map and
the existing accumulator averages them.

The **CPU path has the same class of bug** (`plugins/integrators/
spectral_path_tracer.cpp::buildPhotonMap`, ~line 410 `std::mt19937 gen(12345u)`),
but the CPU photon map is built once per `render()` and the CPU integrator's own
sample loop runs inside that single call, so CPU caustics DO average within a
render. **This package is GPU-only** unless the acceptance gate below reveals a CPU
regression; if you touch the CPU path at all, keep its single-build-per-render
semantics and only vary the seed per `render()` call (leave CPU out of scope if in
doubt — file a follow-up).

---

## Goal

Successive progressive iterations of a GPU caustic render must use **statistically
independent** photon maps, so the accumulated caustic converges: its per-pixel
Monte-Carlo noise in the caustic region must drop like ~1/√N with the number of
accumulated iterations N, instead of staying frozen.

Non-goals: no change to the caustic *algorithm*, the gather, the radius/scale
calibration, or the register topology. This is a decorrelation fix only.

---

## Specification

### 1. Thread a per-iteration seed into the aim

- `include/astroray/gpu_photon_caustic.h`, `struct PhotonCausticAim`: add
  `unsigned int seed;` (document: "per-iteration decorrelation seed for the photon
  jitter; the aim GEOMETRY stays deterministic — only λ + aperture jitter use it").
- `gpu_wavefront_snapshot.cu`, `buildCausticAim(const Renderer&, int maxDepth)`:
  add a parameter `unsigned int seed` and set `aim.seed = seed`. Keep the
  `std::mt19937 gen(12345u)` that derives `sunDir` UNCHANGED (aim geometry must not
  jitter between iterations, or the caustic would swim instead of converge).
- At the call site (~line 1449–1450): pass a seed derived from the render's
  `seed` argument. Use `static_cast<unsigned int>(seed ^ (seed >> 32))` so the full
  64-bit render seed influences it. (The render `seed` already advances per
  progressive iteration via the addon; when `seed == 0` the CPU sentinel means
  "random" — see memory `seed-zero-is-random-sentinel` — but by the time it reaches
  `cuda_wavefront_render` a concrete per-iteration value has been chosen upstream;
  do not special-case 0 here, just mix it.)

### 2. Thread the seed into the emit kernel

- `photon_caustic.cu`, `cuda_photon_caustic_build`: read `aim.seed` and pass it as
  a new `unsigned int seed` kernel argument to `kEmitSceneCaustic`.
- `kEmitSceneCaustic`: add `unsigned int seed` param. Mix it into every jitter draw
  so each cell's λ and aperture position decorrelate per iteration. Change the salt
  argument, do NOT change the hash function:
  ```
  float uLam = pc_jitter(cell, 101u ^ seed);
  float jx   = (gx + pc_jitter(cell, 1u ^ seed)) / float(apertureN);
  float jy   = (gy + pc_jitter(cell, 2u ^ seed)) / float(apertureN);
  ```
  Rationale: `pc_jitter(cell, salt)` already mixes `cell*0x9E3779B1u +
  salt*0x85EBCA77u` then avalanches; XOR-ing the seed into the salt gives a
  well-mixed independent stream per iteration without a curand state (keeping the
  pre-pass stateless, as its header comment requires). Verify the three salts stay
  distinct after the XOR (they do: 1,2,101 XOR the same seed stay distinct).

### 3. Accumulation-consistency check (numerics — READ)

Each independent map is renormalized by `result.scale = boost/(π·peak95)`
(`photon_caustic.cu` ~line 530). Because `scale` normalizes the 95th-percentile
peak irradiance, it is **statistically stable** across independent maps of the same
scene (same photon count, same geometry) — so averaging renders built with
different seeds does NOT introduce a brightness bias. **Confirm this empirically**
in the acceptance gate: the converged mean radiance in the caustic region must not
drift as N grows (mean stays put, variance falls). If the mean drifts >5% between
N=4 and N=64, STOP — the scale calibration is seed-dependent and needs to be frozen
from the first iteration (compute `scale` once, reuse it); report this before
"fixing" it another way.

---

## Acceptance criteria

- [ ] **Independence:** two `cuda_photon_caustic_build` calls with different
      `aim.seed` on the same uploaded scene produce **different** deposit sets
      (assert the host-compacted photon position arrays differ in > 1% of entries),
      while two calls with the SAME seed remain byte-identical (determinism within
      an iteration preserved).
- [ ] **Convergence (headline gate):** glass sphere/prism + delta spot + diffuse
      floor (reuse `tests/test_gpu_caustic_parity.py`'s scene or
      `scripts/`-registered caustic harness — do NOT fork a new render script, see
      CLAUDE.md §5b). Accumulate N independent iterations for N ∈ {1,4,16,64}.
      Measure the per-pixel standard deviation across a fixed patch INSIDE the
      caustic (e.g. against the running mean, or via two independent half-sums).
      Assert the caustic-region noise metric falls monotonically and is
      ≤ 0.6× the N=1 value by N=16 and ≤ 0.35× by N=64 (i.e. tracking ~1/√N within
      tolerance). BEFORE the fix this metric is flat (~1.0× at all N) — include the
      before-number to prove the bug existed.
- [ ] **No mean drift:** the caustic-region mean linear radiance at N=64 is within
      5% of the N=4 mean (the §3 check).
- [ ] **Non-caustic scenes unaffected:** a scene with no caustic caster produces a
      byte-identical render to `main` (the pre-pass is gated off, `aim.valid ==
      false`; the new seed param is inert).
- [ ] **Register gate:** `cuobjdump -res-usage` on the built `.pyd` —
      `kEmitSceneCaustic` and the shade fleet unchanged in REG/STACK tier vs `main`
      (this change only alters an integer salt inside an existing kernel; expect
      REG identical). Include the histogram.
- [ ] **CI green** on all matrix jobs; **HW PASS** on RTX 5070 Ti (rebuild the
      `.pyd` first, verify `astroray.__file__` is the canonical `build_cuda`
      output and `cuobjdump --list-elf` shows sm_120 — memory `stale_pyd_locations`).

## Build / verification notes

- Rebuild via `build_cuda_worktree.bat` (PowerShell, NOT `cmd /c` — memory
  `gitbash-cmd-c-pathconv-false-green`); confirm `.pyd` mtime > HEAD commit time.
- Call-site sweep before pushing: `buildCausticAim` signature changed (added a
  param) and `kEmitSceneCaustic` launch changed — grep the repo for every caller
  of both and update all of them (there is one `buildCausticAim` caller and one
  kernel launch today; confirm no test/mock references them).
- Visual guard against salt-and-pepper false positives (memory
  `general-photon-loop-needs-solid-glass`): inspect the accumulated caustic PNG at
  N=64 — it must be a smooth bright patch, not denser noise.

## Reference

- `src/gpu/photon_caustic.cu` (`kEmitSceneCaustic`, `pc_jitter`,
  `cuda_photon_caustic_build`).
- `src/gpu/wavefront/gpu_wavefront_snapshot.cu` (`buildCausticAim` ~1262,
  call site ~1448, `cuda_wavefront_render` seed param ~1306).
- `include/astroray/gpu_photon_caustic.h` (`PhotonCausticAim`).
- `plugins/integrators/spectral_path_tracer.cpp::buildPhotonMap` (CPU twin, for
  reference only — likely out of scope).
- Memory: `seed-zero-is-random-sentinel`, `stale_pyd_locations`,
  `general-photon-loop-needs-solid-glass`, `mc-noise-vs-deterministic`.
- pkg191 (progressive accumulation contract), pkg113 (photon-caustic pipeline).
