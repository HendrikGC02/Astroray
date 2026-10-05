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
