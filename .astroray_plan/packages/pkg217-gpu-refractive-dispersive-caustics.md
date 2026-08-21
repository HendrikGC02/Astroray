# pkg217 — GPU refractive / dispersive caustics (glass casts a bright caustic, not a black shadow)

**Pillar:** 3 (light transport / spectral rendering)
**Track:** A
**Status:** open (filed 2026-08-21).
**Priority:** NOT top — owner (2026-08-21) explicitly deprioritised: "not necessarily #1 if there are more pressing things or older packages waiting their turn." Sequence behind the existing backlog; this is a real feature, not a quick fix.
**Estimated effort:** L (GPU wavefront caustic path; register-hostile — probe-gated).

## Goal

A delta light (spot / sun, radius 0) refracting through a glass caustic-caster onto a
diffuse surface currently produces a **fully black shadow** on the GPU wavefront —
the refracted energy is dropped. Make it produce a **caustic** (a bright refracted
light patch), and — because Astroray is spectral — a **dispersion-coloured** caustic
through a Sellmeier prism. Match Cycles' "Shadow Caustics" behaviour.

## Context (reproduced 2026-08-21 via the live Blender MCP)

- Scene: white diffuse floor + closed Sellmeier-glass prism (`is_caustic_caster = True`,
  wired correctly via the Astroray Output node) + a collimated delta spot straight down.
- GPU render: the spot lights the floor (bright pool, 76% lit) but the prism casts a
  **pure-black shadow** — zero transmitted light, no caustic, no dispersion on the floor.
  Direct-VIEW dispersion (camera looking *through* the glass) DOES work; only the
  projected caustic is missing.
- Root cause: a unidirectional path tracer cannot connect a diffuse hit through glass to
  a delta light by ordinary NEE (the light is occluded by the glass) or by BSDF sampling
  (can't randomly hit a delta light through refraction). It needs a dedicated caustic
  method. Astroray has a caustic-caster flag (pkg64, SMS-style, Cycles Shadow-Caustics
  parallel) and the addon sets it, but **the GPU wavefront does not act on it** — caustic
  handling is the register-hostile work deferred in prior rounds (see memory
  `wavefront-shade-kernels-register-saturated`, `closure-graph-lobe-count-spills-the-fused-kernel`,
  and the pkg200 honour-matrix rows `caustics_reflective`/`caustics_refractive` → "genuinely
  register-hostile, deferred to Stage 3").
- CPU status unknown here: the same scene was ALSO black on CPU, but for a DIFFERENT
  reason (the tree-light-sampler-over-empty-list bug, fixed separately 2026-08-21). Re-assess
  the CPU refractive-caustic path once that fix lands — CPU may already support SMS caustics
  and only need verification.

## Specification (sketch — refine at dispatch)

1. **Invoke `cite-algorithm` BEFORE writing code** (CLAUDE.md §6). Candidate methods:
   - **Specular Manifold Sampling** (Zeltner, Georgiev, Jakob 2020) — Cycles' Shadow
     Caustics is a restricted SMS; the caustic-caster flag already mirrors its opt-in.
   - **Manifold Next-Event Estimation** (Hanika, Droske, Fascione 2015).
   - Cycles `integrator/shadow_catcher`/`shade_surface` shadow-caustics path as the parity
     reference. Save a research note to `.astroray_plan/docs/`.
2. Wire the caustic path into the GPU wavefront behind the existing per-object
   `is_caustic_caster` flag, so only opted-in casters pay the cost. MUST clear a register
   probe first (spec-gate like pkg198/pkg199) — the shade kernels are pinned at REG:254;
   any per-hit caustic state that spills tanks non-caustic perf. Isolate via
   `template<bool HasCaustics>` if-constexpr, do NOT bloat the shared kernel.
3. Spectral: the refracted caustic must carry per-λ bending so a Sellmeier prism throws a
   dispersion-coloured caustic (leverages pkg206 hero-λ importance sampling for convergence).
4. CPU/GPU parity: byte-mirrored where feasible; the caustic is a visual gate, not a
   bit-exact one (independent MC streams — per-channel mean-ratio, not SSIM).

## Acceptance criteria

- [ ] Glass prism + collimated delta spot + diffuse floor: the floor under the prism shows a
      BRIGHT caustic patch (not a black shadow) on GPU. Assert mean linear radiance in the
      caustic region > a black-shadow baseline by a stated factor.
- [ ] Sellmeier prism caustic is dispersion-coloured (hue spread in the caustic region;
      guard against salt-and-pepper false positives — visually inspect, memory
      `general-photon-loop-needs-solid-glass`).
- [ ] Non-caustic scenes show NO measurable perf regression (register probe green; the
      caustic path is off unless a caster opts in).
- [ ] CPU parity: the CPU caustic matches GPU within a per-channel mean-ratio band.
- [ ] Cycles Shadow-Caustics parity scene (glass sphere/prism over a floor) — qualitative
      match on caustic shape/brightness.
- [ ] CI green on all matrix jobs.

## Reference

- Blender MCP repro session 2026-08-21 (this file's Context).
- Memory: `wavefront-shade-kernels-register-saturated`, `closure-graph-lobe-count-spills-the-fused-kernel`,
  `general-photon-loop-needs-solid-glass`, `gpu-dielectric-lowers-to-closure-graph`.
- pkg64 (caustic-caster flag), pkg200 honour matrix (caustics_reflective/refractive rows).
