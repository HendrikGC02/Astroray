# PBR advances follow-up pass — spectral MIS, multiscatter GGX, Cycles parity (2026-07-18)

Companion to `2026-07-pbr-advances-research.md`, covering that sweep's three
coverage gaps. **Verification caveat:** the adversarial-verify phase of this
run died on session limits (all 25 verifier panels errored), so most claims
below are *extracted from primary sources but not 3-vote verified*. The two
load-bearing claims for axis B were **verified directly by the lead session**
via first-hand fetches (marked ✅). Re-verify anything else before citing it
in code.

## Axis B — multiscatter microfacet energy compensation: ANSWERED

This axis now has an actionable, license-clean answer:

- ✅ **VERIFIED (direct fetch of github.com/blender/blender commit
  `888bdc1419a2cd99284060a64d1df0c4397d3ac5`):** Cycles REMOVED its
  Heitz-2016-style stochastic multiscatter GGX
  (`bsdf_microfacet_multi.h` + `_impl.h`, deleted) and replaced it with
  **albedo scaling of the single-scatter GGX lobe via precomputed LUTs**,
  citing **Turquin** (blog.selfshadow.com/publications/turquin/ms_comp_final.pdf)
  and the Imageworks second-lobe alternative. Commit rationale (quoted):
  "having the exact correct directional distribution is not that important as
  long as the overall albedo is correct and we a) don't get the darkening
  effect and b) do get the saturation effect at higher roughnesses."
  New table generator: `intern/cycles/app/cycles_precompute.cpp`;
  tables in `intern/cycles/scene/shader.tables`. (PR blender/blender#107958,
  2023 — i.e. Cycles 4.x-era Principled energy conservation IS Turquin-style
  albedo scaling.)
- ✅ **VERIFIED (direct fetch):** **adobe/openpbr-bsdf is Apache-2.0** and is
  Adobe's reference implementation of OpenPBR 1.1 with **7 precomputed
  multiscatter energy LUTs** (ideal/opaque dielectrics, ideal metals) + an LTC
  fuzz table, portable across **C++/GLSL/CUDA/MSL/Slang** (LUTs embeddable as
  arrays or GPU textures). A directly portable CUDA-compatible reference.
- Unverified-extracted (Turquin paper, blog.selfshadow.com PDF): at GGX
  roughness α=1, single-scatter conductors lose ~60% energy (>90% for
  longer-tailed GTR/STD); Turquin models the missing term as a scaled copy of
  the single-scatter lobe (ρ_ms = F_ms·k_ms·ρ_ss); Heitz 2016 stochastic
  evaluation measured 7–15× slower in Mitsuba for minimal visual difference.
- Unverified-extracted (OpenPBR spec, both html spec + arXiv:2512.23696):
  OpenPBR does NOT mandate one compensation scheme — it cites Heitz 2016
  (accurate/stochastic), Kulla-Conty 2017 (compensation lobe), Turquin 2019
  (albedo scaling, trades reciprocity for energy preservation) as valid
  implementer choices.

**Recommendation:** port **Turquin-style albedo-scaling LUT compensation**,
using `adobe/openpbr-bsdf` (Apache-2.0) as the primary code reference and
post-#107958 Cycles (`cycles_precompute.cpp` + lookup application sites) as
the production cross-check. This composes with Astroray's existing LUT
infrastructure and the pkg118 lesson (energy bugs hide in albedo LUT paths);
note pkg118 fixed *transmission* energy — this axis is *reflection*
multiscatter at high roughness. File as a future package after pkg55 Phase C.

## Axis A — spectral sampling / hero wavelength: PARTIAL

Unverified-extracted claims (consistent, from HAL/inria fluorescence-HWSS
paper + pbrt-v4 repo/user guide):
- HWSS (Wilkie et al. 2014) mechanism: ONE hero wavelength drives path
  sampling decisions; ~4 stratified wavelengths ride the same path;
  per-wavelength MIS weights computed across all rotations that could have
  been hero. The stratification + MIS weighting is what kills color noise —
  not merely carrying several wavelengths.
- pbrt-v4 (Apache-2.0) moved to point-sampled spectra everywhere (RGB only at
  scene input/image output) — the canonical permissive implementation of the
  HWSS-style architecture. pbrt-v3's 60-band `CoefficientSpectrum<60>` is the
  older dense-band design.
- No 2023–2026 successor to HWSS surfaced in either pass. The open design
  question for Astroray stands: our hero-LESS N-wavelength design carries all
  wavelengths through one path (like a dense-band scheme over the sampled
  set); whether adding hero-rotation MIS weights would measurably cut chroma
  variance on dispersive paths (where wavelengths decorrelate) is untested.
  **Cheap experiment:** A/B chroma-variance on the prism/bk7 refbank scenes vs
  equal-cost more-paths-fewer-wavelengths configurations. Do this BEFORE any
  HWSS port — the win may not exist for our design.

## Axis C — Cycles 4.x/5.x feature specifics: STILL OPEN

This axis again returned little (only the thin-film pointer: OpenPBR's
recommended thin-film model is **Belcour-Barla**, matching the pass-1
finding). The right next step is not more web search — it is a direct
**Blender source review** (fetch release notes + kernel files from
projects.blender.org / github mirror, as pkg115 did): Sobol-Burley blue-noise
sampling, light linking, light tree improvements, Principled v2 sheen (Zeltner
fuzz), ray portals, volume null-collision changes. Blender is Apache-2.0
throughout, so it is all license-clean; the work is locating the exact kernel
files and sizing ports.

## Verification ledger

- Pass-2 stats: 5 angles, 21 sources fetched, 25 claims extracted, verifier
  phase 0/75 completed (session-limit infrastructure failure — NOT refutation).
- Lead-session direct verifications: Blender commit 888bdc1 (multiscatter
  removal + Turquin adoption), adobe/openpbr-bsdf license + LUT contents.
