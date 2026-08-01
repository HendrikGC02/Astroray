# pkg163 — metal spectral colour-space parity: sourcing & citation trail

## Problem
CPU `MetalPlugin::evalSpectral` (`plugins/materials/metal.cpp:106-146`) builds
the conductor BSDF **per wavelength**: F0 = albedo spectrum, per-λ Schlick
Fresnel, per-λ Kulla & Conty energy compensation. The GPU (`gpu_metal_eval`,
`include/astroray/gpu_materials.h`) built the whole f in **RGB** and then
upsampled the sum **once** through the Jakob-Hanika LUT in the spectral wrappers
(`gpu_material_sample_spectral` / `gpu_material_eval_spectral`). The JH upsample
is nonlinear and not scalar-homogeneous, so the two constructions agree only for
a flat albedo. Chromatic albedo diverged, worst at high roughness + grazing
(measured GPU/CPU B = 1.0722 at r=0.9 — pkg160's documented band exception).

## Direction chosen — A (GPU goes per-wavelength for metal)
Architect recommendation. Implemented `gpu_metal_eval_spectral` as the device
mirror of `MetalPlugin::evalSpectral`, routed through the two spectral wrappers
for `GMAT_METAL` and the closure-graph conductor lobe (plain `metal` uploads as
a closure graph — its `GGXConductor` lobe validates). Sampling/pdf unchanged;
only the f-spectral construction moves per-λ. Direction B (drop CPU metal to the
RGB fallback) was NOT taken — it lowers the oracle's spectral accuracy and needs
owner approval; only warranted if A's measured register cost is material.

## Algorithm sourcing (CLAUDE.md §6)
This is a mirror of already-in-repo, already-cited code, not a new derivation.
The canonical sources (carried in the code comments):

- **Kulla & Conty 2017**, "Revisiting Physically Based Shading at Imageworks"
  (SIGGRAPH course) — the GGX multiple-scattering energy-compensation lineage,
  net factor `1 + Fms*(1-E)/E`. Same term already in `MetalPlugin` and
  `DisneyPlugin::ggxCompensationFactor`.
- **Cycles** `intern/cycles/kernel/closure/bsdf_microfacet.h`
  (`microfacet_ggx_preserve_energy`), **BSD-3-Clause** (license confirmed by
  pkg124/#501). Source of the E / Eavg tables (`g_ggxE` / `g_ggxEavg`, uploaded
  from `DisneyEnergyCompensationTables`).
- **Jakob & Hanika 2019**, "A Low-Dimensional Function Space for Efficient
  Spectral Upsampling" (CGF/EGSR) — the RGB→spectral upsampler whose
  nonlinearity IS the divergence mechanism. GPU device twin `gpu_jhEvalSpectrum`
  (pkg54c), CPU `RGBAlbedoSpectrum::sample`.
- CPU canonical mirror source for the per-λ construction:
  `plugins/materials/metal.cpp::MetalPlugin::evalSpectral`.

## Seam statement (spec §"The seam" binding consequence 2)
Post-fix, metal's RGB→spectral upsample sits at the **F0 input** (albedo → JH
per-λ), and the whole BSDF (Fresnel + compensation) is composed per-λ after it —
identical seam position to CPU `MetalPlugin::evalSpectral`. This satisfies the
architect's per-material CPU-canonical seam rule: metal's twins are both per-λ;
Disney's twins remain both per-RGB (its conductor closure lowers to
`gpu_disney_eval`, `disneyMetalConductor` flag, out of scope); glass stays
scalar-neutral. No intra-lobe seam was introduced — Fresnel and compensation
move together per-λ, never one spectral while the other stays RGB.

## Register cost (spec gate 4) — PENDING team-lead HW gate
Direction A adds per-λ arithmetic on the 4-λ state the kernel already carries.
The plausible cost is small but plausibility is not evidence; the shade-stage
regs/thread (runtime profile, not static `-Xptxas -v` under `-rdc=true`) must be
measured before/after by the team-lead's HW gate. If material vs pkg155's ≤128
target, escalate to owner/pkg155 before merge.

## Not verified locally
No CUDA build/verify on the implementer box (no vcvars in subagent shells).
Build + RTX hardware sweep (both parity gates + register measurement) are the
team-lead's HW gate.
