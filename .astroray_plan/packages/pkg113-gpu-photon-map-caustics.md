# pkg113 — GPU port of the photon-map caustics, with CPU/GPU parity

**Pillar:** 3 (light transport) + 5 (GPU)
**Track:** A
**Status:** **Phases 1 + 2 DONE** (RTX-verified). **Phase 3 WIRING DONE + 2 of 3 polish
fixes LANDED; one focused follow-up remains** (branch `feat/pkg113-gpu-caustic-gather`,
RTX-checked 2026-06-09). FIXED: (1) the SMS regression — new opt-in `usePhotonCaustics`
flag gates the pre-pass so legacy SMS scenes are untouched (`test_pkg64_gpu_phase3_prism_
receiver_energy` passes again; 60 GPU tests, 0 regressions); (2) the gather radius now
matches the CPU `1.5*median(k-th-nearest)` via a `kKthNearest` kernel + two-pass build.
REMAINING (fully root-caused): the caustic-ROI energy is ~430x the CPU NOT from the radius
(it is ROI-invariant under peak95 auto-scale) but from the density ESTIMATOR — the GPU
`photonGridGather` is FIXED-radius while the CPU `estimateIrradiance` is an ADAPTIVE k-NN +
cone filter (sharp focal-core peak). Fixed-radius over-smooths the core → flat peak → scale
too high → the (real, shared) aberration skirt clears the ROI floor. **Fix = a separate
adaptive k-NN cone gather for the caustic path** (mirror `photon_map.h:89-108`; keep the
fixed-radius gather for the phase-1 store test). Glass-sphere gate xfailed until then; **NOT
merged** (draft PR). Verified identical CPU/GPU aperture+emission+normals via CAUSTIC_DBG. Phase 1: GPU uniform hash-grid photon STORE +
device query (4/4 PASS vs numpy oracle). Phase 2: GPU photon EMISSION + bounce →
deposit (forward Snell/Schlick/per-λ Sellmeier/TIR port of `light_tracer_caustic.cpp`
general path; flat-prism 2-face stays CPU) — **3/3 PASS on RTX**. Phase 3: scene-driven
photon-caustic PRE-PASS (`src/gpu/photon_caustic.cu`: forward BVH photon trace through
the uploaded caustic-caster glass → resident hash grid + calibrated radius/scale,
mirroring the CPU pkg111 `spectral_path_tracer.cpp::buildPhotonMap`) + `photonGridGather`
wired into BOTH GPU integrators (the spectral `multiwavelength_kernel.cu` path_tracer
and the RGB `path_trace_kernel.cu`) at the primary receiver hit, adding `albedo·E·scale`
(the device twin of `sampleFull` l.207-221). Legacy SMS-GPU is disabled when the photon
grid is active (parity doc Decisions §1, no double-count). Acceptance test
`tests/test_gpu_caustic_parity.py` (CUDA-gated): glass-sphere GPU-vs-CPU caustic-ROI
energy parity + SSIM + PNG visual check. **In scope: the glass SPHERE (closed solid,
general loop correct). OUT of scope on GPU: the flat dispersive PRISM — the GPU general
loop scatters a flat 2-quad caster into noise (Phase 2 decision; the 2-face port is a
documented follow-up, xfailed in the test).** SSIM≥0.97 is documented-unreachable for
the noisy full render (pkg64-gpu retired the identical gate; memory
`ssim-wrong-gate-for-independent-rng`) — the robust caustic-ROI energy parity + visual
PNG is the real gate. **GPU-gated: correctness must be RTX-`/verify`-ed + the PNGs
eyeballed; CI has no GPU and CI-green ≠ correct.**
**Estimated effort:** L (~3–4 weeks, multiple RTX sessions)
**Depends on:** pkg109 (photon-map kd-tree, done), pkg110 (BSDF photon bounce, done),
**pkg111** (CPU k-NN gather into the default path — do FIRST). The caustics-fork is
**decided** (owner 2026-05-30: the photon map is the canonical GPU caustic path,
SMS-GPU is legacy — `cpu-gpu-parity-status.md` Decisions §1), so pkg113 IS the GPU
caustic work, not subordinate to pkg64-gpu. Related: pkg55-B' (wavefront).

---

## Goal

**Before:** the forward photon-map caustics (pkg106/109/110, and pkg111 once it
lands) run **CPU-only**. `light_tracer_caustic` declares `capabilities() =
{gpuSupported=false}`; there is no GPU photon map, no GPU photon bounce, and no
GPU gather. A scene that shows a prism rainbow or a glass-sphere caustic on CPU
shows **none of it** on a GPU render — breaking the "everything runs on GPU with
CPU/GPU equivalence" goal.

**After:** the photon-map caustic pipeline runs on the GPU and matches the CPU
result within a pinned tolerance:
1. **Photon emission + bounce** on the GPU (the forward trace through flagged glass,
   per-λ Sellmeier refraction — reuse the pkg64-gpu Sellmeier upload + hero-λ IOR).
2. **Photon store** on the GPU — either a CUDA build of the `photon_map.h` kd-tree
   **or** a uniform spatial hash grid (pbrt-v4 SPPM style; see Non-goals on which).
3. **k-NN / radius gather** on the GPU at receiver hits, wired into the GPU
   integrator the same way the CPU gather wires into the default `path_tracer`
   (pkg111).
And it is **gated** to track the CPU photon-map result (SSIM + the existing
hue_spread / glass-sphere concentration acceptance, re-measured on GPU).

---

## Context / fork

`.astroray_plan/docs/cpu-gpu-parity-status.md` is the umbrella. Both gating points
are now **DECIDED (owner, 2026-05-30)**:

1. **Architectural fork — DECIDED: the photon map is canonical; SMS-GPU is legacy.**
   The forward photon map (this chain) is the one GPU caustic path; SMS (pkg64-gpu)
   is frozen/legacy and is NOT extended further. So pkg113 *replaces* SMS-GPU as the
   caustic path (SMS retained only for any specular-manifold case the photon map
   can't cover). (parity doc Decisions §1.)
2. **Store + equivalence bar — DECIDED: GPU uniform hash grid + SSIM/energy parity
   (tiered equivalence).** Caustics are stochastic/Monte-Carlo, so the equivalence
   bar is perceptual (SSIM ≥ ~0.97 + energy bounds), NOT bit-exact. Build the GPU
   store as a **uniform spatial hash grid** (pbrt-v4 `cpu/integrators.cpp` SPPM,
   Apache-2.0 — far friendlier to GPU parallelism than the CPU balanced kd-tree) and
   gate on SSIM/energy vs the CPU result. Do **not** port the kd-tree for bit-exact
   parity. (parity doc Decisions §2.)

CLAUDE.md §6: cite Jensen 1996 (photon map) + pbrt-v4 SPPM grid (Apache-2.0) +
Wilkie 2014 (hero-λ); same algorithm citations as pkg109/110, no GPU-specific
algorithm invented.

---

## Phases

### Phase 1 — GPU photon store + parity-harness (RTX)
- Implement the **uniform hash-grid** store (decided — see Context) + a device build
  pass. Mirror pbrt-v4 `cpu/integrators.cpp` ToGrid/Hash/NextPrime (Apache-2.0).
- Unit parity: build the store from a fixed photon set on GPU, gather at fixed query
  points, compare to the CPU `photon_map.h` gather. Tolerance: an aggregate
  energy/SSIM bound (the gather is a stochastic density estimate, not bit-exact).
- Mirror the pkg64-gpu probe-harness pattern (host wrapper + device entry point), and
  heed memory `[[pkg64-gpu-blockers-stale-option-b]]`: land the probe harness WITH the
  core, or the gates can't run.

### Phase 2 — GPU photon emission + bounce
**Status: implemented (branch `feat/pkg113-gpu-photon-emission`, 2026-06-08 — awaiting
RTX `/verify`).** Device kernel `kEmitPhotons` (`src/gpu/photon_emission.cu`) +
host-callable `cuda_photon_emit_sphere` (`include/astroray/gpu_photon_emit.h`) +
`_gpu_photon_emit_sphere` pybind. Parity test `tests/test_gpu_photon_emission.py`
(CUDA-gated) compares the GPU deposit set to a numpy float64 oracle of the identical
math (same jittered aperture lattice, Sellmeier IOR, Schlick transmittance, CIE-CMF
table) by aggregate bounds: total Y-energy ±5 %, Y-weighted centroid < 0.05·radius,
radial RMS extent ±15 %. **Flat-prism decision: stays CPU** (the general loop covers
the glass sphere + any solid/curved caster; the 2-face path needs host-side geometry
classification not uploaded to GPU and scatters into chromatic noise on a flat caster
— research note + `gpu_photon_emit.h` header). NOTE: not yet RTX-built/verified.
- Port the deterministic refraction loop (`light_tracer_caustic.cpp` general path) to
  a device kernel: Snell + Schlick-Fresnel, enter/exit from the geometric-normal sign,
  per-λ `iorAt` (reuse pkg64-gpu Sellmeier upload), TIR; deposit per-λ CIE flux into
  the Phase-1 store. Keep the **flat-prism explicit 2-face** path too (or decide it
  stays CPU — the prism is a flat special case).
- Parity: GPU deposit set vs CPU deposit set on the prism + glass-sphere scenes
  (aggregate energy/position bounds).

### Phase 3 — GPU gather wired into the integrator + acceptance gates (RTX)
- Gather at receiver hits in the GPU integrator (mirror pkg111's CPU wiring).
- Re-run the acceptance scenes on GPU: `prism-bk7-collimated`
  (hue_spread ≥ 0.65–0.7 + bright_coverage ≥ 0.5) and `glass-sphere-caustic`
  (peak/median concentration gate). **Visual check required** (memory
  `[[general-photon-loop-needs-solid-glass]]`: the caustic numeric gates pass on
  salt-and-pepper noise — always `Read` the rendered PNG).
- **GPU-vs-CPU parity gate:** SSIM ≥ 0.97 on both scenes at the test spp (matching the
  pkg64-gpu / pkg54b + pkg82 variance envelope), plus an energy-ratio bound.

---

## Acceptance criteria (summary)

| Gate | Threshold | Source |
|---|---|---|
| GPU store gather vs CPU (Phase 1) | aggregate energy/SSIM bound (hash grid; stochastic) | pkg64-gpu Phase-1 style |
| GPU-vs-CPU caustic SSIM | ≥ 0.97 | pkg64-gpu + pkg54b/pkg82 envelope |
| Prism rainbow on GPU | hue_spread ≥ (pkg110 gate) + bright_coverage ≥ 0.5 + **visual** | pkg106/110 |
| Glass-sphere caustic on GPU | peak/median concentration (pkg110 gate) + **visual** | pkg110 |
| No regression on `pytest tests/ -k gpu` | pass | standard |

---

## Non-goals

- **Not** until the §3 fork is decided and pkg111 (CPU default-path gather) lands.
- **Not** a new caustic algorithm — port pkg109/110/111 math only.
- **Not** SPPM progressive radius reduction (separate pkg112) — fixed radius + enough
  photons, same as the CPU chain.
- **Not** a CI gate — GPU correctness can't be CI-verified; gate on RTX `/verify`.
- **Not** touching the SMS GPU path (pkg64-gpu) unless §3 chooses to deprecate it
  (separate change).

---

## References

- `.astroray_plan/docs/cpu-gpu-parity-status.md` — umbrella + the fork.
- `.astroray_plan/docs/pkg109-110-111-photon-map-research.md` — CPU algorithm + citations.
- `packages/pkg109-photon-map-core.md`, `pkg110-bsdf-driven-photon-bounce.md`,
  `pkg111-caustic-gather-default-path.md` — the CPU chain.
- `packages/pkg64-gpu-spectral-caustics.md` — the SMS GPU port; mirror its phased
  probe-harness + parity-gate methodology, and the pkg55-C megakernel→wavefront note.
- Jensen 1996; pbrt-v4 SPPM grid (Apache-2.0); Wilkie 2014 hero-λ.
