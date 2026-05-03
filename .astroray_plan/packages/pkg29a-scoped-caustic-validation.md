# pkg29a — Scoped Caustic Validation for Spectral Optics

**Pillar:** 2 / 3 bridge follow-up  
**Track:** A  
**Status:** design  
**Estimated effort:** 2-4 sessions  
**Depends on:** pkg29, pkg31, issue #142, issue #146  
**GitHub:** #145

---

## Goal

Make prism, glass, and narrowband-emitter caustics measurable and visible
without turning pkg29 into a broad "solve all specular transport" project.

pkg29 proves wavelength-dependent refraction exists. pkg29a should prove that
the renderer can track progress toward useful caustics with repeatable scenes,
metrics, and one narrowly-scoped transport improvement.

---

## Scope

### Validation scenes

- **Prism-to-screen:** triangular BK7/SF11 prism, narrow slit or line emitter,
  matte receiving screen, saved RGB render, and red/blue centroid spread metric.
- **Glass caustic:** clear sphere or lens over a matte receiver with a compact
  emitter, saved render, and receiver-region energy/concentration metric.
- **Line emitter / laser proxy:** narrowband `line_emitter` source through
  either thin glass or prism glass, saved render, and wavelength-channel energy
  sanity checks.

### Transport strategy

Implement one small, inspectable improvement first:

- keep `path_tracer` as the reference/default;
- add an opt-in caustic validation mode or integrator parameter that only
  changes specular-chain handling after a delta transmission/reflection event;
- record convergence stats against the unchanged reference scene;
- reject the change if it improves screenshots while breaking spectral tests or
  energy sanity checks.

Good first candidates:

- specular-chain light/screen connection for one-bounce refractive caustics;
- caustic-focused next-event retry after delta BSDF events;
- photon/beam prototype as a separate later package if the small connection
  strategy is not enough.

---

## Acceptance Criteria

- [ ] Issue #145 has this scoped design linked and no longer describes an
      unbounded caustics rewrite.
- [ ] Saved diagnostic renders exist for prism-to-screen, glass caustic, and
      narrowband emitter scenes.
- [ ] Quantitative stats are emitted as JSON/CSV: render time, mean luminance,
      receiver energy, high-percentile luminance, and red/blue centroid spread
      where applicable.
- [ ] A focused pytest suite validates finite renders and checks that the
      caustic mode does not regress pkg29/pkg31 spectral behavior.
- [ ] `path_tracer` remains available as the CPU reference and default.

---

## Non-goals

- Do not attempt full bidirectional path tracing, MLT, photon mapping, or
  manifold next-event estimation in this package.
- Do not make caustic transport a default until diagnostics show it improves
  equal-time quality without bias surprises.
- Do not require CUDA; GPU acceleration is welcome for high-sample diagnostic
  renders but cannot be the only validation path.
