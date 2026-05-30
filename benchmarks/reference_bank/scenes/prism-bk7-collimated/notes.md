# prism-bk7-collimated

**Vision:** A triangulated equilateral BK7 prism, lit by a collimated "sun"
(distant directional light), throwing a **clean continuous rainbow caustic**
(red→violet band) onto a white floor. This is the canonical "yes, Astroray does
spectral dispersion through a real prism" reference — when the band loses its hue
spread or breaks into chromatic speckle, a regression has hit the spectral
pipeline, the per-wavelength Sellmeier IOR plumbing, or the light-tracer.

**Why a forward light-tracer (pkg106 finish, 2026-05-29):** the prism rainbow was
originally scoped for the camera-side SMS/MNEE integrator. The full MNEE machinery
was implemented and unit-tested (analytic transfer-matrix geometry term — both the
positional and collimated branches — plus a caster-aimed seed; see
`include/astroray/manifold/` and `tests/test_mnee_*.py`), and it does localize a
dispersive caustic. But a flat prism does not focus, so camera-side specular
connection is a near-delta whose Newton basin is spatially chaotic → salt-and-
pepper chromatic noise that does NOT clean up with samples. A prism rainbow is a
forward light-transport phenomenon, so this scene uses the `light_tracer_caustic`
integrator (Arvo 1986 / Jensen 1996): wavelengths are traced FROM the sun through
the prism and deposited on the floor → a smooth spectrum, no specular-connection
noise. See `.astroray_plan/docs/pkg106-forward-lighttracing-research.md`.

**Acceptance (pkg106):**
1. `hue_spread` ≥ 0.7 in the band ROI (measured 0.754) — full red→violet dispersion.
2. `bright_coverage` ≥ 0.5 in the band ROI (measured 0.88) — the CONTINUITY
   discriminator: salt-and-pepper noise also scores high `hue_spread`, but a real
   continuous band fills its ROI while speckle collapses this well below 0.5.

When the gate trips, look at:
1. `light_tracer_caustic` integrator selected, with `photon_count` high enough?
2. `sellmeier_preset = "bk7"` still wired through `iorAt(λ)`?
3. The two prism faces still flagged `set_object_caustic_caster(True)`?
4. The collimated `add_sun_light_dedicated` still present (the light-tracer reads
   its direction)?

**Reference render notes:**
- 384×288, 64 camera spp, 3M photons, integrator `light_tracer_caustic`.
- ~1 s CPU walltime (the caustic is baked in `beginFrame`; the camera pass is
  near-deterministic, so the gate is stable — no MC flake).
- Re-blessed 2026-05-29 (pkg106 finish).
