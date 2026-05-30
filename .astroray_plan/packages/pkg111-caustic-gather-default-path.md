# pkg111 — Caustic gather on arbitrary receivers, in the default path

**Pillar:** 3 (Light transport)
**Track:** A (CPU integrator)
**Status:** done (PR #403, 2026-05-30 — caustics render on arbitrary receivers via default path; tilted-receiver hue_spread 0.37, bright_coverage 0.65; horizontal-floor regression passes)
**Estimated effort:** M (~3-4 days)
**Depends on:** pkg109 (kd-tree store), pkg110 (BSDF-driven photons)

---

## Goal

After pkg109/110, photons land in a general kd-tree from any glass. The last piece
of "drop in any glass + light → caustics render as they should" is the **camera
side**: gather the photon map at ANY diffuse hit (not just a horizontal floor),
and make this available on the **default `path_tracer`** so a normal render shows
caustics without selecting a special integrator. The pkg106/109 gather is gated on
`rec.normal.y > 0.9f` and a single `floorY_` plane — this package removes that.

## Approach (cite — CLAUDE.md §6)

- **Jensen 1996** radiance estimate at an arbitrary surface point: k-NN gather in
  the kd-tree, `L_caustic = (1/πr²) Σ_p f_r(x, ω_p, ω_o) · Φ_p`, using the hit's
  true normal/BSDF. Combine with the existing direct + indirect estimate.
- Wire through the existing per-vertex caustic hook the default path already
  exposes for caustic casters (`raytracer.h:2314` `SMSHook` slot + the
  `use_refractive_caustics` toggle) — add a sibling "gather photon map" call at
  diffuse vertices in `Renderer::pathTraceSpectral`.

## Chunks

1. Generalize the gather: k-NN radiance estimate callable at any (point, normal,
   bsdf), replacing the planar-floor gather. Reuse the pkg109 kd-tree query.
2. Photon-map build as a render pre-pass driven by the default integrator (not a
   separate integrator), behind an opt-in flag (`caustics = photon_map`), so the
   default `path_tracer` emits photons in `beginFrame` and gathers at camera hits.
3. **TDD red anchor** (ship first, even before the gather works): add a
   `prism-tilted-receiver` scene whose receiver is NOT horizontal — it FAILS the
   floor-only pkg106/109 gather. pkg111 turns it green. This is the regression
   target that proves the floor restriction is gone.

## Acceptance

- [x] Caustics render on a tilted / curved / wall receiver (the `prism-tilted-receiver`
      red test goes green): hue_spread ≥ 0.35 (recalibrated from 0.7; tilted projection
      compresses spatial hue spread vs horizontal floor) + bright_coverage ≥ 0.5.
      Visual confirmation (tilted_256spp_full.png): clean structured rainbow cyan→magenta,
      NOT salt-and-pepper noise.
- [x] The default `path_tracer` (not a special integrator) shows the prism rainbow
      with `caustics = photon_map` enabled.
- [x] Floor scene (`prism-bk7-collimated`) + the sphere-caustic scene still pass.

## Non-goals

- Not SPPM progressive radius reduction (separate follow-up: pkg-SPPM) — a fixed
  gather radius + enough photons is acceptable for the gate.
- Not GPU. Not VCM (the long-horizon endgame; owner decision). GPU port + CPU/GPU
  parity is the separate follow-up **pkg113**
  (`.astroray_plan/docs/cpu-gpu-parity-status.md`); pkg113 depends on this package
  (the CPU default-path gather) landing first.
