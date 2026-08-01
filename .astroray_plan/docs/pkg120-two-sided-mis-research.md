# pkg120 — Two-sided MIS for the spectral integrator (research / citation note)

Companion to `.astroray_plan/packages/pkg120-two-sided-mis-spectral.md` and the
C2 MIS audit (`pkg55-phase-c-plan-2026-07.md §4`). No invented algorithm
(CLAUDE.md §6): the term below is the standard MIS BSDF-sampled leg, mirrored
from the reference implementations cited here.

## The estimator

Direct illumination `L = ∫ f(ω)·Le(ω) dω` is estimated by combining two unbiased
strategies — light sampling and BSDF sampling — with the **power heuristic**
(Veach 1997, "Robust Monte Carlo Methods for Light Transport Simulation", §9.2,
β=2):

```
w_L(ω) = pdf_L² / (pdf_L² + pdf_B²)      w_B(ω) = pdf_B² / (pdf_L² + pdf_B²)
L ≈ w_L·f·Le/pdf_L   (light leg, NEE)   +   w_B·f·Le/pdf_B   (BSDF leg)
```

`w_L + w_B = 1` per direction. Astroray applied only `w_L` (NEE) and dropped the
`w_B` leg for diffuse bounces, so the estimator was biased low by `∫ w_B·f·Le dω`
— the deficit grows as the light's apparent size grows (`pdf_B ~ pdf_L`), i.e. the
softbox / large-near-area-light regime. Compact/distant lights (`pdf_B ≪ pdf_L`,
`w_B ≈ 0`) were already unbiased, which is why this went unnoticed.

## The fix (both integrator paths)

When a BSDF-sampled continuation ray from a **diffuse** bounce
(`bounce > 0 && !wasSpecular`) hits an emitter, add

```
throughput · Le · w_B ,   w_B = powerHeuristic(bsdfPdf_prev, lightPdf_hit)
```

- `bsdfPdf_prev` — the BSDF pdf that generated that continuation ray, carried
  from the previous bounce (CPU: `bsdfPdfPrev`; GPU: SoA `path_bsdf_pdf`, written
  at shade, read at the next intersect).
- `lightPdf_hit` — the light-sampling pdf that would have generated this same
  emitter hit **from the previous shading point**: selection × solid-angle,
  including the light-tree traversal pdf when a tree is resident. This is the
  reverse of NEE's forward pdf, i.e. Cycles' `light_sample_from_intersection()`.

The `bounce == 0 || wasSpecular` full-emission path is unchanged: camera and
post-specular rays have no competing NEE leg, so `w_B = 1` there.

## Reference implementations (license-compatible)

- **Cycles** (Apache-2.0), `intern/cycles/kernel/integrator/shade_light.h` +
  `intersect_closest.h::light_sample_from_intersection()`: the canonical
  "BSDF ray hit a light → reconstruct its light-sampling pdf → apply `w_B`"
  ordering; `kernel/light/sample.h::light_sample_mis_weight` / `power_heuristic`.
- **Astroray's own deleted RGB megakernel** did exactly this
  (`path_trace_kernel.cu:348-372`, recoverable at 9fa91c8^, deleted by pkg55
  Phase C / PR #524) — the spectral port here is the surviving equivalent.
- Existing citations in-tree: `gpu_nee.cuh` (power heuristic, NEE leg),
  `light_sampler.cpp` (`pdfValue` selection × solid-angle × tree pdf).

## CPU ↔ GPU lockstep (by construction)

Both sides compute `w_B` from the SAME inputs so they agree without a tuned
tolerance:

| quantity        | CPU (`pathTraceSpectral`)                 | GPU (`stage_advance.cu` intersect) |
|-----------------|-------------------------------------------|------------------------------------|
| prev shading pt | `ray.origin`                              | `state.ray_origin_*` (verbatim)    |
| BSDF direction  | `ray.direction` (normalized)              | `state.ray_direction_*` (verbatim) |
| `bsdfPdf_prev`  | `bsdfPdfPrev = bss.pdf`                    | `state.path_bsdf_pdf[idx]`         |
| `lightPdf_hit`  | `LightList::pdfValue(pt, dir)`            | `gpu_reconstruct_light_pdf(...)`   |
| power heuristic | `bp²/(bp²+lp²+1e-8)`                       | `gpu_mw_powerHeuristic(bp, lp)`    |

`gpu_reconstruct_light_pdf` mirrors `LightList::pdfValue` exactly, including the
**`normal = -dir` proxy** the CPU `TreeLightSampler::pdfValue` uses
(`light_sampler.cpp:210`), the power-CDF selection-pdf difference, and the
per-shape solid-angle pdfs (Sphere `1/(2π(1-cosθmax))`, `shapes.h:50`; Triangle
`t²/(|dir·n|·area+1e-3)`, `shapes.h:226`). The prev-ray origin/direction are the
values written at the previous bounce and read verbatim at the next intersect —
no new-stage snapshot skew (cf. memory
`wavefront-snapshot-semantics-class-of-bug`).

## Gate (tests/test_pkg120_two_sided_mis.py, CPU-gated on CI)

`max_depth=1` isolates the one-sided leg (NEE only; the BSDF continuation ray is
never traced), `max_depth=2` adds the two-sided term — no integrator toggle
needed. Oracle: `L_r = ρ·L_e·(R/d)²` for a floor point under a uniform emissive
sphere, with `L_e` read from a calibration render so the RGB-emission convention
cancels. Asserts direction (one-sided dark), magnitude (two-sided ≈ oracle), and
no-regression (compact light unchanged). Wavefront leg is RTX-verified by the
team-lead via the wavefront-diff parity harness.
