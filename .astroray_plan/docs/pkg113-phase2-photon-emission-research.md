# pkg113 Phase 2 — GPU photon EMISSION + BOUNCE → deposit (research note)

Scope: a device kernel that forward-traces a batch of collimated-sun photons
through flagged caustic-caster glass (general deterministic-refraction path) and
deposits the surviving per-λ CIE flux as `GPhoton`s onto the receiver. This is the
GPU port of the GENERAL path of `plugins/integrators/light_tracer_caustic.cpp`
(NOT the integrator gather — that is Phase 3). Built on the Phase-1 store branch
`feat/pkg113-gpu-photon-store` (the `GPhoton` struct + hash grid it ingests).

## What is being ported (math, file:line in the CPU source)

`plugins/integrators/light_tracer_caustic.cpp`, the GENERAL branch (lines 276-326):

| Step | CPU source | Device mirror |
|---|---|---|
| collimated-sun aperture seeding around `sunDir`, disc of radius `crad` | l.219-249, 282-287 | `kEmitPhotons` ONB + uniform-disc sample (curand) |
| per-photon wavelength `λ = lmin + (lmax-lmin)·u01` | l.283 | `curand_uniform` over [380,720] |
| per-λ IOR `iorAt(λ)` (Sellmeier) | l.295 | `gpu_sellmeier_ior` (pkg64-gpu, `gpu_dispersion.cuh`) |
| enter/exit from geometric-normal sign | l.297-300 | `d.dot(ng) < 0 ? entering : exiting` |
| Snell refraction `refract(d, nf, eta)` | l.183-189, 302 | device `pe_refract` (identical formula) |
| TIR → mirror reflect | l.303 | device reflect branch |
| Schlick-Fresnel transmittance accumulate `tr *= fresnelT` | l.190-194, 302 | device `pe_fresnelT` (identical formula) |
| deposit on first diffuse receiver on an L S+ D path | l.313-323 | receiver-plane hit, `passedCaster && n.y>0.7` |
| per-λ CIE deposit `cmf = cieCmf1964_10deg(λ); power = cmf·tr` | l.314-318 | device CMF lookup (same `data/spectra/cie_cmf.inc` table) |

The refraction/Fresnel formulae are *identical* to the CPU `refract()` /
`fresnelT()` private statics — these are the standard Snell vector form and the
Schlick approximation, the same ones already on the GPU in
`sms_attempt_device.cuh:283-307`. No new algorithm.

## Citations (CLAUDE.md §6)

- **Arvo, "Backward Ray Tracing", SIGGRAPH 1986 Course Notes** — forward light
  transport (light particles) for caustics. (CPU header citation, carried.)
- **Jensen, "Global Illumination using Photon Maps", EGWR 1996** (DOI
  10.1007/978-3-7091-7484-5_3) — diffuse-surface photon deposition. The Phase-1
  store ingests the `GPhoton`s this phase produces.
- **Schlick, "An Inexpensive BRDF Model for Physically-based Rendering",
  Eurographics 1994** — the Fresnel reflectance approximation `F0 + (1-F0)(1-cosθ)^5`.
  (Undergraduate-textbook tier per CLAUDE.md §6, but cited for provenance; the
  exact CPU form is mirrored, not re-derived.)
- **Sellmeier 1871**, Annalen der Physik 219(11):272-282 (public domain) — `n(λ)`.
  REUSED via `gpu_sellmeier_ior` (`include/astroray/gpu_dispersion.cuh`,
  pkg64-gpu Sellmeier upload). Dispersion is NOT re-derived here.
- **CIE 1964 10° standard observer CMF** — `data/spectra/cie_cmf.inc` (the same
  1 nm table `src/spectrum.cpp::cieCmf1964_10deg` reads, also mirrored to GPU
  constant memory by pkg54b in `multiwavelength_kernel.cu`). The deposit color is
  the bit-identical host table, linearly interpolated, so the GPU per-λ deposit
  weight matches the CPU one to float precision.

## Reuse points (audited, this branch, file:line)

| What | Where | Note |
|---|---|---|
| `GPhoton` struct (deposit target) | `include/astroray/gpu_photon_store.h:41` | Phase-1 store ingests it |
| `gpu_sellmeier_ior(GDispersion, λ)` | `include/astroray/gpu_dispersion.cuh:19` | per-λ IOR (pkg64-gpu) |
| `gpu_buildONB` | `include/astroray/gpu_materials.h` | aperture frame around sunDir |
| ray-sphere `gpu_sphere_hit` math | `include/astroray/gpu_bvh.h:62` | single-sphere trace (self-contained) |
| GHitRecord frontFace/normal sign | `gpu_bvh.h:50-51,84-85` | geometric enter/exit decision |
| CMF table `data/spectra/cie_cmf.inc` | included like `multiwavelength_kernel.cu:164` | per-λ CIE deposit |
| host-callable + pybind pattern | `photon_store.cu` / `blender_module.cpp:2464` | Phase-1 mirror |

## Flat-prism decision: STAYS CPU (general loop goes on GPU)

The flat-prism explicit 2-face path is NOT ported in Phase 2. Reasons:
1. The general deterministic BVH refraction loop already covers the glass SPHERE
   (the spec's primary GPU caustic target) and any solid/curved caster — it is the
   load-bearing GPU path.
2. The 2-face path depends on host-side geometry classification
   (`gatherTriangleCasters` / `countDistinctCasterPlanes` / `CausticTri`,
   `light_tracer_caustic.cpp:152-181, 234-275`) that is not uploaded to the GPU.
   Porting it would require uploading the per-triangle caster set + plane-grouping
   classifier — scope the spec explicitly leaves optional ("or decide it stays
   CPU — the prism is a flat special case") and which the general loop subsumes for
   the parity scene.
3. Memory `[[general-photon-loop-needs-solid-glass]]`: the 2-face deposit is a
   brittle CPU geometric special case; the general loop on a flat 2-quad caster
   scatters into chromatic noise (CPU header l.20-23). So the clean prism deposit
   stays the CPU special path; the GPU does the general loop, validated on the
   glass sphere.

Phase-2 GPU port = the GENERAL deterministic-refraction loop only. The flat-prism
clean-deposit path remains CPU-only (`light_tracer_caustic.cpp`).

## Parity-test design (aggregate bounds, NOT bit-exact)

`tests/test_gpu_photon_emission.py` (CUDA-gated, mirrors `test_gpu_photon_store.py`
skip pattern). A single BK7 glass sphere + a flat receiver plane below it + a
collimated sun straight down. The GPU entry `_gpu_photon_emit_sphere` forward-traces
N photons and returns the deposit set (positions + XYZ power). A numpy float64
ORACLE runs the IDENTICAL closed-form math (analytic ray-sphere entry/exit, Snell,
Schlick, Sellmeier, CMF) on the SAME stratified aperture samples (no RNG: the
aperture is a deterministic jittered grid passed to both sides) and compares by
AGGREGATE bounds:
  - total deposited Y-energy: GPU/oracle ratio within ±5 %;
  - deposit centroid (x,z): within a small fraction of the sphere radius;
  - deposit radial extent (RMS spread): within ±15 %.
Per memory `[[general-photon-loop-needs-solid-glass]]`, the caustic numeric gates
pass on salt-and-pepper noise, so the test asserts energy AND position bounds, not
a deposit count alone. To remove RNG as a variable for the parity comparison the
aperture sampling is a fixed deterministic jittered lattice (the same lattice fed
to the oracle), isolating the refraction math from Monte-Carlo noise — the same
"inject the same samples both sides" tactic `sms_attempt_device.cuh` uses for its
Phase-1 unit test.

## Files

- `include/astroray/gpu_photon_emit.h` — host-callable entry decl + result struct.
- `src/gpu/photon_emission.cu` — the device kernel + host launcher.
- `module/blender_module.cpp` — `_gpu_photon_emit_sphere` pybind (CUDA-gated).
- `tests/test_gpu_photon_emission.py` — the parity test.
- `CMakeLists.txt` — add `src/gpu/photon_emission.cu` to the CUDA sources.
