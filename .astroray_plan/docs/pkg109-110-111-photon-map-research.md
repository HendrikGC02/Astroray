# pkg109 / pkg110 / pkg111 — general-caustics photon-map research (2026-05-29)

Research notes for the general-caustics chain (replaces the prism-specific 2D grid
in `light_tracer_caustic.cpp` with a world-space photon map). Satisfies CLAUDE.md
§6: paper + license-compatible reference impl cited before code; the C++ cites
file:line back to these sources.

## Papers

- **Jensen, "Global Illumination using Photon Maps", EGWR 1996**, Rendering
  Techniques '96 pp. 21–30, DOI `10.1007/978-3-7091-7484-5_3`. The photon map:
  balanced kd-tree photon store + k-NN density-estimate radiance.
- **Jensen, "A Practical Guide to Global Illumination using Photon Maps",
  SIGGRAPH 2000 Course 8** (https://graphics.stanford.edu/courses/cs348b-00/course8.pdf).
  The implementable reference: §2.1–2.2 + Fig. 7 (`balance()` — balanced kd-tree),
  §3.1 Eq. 8 (radiance estimate), §3.4 + Fig. 10 (`locate_photons` k-NN query),
  §3.2 cone/Gaussian filters.
- **Jensen, "Realistic Image Synthesis Using Photon Mapping", AK Peters 2001** —
  book treatment (same equation family).
- **Bentley 1975, CACM 18(9):509–517** — original kd-tree (cited by Jensen §2.1).
- **Wilkie et al. 2014, "Hero Wavelength Spectral Sampling", CGF 33(4)**, DOI
  `10.1111/cgf.12419` — hero-λ for dispersion (relevant to pkg110's per-λ photons).

## Key formulas (reproduced)

Surface radiance estimate (Jensen 2000 §3.1 Eq. 8):

    L_r(x, ω) ≈ (1 / (π r²)) · Σ_{p=1}^{N} f_r(x, ω_p, ω) · ΔΦ_p

- `N` nearest photons around `x`; `r` = distance to the **farthest** of the N
  (radius of the enclosing sphere); `π r²` is the disk-area density footprint.
- pkg109 keeps it as an **irradiance** estimate `E(x) = (1/(π r²)) Σ ΔΦ_p` (the
  receiver's Lambertian BRDF `albedo/π` is applied by the caller, matching the
  pre-existing grid semantics). pkg111 will fold `f_r` per-photon for arbitrary
  BSDFs.

Balanced kd-tree (Jensen 2000 §2.2 Fig. 7): bounding box → split axis = axis of
**largest extent** → **median** split (nth_element / quickselect) → recurse. O(N
log N). Stored implicitly (no child pointers); split axis kept per node.

k-NN locate (Jensen 2000 §3.4 Fig. 10): bounded **max-heap** of N photons keyed
by squared distance; recurse near side first; visit far side only when
`δ² < d²` (signed plane distance vs current search radius²); once the heap is
full, `d²` = heap-root (farthest kept) squared distance. Squared distances
throughout (no per-test sqrt).

## Reference implementation (license-clean)

- **pbrt-v4** (`mmp/pbrt-v4`, SPDX **Apache-2.0**) and **pbrt-v3** (SPDX
  **BSD-2-Clause**) — both permissive, MIT-compatible to mirror. pbrt's SPPM is
  **visible-point / uniform-hash-grid** centric (`src/pbrt/cpu/integrators.cpp`
  SPPM ~L2763–3229), **not** a stored photon kd-tree, so we do **not** copy its
  data structure. We mirror two things from it:
  - the **disk-area density factor** `L = τ / (np · π · r²)` (v4 `integrators.cpp:3229`),
    which is exactly Jensen Eq. 8 with `np` = photons emitted;
  - the **non-progressive simplification**: fixed radius, one pass, drop the
    radius-reduction (`γ`, `rNew = r√…`) and atomics (single-threaded build in
    `beginFrame`).
- The **kd-tree build + k-NN query** mirror **Jensen 2000 Fig. 7 / Fig. 10**
  directly (the canonical published pseudocode; pbrt ships no kd-tree photon map).

## Astroray reuse points (audited, file:line)

| What | Where | Note |
|---|---|---|
| `XYZ` struct | `include/astroray/spectrum.h:29` | photon power carry (hero-λ CIE) |
| `cieCmf1964_10deg(λ)` | `spectrum.h:33` | per-λ CIE deposit weight |
| `SampledWavelengths::sampleUniform` | `spectrum.h:101` | (pkg110 photon λ) |
| `LightList::sample` | `raytracer.h:1264` | (pkg110 photon emission) |
| `getDedicatedLights` | `raytracer.h:1278` | (pkg110 light enumeration) |
| `pathTraceSpectral` + `SMSHook` | `raytracer.h:2319` / `2314` | (pkg111 default-path gather hook) |
| `gatherTriangleCasters` / `CausticTri` | `manifold/mesh_attempt.h:35` / `mesh_caustic.h:23` | prism casters (kept for pkg109 emission) |
| `rayTriHit` | `mesh_caustic.h:29` | caster ray hit |
| BVH `hit` / `HitRecord{point,normal,material,hitObject}` | `raytracer.h:1172` / `406-418` | gather receiver hit |
| `Material::getAlbedo` / `isEmissive` / `evalSpectral` | `raytracer.h:515/512/565` | receiver shading |
| `Integrator` virtuals + `ASTRORAY_REGISTER_INTEGRATOR` | `astroray/integrator.h` / `register.h:50` | integrator contract |
| pybind class pattern | `module/blender_module.cpp:1891` | test binding |

## Integration risks (carried forward)

- **MinGW large-struct-by-value** (memory `mingw_large_struct_byval`): `Photon`
  is 40 B (> 32) → pass by `const Photon&`, never by value in hot paths.
- **beginFrame is single-threaded** before the tile-parallel loop → build the
  photon map there; the immutable map is read by tile workers (no atomics needed).
- **Stale .pyd** (memory `stale_pyd_locations`): rebuild + check `astroray.__file__`
  before trusting any render.
- pkg110/111: hero-λ carry (secondary wavelengths terminated on refraction,
  `dielectric.cpp`), `RGBIlluminantSpectrum` vs `RGBAlbedoSpectrum`, GR object
  bypass in gather, infinite-light visibility epsilon — see audit.

## Scope split

- **pkg109 (this):** storage-only. Swap the 2D grid in `light_tracer_caustic.cpp`
  for `astroray::photon::PhotonMap` (kd-tree); k-NN irradiance gather replaces the
  bilinear grid gather. Keep the 2-face prism emission. Regression: the
  `prism-bk7-collimated` band still passes (hue_spread ≥ 0.7, bright_coverage ≥ 0.5).
- **pkg110:** BSDF-driven photon emission/bounce (any glass/TIR/multi-bounce).
- **pkg111:** k-NN gather at any diffuse receiver, wired into the default `path_tracer`.

## Validation

`scripts/prototypes/pkg109_photon_map_prototype.py` (float64): kd-tree k-NN set ==
brute force (0 mismatch / 300 queries, radius err 0); density estimate converges
to the true areal density (1.6% rel-err at 40k photons). The C++ kd-tree is
validated against the same brute-force oracle in `tests/test_photon_map.py` via a
pybind test binding.
