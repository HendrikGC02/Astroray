# pkg270 — Principled Volume emission (blackbody / temperature) + spectral σ coefficients

**Pillar:** 3
**Track:** A
**Status:** open
**Estimated effort:** 3 sessions (~9 h)
**Depends on:** pkg268

---

## Goal

Before: heterogeneous media scatter and absorb (pkg268) but do not emit, and σ is
handled without a chromatic-tracking story. After: the Principled Volume closure
emits — emission strength/color plus blackbody intensity/tint driven by the
temperature grid evaluated through Planck's law **spectrally** (fire/explosion
look) — and σ_a(λ)/σ_s(λ) are handled per-wavelength via spectral/decomposition
tracking, so chromatic extinction is physically correct rather than RGB-approximate.

---

## Context

Emission (fire, explosions, emissive nebula-like media) is core Cycles Principled
Volume behaviour and required for parity. It is also the natural place to apply
the §7 2026-09-08 physics-first rule: Cycles blackbody emission is RGB-LUT-
approximate (memory `gpu-emission-is-rgb-approximated`) and Cycles tracks σ in
RGB, while Astroray is spectral — so Planck-spectral emission and per-λ σ are
features, with Cycles as a cross-check band. Physics-heavy: Opus-tier
implementation. Research: `docs/volumes-track-research-2026-09-12.md` §2, §4.

---

## Reference

- Design doc: `.astroray_plan/docs/volumes-track-research-2026-09-12.md` §2, §4 (divergences 1, 2)
- External: Planck's law; Kutz et al. 2017 "Spectral and Decomposition Tracking"
  (chromatic σ); Cycles `svm/svm_blackbody.h`, `svm/closure.h`
  `svm_node_closure_volume`, `blender/volume.cpp` temperature-grid mapping
  (Apache-2.0); pbrt-v4 spectral MIS majorant loop (Apache-2.0).
- Existing engine Blackbody path (Sellmeier/Blackbody nodes, memory
  `astroray-native-nodes-need-astroray-output`).

---

## Prerequisites

- [ ] pkg268 is done and green (scattering/absorption transport exists).
- [ ] Owner open-question 2 resolved (spectral Planck vs Cycles-match for the
      fire look); default = spectral Planck with Cycles as cross-check band.
- [ ] `cite-algorithm` run for spectral/decomposition tracking; notes saved.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `include/astroray/volume/volume_emission.h` | Emission strength/color + blackbody(temperature)→Planck spectral radiance for a `GridMedium` |
| `tests/test_pkg270_blackbody_furnace.py` | Emission-only: blackbody radiance vs analytic Planck at known T (linear, floor+ceiling) |
| `tests/test_pkg270_spectral_extinction.py` | Per-λ σ produces measurable chromatic extinction vs an RGB-collapsed run; Cycles cross-check band |

### Files to modify

| File | What changes |
|---|---|
| `include/astroray/volume/principled_volume.h` | Add emission_strength, emission_color, blackbody_intensity, blackbody_tint, temperature-grid handle → per-λ emission; wire per-λ σ_a/σ_s |
| `include/astroray/volume/volume_transport.h` | Accumulate emission along the free flight; use spectral/decomposition tracking for chromatic σ_t |
| `blender_addon/exporter.py` | Lower the remaining `ShaderNodeVolumePrincipled` sockets (emission, blackbody, temperature attribute) onto the medium |
| `module/blender_module.cpp` | Bind the emission/blackbody params + temperature-grid handle |

### Key design decisions

- **Blackbody = spectral Planck** (physics-first, §4 divergence 2): evaluate
  Planck at the temperature-grid value per sampled wavelength through the existing
  engine Blackbody path; Cycles' RGB-LUT result is the cross-check band, not the
  gate. Blackbody intensity scales it; tint multiplies.
- **Chromatic σ:** spectral/decomposition tracking (Kutz 2017) so per-λ σ_t does
  not force a hero-wavelength collapse; clean-room from pbrt-v4, cite.
- **Emission along the flight:** accumulate σ_a·L_e over the tracked path
  (null-scattering-consistent), never a biased fixed-step march (§4 divergence 5).
- **Socket semantics** follow Cycles `svm_node_closure_volume`: density,
  temperature attribute name, blackbody intensity/tint, emission strength/color.
- If pkg269 has already landed, extend the GPU emission accumulation in the same
  PR ONLY if it does not grow the shade-kernel REG; otherwise file the GPU
  emission leg as a follow-up rather than risking the REG:254 gate.

---

## Acceptance criteria

- [ ] `test_pkg270_blackbody_furnace.py` passes: emission-only radiance matches
      analytic Planck at a known T within tolerance, rendered linear with floor
      AND ceiling asserts (`apply_gamma=False`).
- [ ] `test_pkg270_spectral_extinction.py` passes: per-λ σ yields measurably
      different chromatic extinction than an RGB-collapsed run, and lands inside
      the Cycles cross-check band.
- [ ] A blackbody fire/explosion VDB renders on the CPU and is inspected
      qualitatively by Astra or Claude (visual evidence saved); the divergence
      from Cycles' RGB blackbody is recorded with oracle numbers.
- [ ] Full CPU suite green; grid-free scenes unchanged.

---

## Non-goals

- Do not add volume passes/AOVs or the corpus family — pkg271.
- Do not add velocity/motion blur or multi-scatter — pkg272.
- Do not introduce a biased fixed-step emission march.
- Do not make Cycles' RGB blackbody the acceptance criterion (it is the
  cross-check band).
- Do not grow the GPU shade-kernel register footprint to add GPU emission.

---

## Progress

- [ ] cite-algorithm for spectral/decomposition tracking.
- [ ] `volume_emission.h` (Planck spectral) + Principled emission/blackbody params.
- [ ] Chromatic σ tracking in `volume_transport.h`.
- [ ] Exporter socket lowering + bindings.
- [ ] Blackbody furnace + spectral-extinction gates; visual inspection.

---

## Lessons

*(Fill in after the package is done.)*
</content>
