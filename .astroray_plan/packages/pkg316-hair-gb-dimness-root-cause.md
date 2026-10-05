# pkg316 — Hair g/b dimness vs Cycles: lobe-level root cause, then fix (#1051)

**Pillar:** 1
**Track:** A
**Status:** open
**Estimated effort:** 1–2 sessions (~5 h): diagnosis 2–3 h, fix + gates 2 h; one lead CUDA build if the GPU hair eval changes
**Depends on:** pkg225

---

## Goal

Before: after the #1037 self-skip fix the Principled Hair (Chiang) tuft in corpus v2 matches Cycles in red but reads
g/b 0.91–0.95 and L 0.93–0.97 of Cycles; the melanin test tuft is ~22 % dimmer in total covered energy and more
saturated (R/B 1.217 vs Cycles 1.145). Gate (e) rates #1051 high (wrong image, no warning).
After: the defect has a named code site, proven by a lobe-level comparison against an independent reference, and is
fixed on CPU and GPU; the provisional hair_tuft rows in `provisional_v2.toml` pass and are removed.

---

## Context

Last unstarted gate (e) high. Both backends agree to 1–3 %, so the error is shared math or shared geometry, not a
port divergence. The pattern (more loss in g/b than r, scaling with darkness) points to absorption along the
multiple-scatter chain, but geometry (`h` from the curve hit) and integrator weighting are equally plausible. The
corpus node is Chiang with `parametrization = COLOR` (verified: Blender 5.2 `ShaderNodeBsdfHairPrincipled` defaults
to `model = CHIANG`), so this is not a Huang-vs-Chiang model mismatch.

---

## Evidence

- 2026-10-03 (#1051): v2_camera_geometry tuft CPU/Cycles r 0.998, g 0.941, b 0.937, L 0.956; ortho r 0.981, g 0.914,
  b 0.906, L 0.932 (3 seeds, 64 spp). GPU/CPU within 1–3 %.
- `tests/test_pkg225_spectral_hair.py`: Cycles 5.2 CPU Chiang melanin 0.6, 384 spp: covered R/B 1.145; engine 1.217
  (rgb) / 1.205 (spectral). Covered energy 85.5 (Cycles) vs 66.5 (Astroray); covered-pixel counts not matched.
- 2026-10-06: `ShaderNodeBsdfHairPrincipled` created headless in Blender 5.2 reports `model CHIANG`, `parametrization COLOR`.

---

## Reference

- Chiang, Bitterli, Tappan, Burley 2016, "A Practical and Controllable Hair and Fur Model for Production Path
  Tracing" (EGSR / CGF 35(2)), Eq. 4–10 (Mp, Ap, Np) and the colour→σa inversion.
- Cycles `intern/cycles/kernel/closure/bsdf_principled_hair_chiang.h` and `kernel/svm/closure.h` hair setup
  (Apache-2.0): the target behaviour, including how `h` is derived on thick curves.
- pbrt-v4 `src/pbrt/bxdfs.cpp` `HairBxDF` (Apache-2.0): independent reference evaluator; its white-furnace test
  (`src/pbrt/bsdfs_test.cpp` hair furnace tests) is the model for the furnace gate.
- `docs/pkg225-hair-bsdf-research.md` (existing pbrt-vs-Cycles divergence table).

---

## Prerequisites

- [ ] Main builds; `tests/test_pkg225_*` green.
- [ ] Blender 5.2 available for the Cycles legs.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg316_hair_lobe_reference.py` | Lobe-level f(wo,wi) grid vs an in-test pbrt-v4-derived reference; white furnace (σa = 0) per lobe and summed |
| `.astroray_plan/docs/pkg316-hair-dimness-diagnosis.md` | Bisection table: which stage owns the deficit, with numbers |

### Files to modify

| File | What changes |
|---|---|
| `include/astroray/hair_bsdf.h` | The fix, if the owner is the shared BSDF math |
| `include/astroray/gpu_hair.cuh` | GPU mirror of the same fix (formula only, no new live state) |
| `plugins/materials/principled_hair.cpp` | The fix, if the owner is parametrization (colour/melanin → σa) or `h` mapping |
| `include/astroray/curves.h` | The fix, if the owner is the curve-hit `h` / frame |
| `benchmarks/reference_corpus/provisional_v2.toml` | Remove the hair_tuft rows that now pass |
| `tests/test_pkg225_spectral_hair.py` | Re-pin the melanin energy assertion against the Cycles numbers with a matched covered-pixel mask |

### Key design decisions

#### Diagnosis order (stop at the first stage that owns the deficit)

1. **BSDF math:** evaluate Astroray's hair f(wo,wi)·|cos θi| on a (h, θi, θo, φ) grid for the corpus colour and
   melanin 0.6 against the pbrt-v4 HairBxDF formulas re-implemented in the test (Apache-2.0, cited inline).
   White furnace with σa = 0 must integrate to 1 within MC error, per lobe and in total (pbrt-v4 test pattern).
2. **Parametrization:** colour→σa (Chiang Eq. for β_N) and melanin→σa vs Cycles' `bsdf_principled_hair_sigma_*`.
3. **Geometry:** distribution of `h` at camera and bounce hits on a thick curve vs uniform [−1, 1]; frame orientation.
4. **Integrator:** single-strand scene (one fibre, one sun, black world) Astroray vs Cycles at 1024 spp, then NEE-only
   and BSDF-only legs (MIS weights; hair is non-delta, both strategies must agree on the mean).
5. Multi-strand only after 1–4 agree: bounce limits / RR on long hair chains.

- Compare means with matched covered-pixel masks (Cycles alpha pass vs Astroray coverage), never raw sums.
- Unbiased strategy legs that disagree in the mean are a bug signal, not noise (memory note on strategy switches).
- GPU: formula-only edits inside the shade kernel; no new per-hit state (REG 254). Report cuobjdump deltas.
- Stop rule: if stages 1–4 all agree and the residual is multi-strand only, record the table, keep the rows xfail,
  and file a scoped follow-up instead of guessing.

---

## Acceptance criteria

- [ ] Diagnosis doc names the owning stage with a before/after number.
- [ ] Furnace (σa = 0) per lobe and total within 1 % of 1 (CPU); lobe grid matches the reference to 1e-3 relative.
- [ ] v2_camera_geometry hair_tuft r/g/b/L inside the MC band vs Cycles on CPU and GPU (perspective and ortho);
      rows removed from `provisional_v2.toml`; corpus suite 0 XPASS.
- [ ] Melanin tuft covered energy within 5 % of Cycles with a matched mask; R/B within the MC band.
- [ ] Non-hair scenes byte-identical (CPU); GPU shade REG/STACK unchanged or delta reported and accepted by the lead.

---

## Non-goals

- Do not implement the Huang 2022 model (it is reported as approximated by Chiang; separate work).
- Do not retune hair against Cycles by scale factors (no look-parity hacks).
- Do not touch the #1037 self-skip logic unless stage 3 proves it is the owner.

---

## Progress

- [ ] Stage 1 lobe grid + furnace.
- [ ] Stages 2–4 as needed; diagnosis doc.
- [ ] Fix CPU + GPU; corpus rows; melanin re-pin.
- [ ] Lead: build, GPU suite, corpus v2 hair rows.

---

## Lessons

*(Fill in after the package is done.)*
