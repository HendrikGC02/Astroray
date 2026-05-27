# prism-bk7-collimated

**Vision:** A BK7 dispersive sphere lit by a white area emitter, casting a
**visible chromatic caustic** (rainbow ring) onto a white floor. This is the
canonical "yes, Astroray actually does spectral dispersion" smoke test —
when this image stops showing colored speckles around the sphere's base, a
regression has hit either the spectral pipeline, the SMS Newton iteration,
or the per-wavelength IOR plumbing.

**Why a sphere, not a triangular prism:** the goal is *visible chromatic
dispersion* as a regression target. A glass sphere with the
`sms_caustic_path_tracer` integrator + `spectral_newton=1` produces a
clean chromatic caustic at 1024 spp in ~30 s on CPU. A triangular prism
geometry needs additional SMS chain support that doesn't have a tested
acceptance path yet (deferred to a follow-up). The *physics being measured*
(per-wavelength Newton residual on a dispersive caster) is identical.

**Acceptance:** `hue_spread` in the floor ROI must remain above 0.55
(measured 0.80 at bless time). When this drops, look at:
1. `spectral_newton` integrator param still being set to 1?
2. `sellmeier_preset` material param still wired through to `gpu_dispersion.cuh`?
3. Caustic chain depth (`caustic_chain_iters` ≥ 3)?
4. The light source still bright enough that the caustic isn't drowned in noise?

**Reference render notes:**
- 384×256, 1024 spp, integrator `sms_caustic_path_tracer`.
- ~32 s CPU walltime on the bless machine (RTX box, but CPU rendering — GPU is hero-wavelength only and would not show chromatic spread).
- Blessed at commit b02b161.
