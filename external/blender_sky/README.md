# external/blender_sky — vendored Blender sky models (#799 Phase 2)

Engine-side spectral Nishita sky for Astroray. Vendored from
[blender/blender](https://github.com/blender/blender) `intern/sky/` at `main`
(fetched 2026-09-13 via the GitHub contents API; SPDX headers verified by hand
before vendoring).

## Files and licences

| File | Origin | SPDX | Status |
|------|--------|------|--------|
| `sky_single_scattering.cpp` | `intern/sky/source/sky_single_scattering.cpp` | **Apache-2.0** (Blender Authors 2011-2020) | Vendored verbatim + a clearly-marked Astroray addition at the end (spectral/XYZ per-direction query). |
| `sky_multiple_scattering.cpp` | `intern/sky/source/sky_multiple_scattering.cpp` | **MIT** (Fernando García Liñán 2022 + Blender Authors) | Vendored verbatim + a clearly-marked Astroray addition at the end (per-direction eval context). |
| `sky_math.h` | — (reimplemented) | Apache-2.0 (Astroray) | **Clean-room.** Blender's `intern/sky/source/sky_math.h` is **GPL-2.0-or-later** and was NOT copied. This is an independent implementation of the trivial float2/float3/float4 helpers + a textbook ray-sphere intersection the two sources need. |
| `sky_nishita.h` | — (reimplemented) | Apache-2.0 (Astroray) | **Clean-room.** Blender's `intern/sky/include/sky_nishita.h` is **GPL-2.0-or-later** and was NOT copied. These are plain function declarations (an interface). |

## Correction to earlier Astroray notes

`blender_addon/sky_bake.py` and the earlier #799 research note claimed the
Cycles/Blender sky implementations were GPL and therefore unusable. That is
only true of `sky_nishita.h` and `sky_math.h` (GPL-2.0-or-later). The two model
**sources** are Apache-2.0 (`sky_single_scattering.cpp`) and MIT
(`sky_multiple_scattering.cpp`), and `intern/cycles/kernel/svm/sky.h` (the
texture-sampling/sun-disc logic) is Apache-2.0. Those are vendorable; this
directory does so. See
`.astroray_plan/docs/799-sky-absolute-exposure-sun-disc-research.md`.

Precedent for vendoring Apache-licensed Cycles code with its header:
`external/cycles_light_tree/`.

## Astroray additions (not upstream)

Both `.cpp` keep the upstream code unchanged and append a small, delimited
block used by `src/world/nishita_sky.cpp`:
- `SKY_single_scattering_spectrum` / `SKY_single_scattering_eval_xyz` — the
  21-wavelength spectrum / CIE XYZ for one Z-up view direction (keeps the
  per-wavelength intermediate reachable for a future spectral integrator).
- `SKY_multiple_scattering_{create,eval_xyz,destroy}` — a context that
  precomputes the transmittance LUT once and evaluates radiance per direction.

These only call existing (static) upstream routines; no model maths changed.
