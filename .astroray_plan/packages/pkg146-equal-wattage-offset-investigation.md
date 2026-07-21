# pkg146 — Investigate the equal-wattage brightness offset (re-attributed from pkg142/Defect 4)

**Pillar:** 3 (light transport / emitter energy — measurement correctness)
**Track:** A (an investigation: reconcile two disagreeing oracles before proposing any fix; measure first, adjudicate second)
**Codex-paste-ready:** no (diagnosis with a live-Cycles oracle + harness archaeology; the deliverable is a root-cause + a scoped fix spec, not a blind patch)
**Status:** open — dispatchable (investigation)
**Estimated effort:** M (mostly measurement + reconciliation; fix scope unknown until the two oracles are reconciled)
**Depends on:** pkg142 adjudication (keep `RGBIlluminant`, PR #511 reverted) — this investigation runs on the **`RGBIlluminant`** baseline, not the reverted RGBUnbounded one.

**Origin:** pkg142 ✅ FINAL ADJUDICATION. Defect 4 established that the RGB emission
**convention** (`RGBIlluminant` D65) is **correct** and is **not** the source of a
universal brightness offset. But the offset the owner delegated (all four dedicated-light
types **1.07–1.16×** brighter than Cycles at equal wattage, pkg122 oracle) is still
**unexplained** — and now looks **scene/type-dependent**, not a convention bug.

---

## The contradiction to resolve

Two oracle runs disagree on the same nominal quantity (Astroray/Cycles equal-wattage
brightness ratio) on the **unchanged `RGBIlluminant` baseline**:

| Oracle | Measured ratio | Implication |
|---|---|---|
| pkg122 (`verify_pkg122_cycles_oracle.py`) | **1.07–1.16×** (all four types) | motivated the whole Defect-4 "switch the convention" effort |
| pkg139 rows | **0.96–1.01×** (no pkg142 change) | offset is small/absent → scene- or harness-dependent |

If pkg139 already sits at 0.96–1.01 on the same baseline, the pkg122 1.07–1.16 is **not**
a universal property of the emission lift. **This discrepancy is the primary lead** — it
almost certainly points at a harness/scene difference, not a renderer energy bug (cf.
the pkg123 lesson that a test integrator can itself be the artifact, memory
`ssim-wrong-gate-for-independent-rng` and the pkg123 `rho()` false-positive/negative
finding).

---

## Investigation contract (measure-first; do NOT ship a brightness fix before reconciling)

1. **Diff the two oracles.** Line up the pkg122 and pkg139 scenes/harnesses:
   light type + wattage, floor albedo + material (Disney-diffuse vs pure Lambertian —
   the pkg122 SUN caveat already documents a Disney baseline-Fresnel leak), camera
   alignment (the pkg122 SUN 5° tilt + AREA 180° flip caveats), spp, colour management
   (`view_transform=Standard`, `exposure=0`, `gamma=1`), and the measurement patch.
   Produce a table of every difference.
2. **Identify which difference moves the ratio.** Re-run one harness while swapping in
   the other's choices one at a time (exposure/tonemap, material, patch location,
   wattage normalization) until the 1.16 vs 0.99 gap is explained. Expected suspects,
   in order: (a) colour-management/exposure mismatch; (b) Disney-diffuse-vs-Lambertian
   floor at the sampled angles; (c) the measurement patch catching a specular/Fresnel
   lobe; (d) a genuine residual per-type radiometry error pkg122 left (small).
3. **Only if a genuine renderer-side offset survives reconciliation**, scope a fix
   against the **live-Cycles** numbers (per-channel mean-ratio, NOT SSIM) — and it will
   be a **radiometry/units** fix (per-type or exposure), **not** an emission-convention
   change (that is closed: keep `RGBIlluminant`).

## Gates

- A written reconciliation: the pkg122↔pkg139 discrepancy explained, with the single
  dominant cause identified and demonstrated (before/after numbers).
- If a real offset remains: a live-Cycles oracle showing all four types within
  **[0.97, 1.03]** per channel after the scoped fix, on the `RGBIlluminant` baseline,
  with the reference bank re-blessed evidence-first (Blender 5.1 headless).
- If NO real offset remains (the likely outcome): the pkg122 oracle is corrected/retired
  as the artifact, and the "dimmer/brighter than Cycles" complaint is closed as a
  measurement issue with the evidence recorded.

## Non-goals

- **Do not** revisit the emission convention — `RGBIlluminant` (D65) is adjudicated
  correct (pkg142). Any pinkness or ~116×/~30% artifact belongs to the reverted #511, not
  here.
- **Do not** loosen the [0.97,1.03] band; if the renderer is genuinely off, fix the
  radiometry.

## Definition of done
- [ ] pkg122 vs pkg139 oracle discrepancy reconciled to a single dominant cause, demonstrated with numbers.
- [ ] Either: a scoped radiometry fix lands all four types in [0.97,1.03] vs live Cycles (RGBIlluminant baseline) with an evidence-first re-bless; **or** the offset is shown to be a harness artifact and the pkg122 oracle is corrected/retired with the complaint closed.
- [ ] Finding written to `.astroray_plan/docs/` with both oracle datasets cited.
