# pkg228 — Forward light-tracer rainbow (internal-reflection branch for spheres/droplets)

**Pillar:** 3
**Track:** A
**Status:** superseded — PROPOSED but never owner-approved; the internal-reflection rainbow is covered by pkg227 Track S (Phase 2a landed) (2026-09-07 backlog triage)
**Estimated effort:** M
**Depends on:** pkg227

---

## Goal

Before: the forward light tracer's general deterministic BVH refraction loop
transmits through every dielectric hit and reflects only on TIR, so a water
sphere renders its lens caustic but the forward tracer physically cannot render
a rainbow — the primary bow needs one partial internal reflection and the
secondary bow needs two. After: at a dielectric hit the loop also spawns a
Fresnel-reflected internal photon carrying `R·Φ`, continued up to
`caustic_internal_reflections` bounces (default 0 keeps every existing scene
byte-identical; 2 covers the primary k=1 and secondary k=2 bows), and a
droplet-curtain showcase scene with a seed-pinned render gate demonstrates a
continuous primary bow at 42° from the antisolar point.

---

## Context

This package serves Pillar 3 (light transport / caustics) on Track A
(physically-based forward transport; render-level caustic gates). The forward
tracer physically cannot render a rainbow today (see Evidence) — that is the
gap this package closes. Estimated effort M: one bounded internal-reflection
branch in an existing general refraction loop + a showcase scene + a render
gate; the risk is photon budget / deposit balance, not new math. It depends on
nothing in pkg227 (independent path). It shares no code with the SMS solver —
this is the *showcase/publication* path; pkg227-S2a stays the camera-side
physically-exact path for research renders.

---

## Evidence

- `plugins/integrators/light_tracer_caustic.cpp` already traces per-wavelength
  photons from the collimated sun through caster geometry and deposits CIE flux
  into a world-space photon map (pkg106/109/110).
- Its **general deterministic BVH refraction loop** (the non-flat-prism path,
  ~line 108–130) already "makes a glass sphere focus a caustic" — but at each
  transmissive hit it **refracts through, and only reflects on TIR**:

  ```cpp
  for (int bounce = 0; bounce < maxDepth_; ++bounce) {
      ...
      if (refract(d, nf, eta, dt)) { d = dt; }               // transmit
      else { d = (d - nf*(2*d.dot(nf))).normalized(); }      // reflect ONLY on TIR
  }
  ```

- A water sphere's primary rainbow is: **refract-in → ONE internal reflection
  at the back face (a partial, ~6% Fresnel reflection — NOT a TIR) →
  refract-out.** A centered ray into a water drop never hits TIR, so the
  current loop always transmits straight through — it produces the **lens
  caustic only, never the bow.** The secondary bow needs **two** internal
  reflections.

---

## Reference

- Arvo, "Backward Ray Tracing", SIGGRAPH 1986 Course Notes (forward light
  particles for caustics) — already used by `light_tracer_caustic`.
- Jensen, "Global Illumination using Photon Maps", EGWR 1996 (diffuse deposit +
  k-NN density estimate).
- Descartes / Newton geometric rainbow theory (deviation stationarity → 42°
  primary / 51° secondary for water); see `tests/test_pkg227_sphere_chain_unit.py`
  for the Descartes oracle already in the tree.

---

## Prerequisites

- [ ] TBD

---

## Specification

### Files to create

None.

### Files to modify

| File | What changes |
|---|---|
| `plugins/integrators/light_tracer_caustic.cpp` | Add the reflected-branch split to the general deterministic BVH refraction loop only (flat-prism 2-face path untouched) and the new `caustic_internal_reflections` integrator param. |
| `scripts/README.md` | Register the droplet-curtain showcase harness (§5b) if reusable; delete if one-off. |

### Key design decisions

#### Bounded internal-reflection sub-path split

At a dielectric hit, in addition to the transmitted photon, spawn a
**Fresnel-reflected internal photon** carrying `R·Φ` flux and continue it up to
`caustic_internal_reflections` bounces (default 2 → covers primary k=1 and
secondary k=2 bows); the transmitted photon carries `(1−R)·Φ` as today. Cap the
split depth so the branching stays bounded (a drop is convex → each internal
reflection has exactly one next face; this is a *linear* chain per spawned
branch, not an exponential tree — spawn at most one reflected branch per surface
hit, gated by a per-branch depth counter). Deposit every branch's exit photon
into the same photon map. This is standard forward caustic transport (Arvo 1986;
Jensen 1996 — already cited in the file header).

#### Physically-honest throughput

Transmit `(1−R)`, reflect `R` (Schlick/dielectric Fresnel, already in
`refract`/the material). The primary bow is intrinsically faint (one ~6%
reflection between two transmissions) — **do not brighten it**; make it visible
by throwing enough photons and letting many drops overlap, the way a real sky
does. A `caustic_boost` display gain already exists for inspection.

#### Scope decisions

- Add the reflected-branch split to the general loop only (leave the flat-prism
  2-face path untouched — it is fleet-blessed for the existing prism showcase).
- New integrator param `caustic_internal_reflections` (int, default **0** so
  every existing scene is byte-identical; set to 2 for droplet showcases). Verify
  the prism rainbow reference is unchanged at the default.
- One showcase scene: a **droplet curtain** (many small water spheres, thin in
  depth/height, wide horizontally) + a diffuse receiver, collimated sun low
  behind camera → a continuous primary bow at 42° from the antisolar point. This
  is the "nicer scene for publication" the owner deferred. Register the harness
  in `scripts/README.md` (§5b) if reusable; delete if one-off.
- **GPU:** `src/gpu/photon_caustic.cu` / `photon_emission.cu` have their own
  forward-photon path — out of scope here (CPU showcase first); note whether the
  GPU photon loop has the same transmit-only limitation for a later GPU package.

---

## Acceptance criteria

A render-level pytest (mirror `tests/test_pkg227_raindrop_bow.py` conventions):
`caustic_internal_reflections=0` vs `=2` on a droplet-curtain scene, seed-pinned:

- [ ] **FIRES:** the internal-reflection branch deposits photon energy the
      transmit-only path lacked.
- [ ] **BANDED at 42°:** the added energy concentrates in the angular band the
      Descartes construction predicts (deviation ≈138° for water n=1.333 → 42°
      antisolar), not uniformly — a real bow arc, measured as a strong band
      concentration in the antisolar annulus (target: markedly higher than the
      0.18 the camera-side 40-drop SMS scene reached).
- [ ] **CHROMATIC + ORDERED:** red outer, violet inner (primary bow), both hues
      present — the rainbow signature, with the correct radial colour order.
- [ ] **NO REGRESSION:** the existing prism rainbow reference render is
      byte-identical at the default (`caustic_internal_reflections=0`).

---

## Non-goals

- Not touching pkg227-S2a's camera-side SMS solver (that stays the exact
  research-grade path).
- Not supertemporal / animated rain. One still showcase frame.
- No new density-estimation kernel — reuse the existing k-NN gather.

---

## Progress

- 2026-09-07 backlog triage: status flipped to `superseded`. Previous status text: PROPOSED (2026-09-04) — follow-up to pkg227 Phase 2a. The camera-side SMS chain solver (pkg227-S2a, on branch `pkg227-s2a`) is *correct* — it computes the exact multi-bounce sphere caustic (proven to <1e-8 rad, gated in CI) — but a single raindrop's primary bow rendered from the **camera side** is intrinsically a faint, noisy caustic, and a curtain of drops smears into an unresolved band (measured: band concentration 0.42 single-drop → 0.18 at 40 drops; the direct lens caustic is ~17× brighter and dominates the eye). This is the *same* reason the prism rainbow uses the **forward light-tracer** (`light_tracer_caustic`), not SMS. A beautiful rainbow is a rendering-**method** problem, not a solver problem.

- [ ] reflected-branch split in the general BVH loop + `caustic_internal_reflections` param
- [ ] droplet-curtain showcase scene + render gate (4 asserts above)
- [ ] verify prism reference byte-identical at default; regression sweep
- [ ] (note-only) GPU photon-loop transmit-only audit for a future GPU package

---

## Lessons

- (none yet)
