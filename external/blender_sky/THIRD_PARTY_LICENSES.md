# Third-Party Licenses — Blender Sky Models (#799 Phase 2)

Engine-side spectral Nishita sky. Sources vendored from
https://github.com/blender/blender (`intern/sky/`, `main` branch, fetched
2026-09-13 via the GitHub contents API). SPDX headers were verified by hand
before vendoring.

## 1. Single-scattering (classic Nishita)

**License:** Apache-2.0
**Copyright:** 2011-2020 Blender Authors
**File:** `intern/sky/source/sky_single_scattering.cpp` →
`external/blender_sky/sky_single_scattering.cpp`

Preserves the original `SPDX-FileCopyrightText: 2011-2020 Blender Authors` /
`SPDX-License-Identifier: Apache-2.0` header. An Astroray addition (spectral /
XYZ per-direction query) is appended in a clearly-delimited block and calls only
existing upstream routines.

## 2. Multiple-scattering (spectral 4-wavelength fit)

**License:** MIT
**Copyright:** 2022 Fernando García Liñán; 2011-2025 Blender Authors
**File:** `intern/sky/source/sky_multiple_scattering.cpp` →
`external/blender_sky/sky_multiple_scattering.cpp`

Preserves the original MIT header. Based on García Liñán's Master's thesis
(https://fgarlin.com/posts/2024-12-06-spectral_sky/) and Hillaire's "Physically
Based Sky, Atmosphere and Cloud Rendering in Frostbite". An Astroray addition
(per-direction eval context) is appended in a clearly-delimited block.

## 3. Clean-room headers (NOT copied from Blender)

Blender's `intern/sky/source/sky_math.h` and `intern/sky/include/sky_nishita.h`
are **GPL-2.0-or-later** and were therefore NOT copied. `external/blender_sky/
sky_math.h` and `sky_nishita.h` are independent Astroray reimplementations
(Apache-2.0):

- `sky_math.h` — trivial component-wise float2/float3/float4 arithmetic,
  dot/length, clamp/saturate/mix, a textbook ray-sphere intersection, and a
  serial parallel_for. Only the public symbol names (an interface) match
  upstream so the vendored `.cpp` compile unmodified.
- `sky_nishita.h` — plain C-style function declarations (an interface).

## License Compatibility

Apache-2.0 and MIT are both compatible with Astroray's MIT license
(CLAUDE.md §6). Original copyright notices and licence headers are preserved in
the vendored `.cpp`. No GPL code is copied into Astroray.
