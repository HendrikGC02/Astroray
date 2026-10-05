# GR geodesic / scene intersection research (#1063)

Problem: the geodesic march inside a BlackHole influence region never tested the
scene, so geometry inside r_max = 1.05 x influence radius was invisible.

## Source

- E. Groeller, "Nonlinear ray tracing: visualizing strange worlds", The Visual
  Computer 11(5):263-274, 1995. A curved ray is stored as a polyline of short
  straight segments (iterative representation); each segment is intersected with
  the scene by the ordinary linear test, the first hit along the polyline wins.
  Paper page: https://www.cg.tuwien.ac.at/research/publications/1995/groeller-1995-non
- Relativistic-rendering follow-ups (Weiskopf et al. 2004, as cited by the
  2026-10-06 architect plan; not re-verified here) use the same polyline idea.
- GYOTO (GPL-2+) uses the same per-step scene test for opaque objects. Concept
  only; no code read or copied.

## Mapping onto Astroray

- Each accepted DP45 step (BL state a -> b) becomes the world-space chord A->B
  (`BlackHole::blToWorld`, the inverse of `buildInitialState`'s mapping).
- The scene BVH (`Hittable::hit`) is queried on [0, |AB|]; GR objects (the
  influence sphere itself lives in the BVH) are stepped over; the first real
  surface ends the march (`IntegrationResult::stopped`) and is returned as a
  surface hit whose incoming direction is the chord tangent.
- The escaping step ends its chord at the #1061 exit point (the back-projected
  r_max crossing of the exit line), i.e. exactly where the continuation ray
  starts: the piecewise path is connected, no seam or overlap at r_max.
- Disk crossings recorded before the stop are kept; a hit does not run past
  capture (a captured step returns no hit).

## Limits (documented, not fixed)

- Chord sag: a long step with large angular travel under-approximates the
  curved path (error ~ R dphi^2 / 8). RK45 steps near the photon sphere are
  short; measured step angles are in the PR.
- Straight shadow rays from a surface hit inside the region ignore the bending.
- The volumetric (ADAF/jet) straight-line integral is not truncated at a hit.

## Review fixes (PR #1080)

- Redshift of the hit's emission: I_lambda * lambda^5 is invariant along a null
  geodesic (Liouville; the invariant the disk transfer already uses), so
  L_obs(lambda) = g^5 L_emit(g lambda), bolometric g^4. g = sqrt(-g_tt) of a
  static emitter (Schwarzschild 1-2M/r, Kerr 1-2Mr/Sigma), divided by the same
  factor at r_max: the flat scene outside is the reference observer, so the
  region boundary has no brightness seam (a plain infinity reference would dim
  a sphere straddling r_max by ~23% at r_obs_M = 20 just inside the edge).
  **Superseded (owner decision 2026-10-06):** the reference is an observer at
  infinity, g = sqrt(-g_tt), the same as the accretion disk
  (`NovikovThorneDisk::redshiftFactor`, Cunningham 1975). The owner accepts the
  resulting ~23% (r_obs_M = 20) brightness step at r_max: in-region emission is
  dimmed and the part of a straddling object beyond r_max is not. Test:
  `test_scene_hit_emission_is_gravitationally_redshifted` (green channel,
  g^4 = (1-2M/r)^2, tol 5%). Evidence: `astra_run/batch-i/i7/`.
  Emission only; reflected light is #1082, straight NEE rays #1081.
- Volumetric straight-line march ends at the hit depth along the incoming ray;
  its transmittance multiplies path throughput.
- A disk crossing past the hit within the same step is dropped (hit fraction
  from the chord vs the crossing's theta-linear fraction).
- Per GR object the Renderer caches a BVH over the non-GR primitives meeting
  the r_max ball (none: no geodesic scene test, no overhead).
