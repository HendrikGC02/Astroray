# #842 — every bounded medium on a ray segment (sequential + overlapping)

**Defect.** CPU `pathTraceSpectral` and the GPU `intersectPathSlotT<…,HasGridVolume>`
tracked only the medium whose AABB the segment entered first; a second medium
further along (fire behind smoke) was skipped. Shadow-ray transmittance already
multiplied every medium (unbiased: independent ratio-tracking estimators of each
factor of a product).

**References.**
- Cycles volume stack (`kernel/integrator/volume_stack.h`, `shade_volume.h`
  `volume_shader_sample`, Apache-2.0): a point inside several volumes evaluates the
  SUM of their closures (σ_s, σ_a, emission add; the phase is the σ_s-weighted mix).
- Novák, Georgiev, Hanika, Křivánek, Jarosz 2018, *Monte Carlo Methods for
  Volumetric Light Transport Simulation* (EG STAR) §3–4: null-collision tracking
  with a combined majorant σ̄ = Σ σ̄_k; each tentative collision picks a type with
  probability σ_type/σ̄. Choosing "scatter in medium k" as its own type samples the
  mixed phase exactly.
- pbrt-v4 `VolPathIntegrator::Li` (Apache-2.0): the hero-wavelength spectral-MIS
  weight update (beta, r_u *= σ_type/σ_type[λ0]) already used by pkg270.

**Algorithm.** Sweep [tMin, surfaceT] by the media's AABB boundaries. A piece
covered by one medium runs the existing `spectralTrack` / `gpu_gridVolumeTrack`
(single-medium scenes: same interval, same draws — byte-identical). A piece covered
by several runs the summed-majorant flight above. The exponential restarts at each
boundary (memoryless — exact). The GPU carries one draw counter across pieces so
no counter-based draw repeats within a flight. At most 8 media per piece (the GPU
`G_WF_MAX_GRID_MEDIA`).

**Not in scope.** #833 mesh-shaped bounds: the AABB sweep has no inside-mesh test;
mesh media stay lowered to their AABB with the existing declared approximation.
