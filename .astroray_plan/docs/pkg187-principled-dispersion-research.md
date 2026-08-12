# pkg187 — Principled BSDF dispersion: algorithm research notes

Per CLAUDE.md §6 / the `cite-algorithm` skill: research done **before** writing
the Abbe-number → dispersion-curve mapping.

## Problem

Blender's Principled BSDF (WIP) exposes dispersion as an **Abbe number** (Vd)
plus a **dispersion scale**. The engine needs a per-wavelength IOR `n(λ)` for the
transmission lobe. Do not hand-roll a wavelength dependence — find the canonical
formula and a license-compatible reference implementation.

## Canonical source (borrowed)

**Cycles' WIP Principled/Glass dispersion** — Blender PR
[#162041](https://projects.blender.org/blender/blender/pulls/162041), function
`bsdf_glass_ior` in `intern/cycles/kernel/closure/bsdf_microfacet.h`
(Apache-2.0 / compatible). It implements the **OpenPBR Surface specification
v1.1.1, Eqs. (55) and (56)** — the two-term **Cauchy** empirical dispersion:

```
n(λ) = A + B / λ²                          (Eq. 55, λ in μm)
B    = (n_d − 1) · inv_abbe · fac          (Eq. 56)
A    = n_d − B / λ_d²
fac  = 1 / (1/λ_F² − 1/λ_C²)
```

with the Fraunhofer spectral lines (μm): `λ_d = 0.5876`, `λ_C = 0.6563`,
`λ_F = 0.4861`, and `inv_abbe = dispersion_scale / abbe_number`
(Cycles `safe_divide`, so `inv_abbe = 0` when the Abbe number is 0 → flat IOR).
`n_d` is the IOR at the d line (Blender's `IOR` socket).

Cycles source (paraphrased from the PR diff):

```cpp
// bsdf_glass_ior — Cauchy fit, input ior is the d-line IOR after backface flip.
constexpr float lambda_d = 0.5876f, lambda_C = 0.6563f, lambda_F = 0.4861f;
constexpr float fac = 1.0f/(1.0f/(lambda_F*lambda_F) - 1.0f/(lambda_C*lambda_C));
const float B = (ior - 1.0f) * inv_abbe * fac;   // OpenPBR Eq. 56
const float A = ior - B / (lambda_d*lambda_d);
ior = A + B / sqr(wavelength);                    // OpenPBR Eq. 55
```

The socket→inv_abbe mapping (Cycles OSL / SVM in the same PR):

```
dispersion_scale = clamp(TransmissionDispersionScale, 0, 1);
abbe_number      = max(TransmissionDispersionAbbeNumber, 0);   // default 20
inv_abbe         = safe_divide(dispersion_scale, abbe_number);
```

Cycles collapses the path to a single sampled wavelength on a dispersive
interaction (`SR_BSDF_HAS_DISPERSION`, `dispersion_throughput_weight`) — the
direct analogue of Astroray's `SampledWavelengths::terminateSecondary()`
hero-wavelength collapse, already used by `DielectricPlugin::sampleSpectral`.

## Why Cauchy, not the engine's Sellmeier

The in-repo dielectric (`plugins/materials/dielectric.cpp`) uses **Sellmeier**
coefficients (measured glass presets). The Abbe→dispersion bridge here is
**Cauchy**, matching Cycles exactly — the pkg187 spec explicitly permits
"Cauchy or a reduced-Sellmeier fit from (Vd, IOR at d-line)". A two-term Cauchy
fit from `(n_d, Vd)` is the standard and reproduces Cycles bit-for-bit, so the
`cycles-parity-reviewer` sees the same math. `iorAt`/`isDispersive`/hero-collapse
**structure** mirrors `dielectric.cpp:110-142`; only the closed form differs
(Cauchy vs Sellmeier), and it is cited in-code.

## Blender-socket reality (correcting the spec premise)

The pkg187 spec asserted "Blender 4.2+ exposes a Dispersion input on Principled
BSDF; that value is dropped silently on import." **This is false for every
installed build.** Headless probe (`bpy`, `ShaderNodeBsdfPrincipled` /
`ShaderNodeBsdfGlass` / `ShaderNodeBsdfRefraction`):

| Blender | Dispersion socket on Principled / Glass / Refraction |
|---------|------------------------------------------------------|
| 4.3.2   | none                                                 |
| 4.5.0   | none                                                 |
| 5.1.0   | none                                                 |
| 5.2.0   | none                                                 |

Dispersion is unmerged upstream WIP (PR #162041). The engine core is still built
and verified via native dispersion params; the addon gets a forward-compatible
`put_float` probe (`'Dispersion Scale'` / `'Dispersion Abbe Number'`, single
`'Dispersion'` alias) that is a no-op today and live the day the PR ships.
(Coordinator-approved Option A, 2026-08-12.)

## In-code citations

- `plugins/materials/principled.cpp` — `cauchyAB()` cites PR #162041 +
  OpenPBR v1.1.1 Eqs. 55/56.
- `include/astroray/gpu_dispersion.cuh` — `gpu_cauchy_ior()` cites the same.
