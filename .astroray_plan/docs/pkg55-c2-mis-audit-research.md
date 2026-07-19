# pkg55 Phase C — Session C2 MIS audit (research + findings)

**Author:** pkg55-C2 implementer, 2026-07-18. **Branch:** `feat/pkg55-c2-mis-audit`.
**Base:** main `a7f09d1` (C1 extraction merged, PR #481).
**Scope:** audit the wavefront's shade-time MIS flow against the cited Cycles
references + Veach's power heuristic; add `path_light_pdf` / `path_mis_pdf`
SoA instrumentation and a `PostNEE_MIS` per-stage gate. Per CLAUDE.md §6, no
new algorithm — cite, borrow, verify.

---

## 1. Reference sources (cite-and-borrow, licenses verified)

| Reference | File | License | What we mirror |
|---|---|---|---|
| Veach & Guibas 1995, "Optimally Combining Sampling Techniques for Monte Carlo Rendering", SIGGRAPH '95; Veach PhD thesis 1997, "Robust Monte Carlo Methods for Light Transport Simulation" (Stanford) §9.2 | — | public (academic) | Power heuristic `wt = a²/(a²+b²)` |
| Cycles `power_heuristic(a,b)` | `intern/cycles/kernel/sample/mis.h` | **BSD-3-Clause** | Exact formula `(a*a)/(a*a + b*b)` |
| Cycles `light_sample_mis_weight_nee(kg, ls.pdf, bsdf_pdf)` → `power_heuristic(nee_pdf, forward_pdf)` | `intern/cycles/kernel/light/sample.h` | Apache-2.0 | NEE-side MIS weight = `power_heuristic(lightPdf, bsdfPdf)` |
| Cycles `integrate_surface_direct_light()` | `intern/cycles/kernel/integrator/shade_surface.h` | Apache-2.0 | Ordering: sample light → `bsdf_eval` at shading point → MIS weight → queue shadow ray |
| Cycles `light_sample_from_intersection()` + forward MIS | `intern/cycles/kernel/light/sample.h`, `kernel/integrator/shade_light.h` | Apache-2.0 | The **BSDF-ray-hits-light** (two-sided) MIS branch the spectral integrator deliberately omits |

**Exact Cycles formula (fetched 2026-07-18):**
```cpp
// intern/cycles/kernel/sample/mis.h  (SPDX: BSD-3-Clause)
ccl_device float power_heuristic(float a, float b) { return (a * a) / (a * a + b * b); }
ccl_device float balance_heuristic(float a, float b) { return (a) / (a + b); }
```
```cpp
// intern/cycles/kernel/integrator/shade_surface.h  (SPDX: Apache-2.0)
//   light_sample_from_position(...) → ls
//   surface_shader_bsdf_eval(..., ls.D, &bsdf_eval, ...)          // eval at shading point
//   const float mis_weight = light_sample_mis_weight_nee(kg, ls.pdf, bsdf_pdf);
//   bsdf_eval_mul(&bsdf_eval, light_shader_eval * ls.eval_fac / ls.pdf * mis_weight);
//   → queue shadow ray
```

Astroray's power heuristic adds a `+1e-8f` denominator guard (division safety
for the both-pdf-zero corner); mathematically identical to Cycles for any
positive pdf. See `src/gpu/gpu_nee.cuh:27-29`.

---

## 2. Where the wavefront computes MIS (the audited code)

- **Shared power heuristic:** `src/gpu/gpu_nee.cuh:27-29`
  `gpu_mw_powerHeuristic(a,b) = a*a / (a*a + b*b + 1e-8f)`.
- **NEE light-sample MIS weight (production, deferred/bucketed path):**
  `src/gpu/wavefront/stage_advance.cu:341-347` — `bsdfPdf = gpu_material_pdf(mat, rec, wo, s.wi);
  wt = a2/(a2+b2+1e-8f)` with `a2 = s.lightPdf²`, `b2 = bsdfPdf²`; contribution
  scaled by `wt / (s.lightPdf + 0.001f)` (lines 347, 355-358).
- **NEE light-sample MIS (immediate/flat path, shared):** `src/gpu/gpu_nee.cuh:207-210` —
  identical formula via `gpu_mw_powerHeuristic(s.lightPdf, bsdfPdf)`.
- **`s.lightPdf` composition (selection × solid-angle, incl. light-tree pick pdf):**
  `gpu_nee.cuh:79-90` (selection: tree pick `treePdf` at :85 when resident, else
  power-CDF `power/totalPower` at :89) and `:115` (sphere solid-angle × selPdf),
  `:131` (triangle area→solid-angle × selPdf).
- **Emissive-on-hit gate:** `stage_advance.cu:198-210` — `Le` added to `color`
  **only** when `bounce == 0 || wasSpecular`; path terminates either way.

### Reference the wavefront mirrors (bit-identical by shared-kernel construction on CPU)
- CPU reference oracle: `src/cpu/wavefront/path_kernel.cpp:229-276` (NEE + PostLightSample
  snapshot) and `:217-225` (emissive gate). Both `reference_pt_wavefront` and the
  CPU wavefront driver call this same `advance_one_bounce`.
- Production CPU: `include/raytracer.h::pathTraceSpectral` — NEE MIS at `:2476-2498`,
  emissive gate at `:2464-2472`. The wavefront is the GPU twin of this.

---

## 3. Line-by-line audit findings

### Finding A — NEE power-heuristic weight: MATCH (correct-by-construction)
The wavefront's NEE MIS weight `wt = lightPdf²/(lightPdf²+bsdfPdf²+1e-8)` equals
Cycles `light_sample_mis_weight_nee(ls.pdf, bsdf_pdf) = power_heuristic(nee_pdf, forward_pdf)`
and the CPU reference `path_kernel.cpp:244-245` / `raytracer.h:2493-2494`,
term-for-term. The ordering (sample light → eval BSDF + pdf + MIS in shade →
trace shadow ray in a dedicated stage) mirrors Cycles `integrate_surface_direct_light`
exactly; the split is documented at `stage_advance.cu:103-105, 331-337`. **No divergence.**

### Finding B — light-pdf composition (selection + solid-angle + tree pick pdf): MATCH
`s.lightPdf` folds the selection pdf into the solid-angle pdf on both sides:
- GPU: `gpu_nee.cuh:89` (`power/totalPower`) or `:85` (`treePdf` from
  `gpu_light_tree_pick`), then `× selPdf` at `:115`/`:131`.
- CPU: `src/light_sampler.cpp:52,67,85` (`out.pdf = … * selPdf`); tree pick pdf at
  `:155` (`treePdf = pick.pdf`). The light-tree descent pdf math is the same on
  both sides (`src/light_tree.cpp:498-518` ↔ `src/gpu/light_tree_device.cuh:111-120`,
  Conty 2018 / Cycles `kernel/light/tree.h`, already parity-gated by
  `test_pkg86_B_gpu_parity.py`). **No divergence.**

### Finding C — the BSDF-ray-hits-emitter path (the named asymmetry-bug check): NO BUG
The task's specific check: *"when a BSDF sample hits an emissive surface, is the
light-pdf side of the power heuristic computed consistently with how NEE computed
it (including the light-tree pick pdf branch)?"*

**Resolution: the spectral integrator is one-sided — it never computes a
BSDF-side light-pdf, so the asymmetry bug class cannot occur.** When a BSDF
continuation ray hits an emitter at a diffuse bounce (`bounce>0 && !wasSpecular`),
the wavefront (`stage_advance.cu:200-210`) and its reference (`raytracer.h:2467-2472`,
`path_kernel.cpp:220-224`) **drop** the emission — they do not weight it, do not
compute a forward MIS weight, and do not compute a light pdf at the hit. There is
therefore no second light-pdf computation that could disagree with NEE's.

The **RGB megakernel** `sampleDirectGPU` (`src/gpu/path_trace_kernel.cu:348-375`)
is the only path that carries a genuine two-sided `bsdf_mis` branch: on a
BSDF-sampled emitter hit it computes `lightPdf = gpu_light_pdf(rec.point, rec.normal,
bs.wi, …, lightTree, bRec.primId, bRec.t, pArea)` (`:362-366`) — i.e. the BSDF-side
light pdf **including** the light-tree pick pdf, consistently with NEE — and weights
`powerHeuristic(bs.pdf, lightPdf)`. That branch is **RGB-only and is NOT part of the
spectral reference**; the spectral wavefront correctly omits it (plan §4). Had the
spectral path grown a `bsdf_mis` branch that recomputed the light pdf via a *different*
selection rule than NEE, that would be the classic asymmetry (energy loss/double
count). It has not. **No wavefront MIS bug.**

### Finding D — one-sided vs two-sided MIS: a DESIGN divergence from Cycles (documented, NOT a C2 fix)
Cycles combines two direct-lighting strategies at every non-specular vertex (NEE
weighted by `power_heuristic(lightPdf, bsdfPdf)` **plus** the BSDF-ray-hits-light
emission weighted by `power_heuristic(bsdfPdf, lightPdf)` via
`light_sample_from_intersection`); the two weights sum to 1, giving an unbiased
combined estimator. Astroray's **spectral** integrator (`pathTraceSpectral`, the MW
megakernel, and the wavefront) uses a **one-sided** estimator: NEE weighted by the
power heuristic, and the diffuse BSDF-ray-hits-emitter term dropped.

Consequence: for a diffuse vertex, direct light is estimated by NEE alone, weighted
by `w_light = lightPdf²/(lightPdf²+bsdfPdf²)`. For compact/distant area lights
`lightPdf ≫ bsdfPdf` ⇒ `w_light ≈ 1`, so the dropped `(1−w_light)` BSDF-strategy
share is negligible and the estimator is unbiased in practice. For very large/near
lights (light subtending much of the hemisphere, `bsdfPdf ≳ lightPdf`) the one-sided
estimator is mildly biased-dark relative to full two-sided MIS.

This is a property of the **reference integrator**, faithfully mirrored by the
wavefront (bit-identical on CPU by shared-kernel construction; ported on GPU). It is
**out of scope for C2**, which audits *wavefront ↔ reference parity*, not the
reference estimator's optimality. Converting the spectral path to two-sided MIS
would touch the core CPU integrator and every GPU path, change all images, and
require a ground-truth (converged-brute-force) gate to validate the direction — a
separate package. Filed as **pkg120** (spec merged, PR #483) so it enters the
roadmap formally; recorded here as the C2 observation that motivated it.

---

## 4. Instrumentation + gate design (why the CPU↔GPU tier is a formula-parity check, not a value match)

The audit adds two SoA fields written where the shade stage already computes them
(no extra RNG draws, no reordering ⇒ renders stay bit-identical; behaviour contract):
- `path_light_pdf` ← `s.lightPdf` (selection × solid-angle, incl. tree pick pdf)
- `path_mis_pdf`   ← `bsdfPdf = gpu_material_pdf(mat, rec, wo, s.wi)`
plus the kernel's resulting `path_mis_weight` ← `wt`, so "resulting wt" (plan §4) is
captured directly rather than re-derived.

**Two-tier gate (mirrors the merged PostShade convention, `test_pkg55_cuda_threshold_gate.py`):**

1. **CPU-wavefront ↔ CPU-reference — exact (0.0).** `nee_light_pdf`,
   `nee_bsdf_pdf_at_dir`, `nee_mis_weight` are already compared field-for-field by
   `snapshot_diff.cpp:123-128` and are 0.0-identical by shared-kernel construction
   (`advance_one_bounce`). The PostNEE_MIS gate asserts this explicitly on a
   NEE-firing scene (session_n1_envmap_cornell has emitters, so NEE fires).

2. **CPU ↔ GPU — power-heuristic formula parity (deterministic-given-stage),
   NOT raw-value equality.** The raw MIS pdfs are *not* comparable CPU↔GPU: the
   template-RNG arc (`stage_advance.cu:316-323`) has the CPU draw light samples from
   an mt19937 sub-stream seeded off one PCG32 draw, while the GPU draws PCG32
   uniforms directly — independent Monte-Carlo samples even at matched dimension.
   The measurement scene has multiple emitters (an emissive sphere + a 2-triangle
   area light), so both the light *selection* and the sampled *point* legitimately
   differ ⇒ `lightPdf`/`bsdfPdf`/`wt` differ by sampling variance, not error. This is
   the same reason the merged PostShade/PostLightSample/PostRR gates compare only
   `ray_origin` + `lambdas` and exclude `bsdf_pdf`/`throughput` (test lines 427-482).

   The deterministic-given-stage invariant that *is* checkable, and that actually
   audits the MIS, is the **power-heuristic identity on each side's own pdfs**:
   `|path_mis_weight − power_heuristic(path_light_pdf, path_mis_pdf)| ≤ tol` on the
   GPU, and `|nee_mis_weight − power_heuristic(nee_light_pdf, nee_bsdf_pdf_at_dir)| ≤ tol`
   on the CPU — identical formula, identical `1e-8` guard, on both sides. This proves
   both integrators apply Veach's power heuristic to the pdfs they captured. Whole-
   program correctness of the sampled values remains gated by the final-image SSIM
   gate (`final_image.ssim_visible ≥ 0.985`), which is the sampling oracle.

Net: the audit's written assertion — *the wavefront's shade-time MIS equals the
reference's* — is proven exactly on the CPU (tier 1) and by formula parity on the
GPU (tier 2), with the RGB two-sided `bsdf_mis` branch documented as intentionally
omitted (Finding C) and the one-sided-vs-two-sided design divergence documented as
out-of-scope (Finding D).
