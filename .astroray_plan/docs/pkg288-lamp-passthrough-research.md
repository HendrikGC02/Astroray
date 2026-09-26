# pkg288 — lamp hit continuation (research note)

**Source:** Cycles `intern/cycles/kernel/integrator/shade_light.h`
`integrator_shade_light` (Apache-2.0): after `film_write_direct_light`-style
accumulation of the MIS-weighted lamp emission, the kernel sets
`ray.tmin = intersection_t_offset(isect.t)` and returns to
`intersect_closest`. Bounce, throughput and MIS state are not touched; the lamp
is not a path vertex. `lights_intersect` skips the lamp just hit
(`last_prim == lamp`).

**Astroray mapping.** Area lamps are one-sided planes and the sun is a
direction at t = 1e30, so each lamp is hit at most once per ray. Re-querying
`intersectDedicated` from the same origin with `tMin = t_lamp` (strict
`t <= tMin` reject) is the exact equivalent of Cycles' offset + self-skip, with
no origin shift. Cap: 4 lamps per segment (CPU and GPU).

**Media.** The world-fog free flight no longer stops at lamps. The lamp term is
estimated deterministically as `throughput · Tr(t_lamp) · Le · w_B`, and the
free flight estimates in-scatter and surface terms over `[0, t_surface)`; the
sum is unbiased (split of the RTE line integral). Grid media keep their
pre-pkg288 order (lamps after the delta-tracking flight to the surface).

**Measured (CPU, 2026-09-27):** two collinear area lamps: NEE on/off agree to
0.4 % (was 8 % in B); engine frame mean 0.998-1.002 of Cycles 5.2.
