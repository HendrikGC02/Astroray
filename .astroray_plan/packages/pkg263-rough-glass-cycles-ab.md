# pkg263 — Rough-glass Cycles A/B row in the parity harness

**Pillar:** 5
**Track:** A
**Status:** done — PR #764 merged 2026-09-08: glass preset in the metal_ab harness (IOR 1.45, roughness 0/0.2/0.5/0.85, centre/limb/background ROIs); limb darkening CONFIRMED far outside the 1.4 % noise floor — Astroray/Cycles limb 0.81 → 0.34 and centre 0.96 → 0.53 from r 0 to r 0.85; fix owned by pkg264. Also fixed the harness bug that left the Astroray leg at Blender's factory 4096 spp + denoise (thin-film twin tracked as #765)
**Estimated effort:** 1 session (~3 h; CPU headless Blender; GPU leg optional)
**Depends on:** pkg129, pkg119

---

## Goal

Before: every rough-glass energy fix (pkg118, pkg167, pkg169, pkg179) was gated
against Astroray's own white furnace; no Cycles-vs-Astroray rough-glass
comparison exists (the cycles-parity harnesses cover metals and thin film
only), so the owner's observation that Astroray rough glass shows a rim/limb
darkening Cycles does not is unmeasured. After: the parity harness has a
rough-glass row (sphere on a plane under a studio light + a grey world, IOR 1.45,
roughness sweep 0 / 0.2 / 0.5 / 0.85) rendered in both engines with the
pkg129 metal_ab pattern, reporting per-channel mean ratio in three ROIs (sphere
centre, sphere limb annulus, background) and the limb/centre ratio per engine,
so the limb darkening is either quantified with a root-cause lead or shown to
be within noise.

---

## Context

Owner 2026-09-08: "the rough glass in Astroray still has this limb-darkening
that isn't present in Cycles rough glass; a package improved things but never
reached a perfect result." The pkg259 corpus (materials_hall Alcove C) will
eventually carry this, but a targeted row now gives a number in one session
and tells pkg124 (VNDF reflection lobe) and pkg179 Phase 2 what to chase.
Serves Pillar 5 / gate (c).

---

## Evidence

- 2026-09-08: `benchmarks/cycles-parity/` contains `metal_ab` and `thin_film`
  harnesses only; `grep -i glass` over the harness scripts returns nothing.
- pkg179 Phase 1 done; its Phase 2 boxes (dead-sample redistribution, furnace
  in-band at r ∈ {0.3, 0.6, 1.0} CPU and GPU) are unticked; pkg124 open.
- Memory `rough-glass-residual-is-multiscatter`: the 2026-06 furnace deficit
  was the albedo-LUT η² clamp (#423), not multi-scatter.

---

## Reference

- `benchmarks/cycles-parity/metal_ab/harness.py` (pkg129; the pattern to extend,
  not fork), `benchmarks/blender_parity/render_leg.py` (`_to_top_down`, ROI
  discipline — memory `blender-pixels-bottom-up-roi-flip`).
- Cycles `bsdf_microfacet.h` (`bsdf_microfacet_ggx_glass_*`, `microfacet_ggx_preserve_energy`),
  Astroray `plugins/materials/disney.cpp` glass branch, `principled.cpp` `ggxGlassComp`.

---

## Prerequisites

- [ ] Headless Blender 5.2 + the CPU addon module staged from main.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `benchmarks/cycles-parity/rough_glass/harness.py` | Only if `metal_ab/harness.py` cannot take a glass preset; otherwise this file is NOT created and the metal_ab driver gains a `--material glass` preset. |
| `.astroray_plan/docs/pkg263-rough-glass-ab-2026-09.md` | Results table (ratios per ROI per roughness, both engines), annotated ROI PNGs, root-cause leads. |

### Files to modify

| File | What changes |
|---|---|
| `benchmarks/cycles-parity/metal_ab/harness.py` | Glass preset (Glass BSDF, IOR 1.45, roughness sweep), limb/centre/background ROIs drawn on the proof PNG, per-channel mean-ratio report. |
| `scripts/README.md` | Note the glass preset on the existing metal_ab row. |
| `.astroray_plan/packages/pkg124-vndf-sampling.md` | Evidence line pointing at the measured limb ratio. |

### Key design decisions

- Extend the pkg129 driver; no new one-off script (CLAUDE.md §5b).
- Linear EXR both engines, Standard view transform, adaptive off, denoise off
  on scene AND view layer, same seed policy as the pkg119b harness.
- Diagnostic only: no engine change in this package; findings route to pkg124 /
  pkg179 / a new spec.

---

## Acceptance criteria

- [x] Both engines render the sweep headless without exception (4/4 configs
      PASS, both legs each). ROI PNGs subagent-visually-verified (correct
      framing, no sphere/plane bleed into background ROI); still awaiting the
      LEAD's own inspection pass per common-rules — not ticked as
      lead-reviewed.
- [x] Results doc with the limb/centre ratio per engine per roughness and the
      Astroray/Cycles ratio per ROI; a stated verdict (darkening CONFIRMED,
      magnitude quantified, noise floor ≤1.4% vs 19-66% observed gaps) with
      root-cause leads — `.astroray_plan/docs/pkg263-rough-glass-ab-2026-09.md`.
- [x] Preset registered (`scripts/README.md`); harness pure tests green
      (13/13, `tests/test_pkg129_metal_ab_harness.py`).

---

## Non-goals

- No BSDF changes here. No GPU requirement (GPU leg optional if the lock is free).

---

## Progress

- [x] 2026-09-08 — filed by the lead; owner approved; not started.
- [x] 2026-09-08 — glass preset added to `metal_ab` (scenes/harness/render_leg);
      13/13 pure tests green; full 4-roughness CPU sweep run (res 256, 128 spp
      both engines); results doc + 12 evidence PNGs written; Cycles noise
      floor measured (second seed); PR #764 opened. Verdict: limb darkening
      CONFIRMED (Astroray/Cycles limb ratio 0.81→0.34 over r=0→0.85, vs a
      ≤1.4% noise floor). Root-cause leads recorded for pkg124/pkg179 Phase 2.
      GPU leg not run (CPU-only lane).

---

## Lessons

- (none yet)
