# pkg181 — Dedicated-light visibility to BSDF rays (Cycles `lights_intersect` parity): fix the systemic dim + dark lamp reflections

**Pillar:** 3 (GPU/CPU + Cycles parity) / Integration Milestone
**Track:** A (RTX + headless-Blender/Cycles; render legs serialize on the GPU lane)
**Status:** in progress — CPU implemented + VERIFIED on branch `pkg181-dedicated-light`
(2026-08-09): mirror-lamp 0.017x→1.008x Cycles, AREA floor 0.921x→0.985x Cycles,
SUN 0.50008 unchanged; all 7 CPU gates pass
(tests/test_pkg181_dedicated_light_bsdf_visibility.py). GPU wavefront advance-stage
twin implemented (stage_advance.cu intersectPathSlot + gpu_nee.cuh device helpers)
but UNBUILT/UNVERIFIED — DEFERRED to lead's RTX sweep (CUDA build + cuobjdump REG/STACK
+ GPU gate 6). Harness AREA flips removed (gate 7); pkg119-B/pkg129 band re-baseline
needs the lead's Blender/Cycles re-run.
**Estimated effort:** M–L (CPU + GPU wavefront, register-aware)
**Depends on:** pkg180 (diagnosis + mechanism + numbers — read
`.astroray_plan/docs/pkg180-systemic-cycles-dim-diagnosis.md` Phase 2 FIRST),
pkg120 (two-sided MIS term — the machinery this feeds into), pkg149 VNDF,
pkg122 (dedicated-light radiometry + the oracle configs), pkg119-B differential
harness + pkg129 metal A/B (the ratio bands this re-baselines), pkg166 (linear
floor+ceiling gate discipline).

## Origin

pkg180 Phase 2 localized the systemic ~12–20% Astroray-vs-Cycles dim AND the
owner's 2026-08-09 observation ("a light seen in a reflection looks dark, as if
self-occluding") to a **single engine-core defect**. This package fixes it. Do
not re-diagnose — the mechanism, code locations, and target numbers are in the
pkg180 note.

## The defect (named)

**Dedicated lights are invisible to BSDF-sampled rays, but NEE still pays the
MIS power-heuristic complement as if they weren't.** `astroray::Light` is a
first-class interface *sibling to* `Hittable` (`include/astroray/light.h:3`),
never in the BVH; the addon translates every Blender lamp (POINT/SUN/AREA/SPOT)
via `add_*_dedicated` (`blender_addon/__init__.py:4150–4217`). The NEE leg
(`include/raytracer.h:2457–2487`) weights every non-delta light sample by
`wt = a²/(a²+b²)`, budgeting for the complementary BSDF-sampled hit
(`raytracer.h:2416–2447`, pkg120) that can only fire on emissive **Hittables** —
structurally impossible for a dedicated lamp. So the BSDF-share of every lamp's
direct light is discarded at every diffuse/glossy vertex, and lamp reflections
in specular/low-roughness surfaces are near-black (NEE skipped on delta lobes;
`wt→0` as roughness→0). The loss scales with the lamp's subtended solid angle,
which reproduces the whole baseline pattern (backdrop ~0.80 worst → sun clean).
GPU wavefront is structurally identical (`src/gpu/gpu_nee.cuh:438`; no lamp
intersect in `stage_advance.cu`).

Measured (pkg180): mirror reflecting a 100 W area lamp — Cycles 7.155 vs
Astroray 0.123 (**58× too dark**); radiance-matched emissive MESH → 0.965×
(fine); area lamp over diffuse floor 0.93× with addon/standalone = 0.991
(**translator exonerated, engine convicted**); SUN analytic 0.50008 vs 0.5
(near-delta lights already exact).

## Fix (Cycles `lights_intersect` parity)

Add a lamp-intersection pass for dedicated lights and feed the hits into the
EXISTING pkg120 two-sided MIS term:

- `Light::intersect(ray, tMin, tMax)` for **Area**, **Point(radius>0)**,
  **Spot(radius>0)**, **Distant/Sun(angle>0)**. Truly-delta lights (radius/angle
  == 0) stay NEE-only with `wt=1` (a BSDF ray cannot hit a zero-measure light) —
  matching Cycles.
- In `pathTraceSpectral` (CPU) and the GPU wavefront **advance/intersection**
  stage (NOT the shade stage — it is register-saturated at REG:254, memory
  `wavefront-shade-kernels-register-saturated`), test dedicated lights against
  the current BVH-hit distance for **non-camera rays only** (Cycles semantics:
  lamps are invisible to camera rays; only indirect/BSDF rays see them).
- Feed hits into the existing MIS term. `LightList::pdfValue` /
  `PowerLightSampler::pdfValue` already sum dedicated lights, so the weight
  machinery is complete — **only the intersection is missing**. Exercise the
  light-tree (`Tree` sampler) `pdfValue` path too, not just power sampling.
- Respect spot cone / area spread / one-sidedness via the existing per-type
  falloff so a back-face or out-of-cone hit stays dark.
- **Cite** Cycles `intern/cycles/kernel/light/light.h` `lights_intersect` +
  `light_sample_from_intersection` (Apache-2.0) in-code (CLAUDE.md §6).

## Gates (all linear, floor+ceiling — memory `gamma-furnace-cannot-detect-energy-gain`)

1. **Mirror-lamp A/B ≥ 0.95× Cycles** (was 0.017×) — the owner's observation.
2. **pkg122 AREA floor A/B in [0.97, 1.03]** (was 0.921×).
3. **SUN analytic 0.5 within ±1%** — regression guard for near-delta lights.
4. **Furnace/energy suites unchanged** (no new energy gain introduced).
5. **Render-level suites re-run** (`reflection_not_black`, `material_properties`)
   — not just the new gates (memory `pr-named-tests-insufficient`).
6. **CPU/GPU agreement** on probes (1)–(3).
7. **Remove the stale harness AREA flips** (pkg180 side-finding 1:
   `benchmarks/blender_parity/scene_library.py::build_light_scene` and
   `scripts/verify_pkg122_cycles_oracle.py` — post-pkg139 they render the
   Astroray leg BLACK) and re-baseline the pkg119-B + pkg129 ratio bands.

## Risks / notes

- Wavefront shade stages are register-saturated (REG:254) — the lamp intersect
  belongs in the advance/intersection stage; pin the wavefront snapshot capture
  moment at spec time (memory `wavefront-snapshot-semantics-class-of-bug`),
  measure REG/STACK with cuobjdump, attach the register report.
- CI has no GPU (memory `ci_has_no_gpu_runtime_blindspot`) — this MUST get the
  full RTX sweep at closeout; green CI alone is not acceptance.
- GPU NEE `gpu_nee.cuh:440` still divides by `(lightPdf+0.001)` (pkg180
  side-finding 3) — the additive-epsilon family; fold the GPU twin removal in
  with the pkg172(A) GPU work, NOT here, unless it blocks a gate.

## Rejected alternative

Setting `wt=1` for all dedicated lights (NEE-only estimator): unbiased for
diffuse and would close the uniform dim, but lamp reflections stay black on
delta lobes and near-black at low roughness — it does NOT fix the owner's
observation and diverges from Cycles' estimator. Parity requires the intersect.

## Sequencing (owner-facing, from pkg180)

pkg181 fix → RTX hardware sweep → ONE coordinated re-pin (pkg172(A) + pkg119-B
bands + pkg129 metal bands + pkg178 lobe gates + disney-sweep re-bless on 5.2)
on the clean baseline. pkg172(A) and the refbank re-bless are BLOCKED on this.

## Provenance

Filed by the lead 2026-08-09 from pkg180 Phase 2 (Fable architect localization).
Owner observation 2026-08-09: dark lamp reflections. Root cause: dedicated-light
non-hittability + unmatched MIS complement.
