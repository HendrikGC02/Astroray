# pkg169 — Disney transmission energy-gain findings

**Status:** diagnosis complete; fix landed for both convictions; one residual cell
(CPU ior 1.5, R=1.0) pending an architect scope decision (multiscatter comp is a
spec non-goal, band-widening forbidden).

Base SHA for all measurements below: `e2bfd84` (current main; spec baseline was
`cf67a92`, re-confirmed to reproduce — CPU delta 1.784, GPU rough → 2.296,
controls conserve). RTX 5070 Ti, linear render (`apply_gamma=False`), albedo=1,
white env, deterministic across 256↔1024 spp.

## Repo radiance-transport convention (stated per the spec's contract)

Astroray is a **radiance** path tracer. Under refraction, radiance scales by the
inverse-squared relative IOR: a ray crossing into a medium of relative IOR
`etap = etaT/etaI` carries radiance multiplied by `1/etap²` (PBRT-v4 §9.5.2,
"Radiance along rays that do refract must increase so that energy is preserved").
In the code `eta = etaI/etaT`, so the delta-transmission factor `eta² = 1/etap²`
is the correct radiance factor: `0.444` on enter (etap=1.5), `2.25` on exit
(etap=1/1.5); the pair telescopes to 1.0 over a closed enter→exit path.

The integrator forms throughput as `f_spectral / (pdf + eps)` with **no separate
cosine multiply** for any BSDF sample (raytracer.h ~2714). The convention is
therefore that `eval()` returns the BSDF value **with the incident cosine folded
in** (disney.cpp eval() ends with `result * NdotL`), and delta events fold the
cosine away analytically. Any lobe that returns a per-steradian BSDF without the
cosine is inconsistent with this convention — that is Conviction A bug #2.

## Conviction A — CPU, two single-scatter weight defects

### A1. Delta glass dropped the Fresnel common factor (furnace 1.784 at R=0)

`disney.cpp` sample() delta branch set:
- reflection `s.f = Vec3(1)` with `s.pdf = fresnel·transmission_`  → `f/pdf = 1/R`
- transmission `s.f = baseColor·eta²` with `s.pdf = (1-fresnel)·transmission_` → `f/pdf = eta²/T`

PBRT-v4 DielectricBxDF::Sample_f (smooth case): reflection `f = R/|cosθi|`,
`pdf = pr/(pr+pt) = R`; transmission `f = T/|cosθi| /etap²`, `pdf = pt/(pr+pt) = T`.
The book states the value and pdf "contain the common factor R or T, which cancels
when their ratio is taken." Astroray kept R/T in the pdf but dropped it from f, so
each interface behaved lossless-in-expectation and created energy.

**Fix:** reflection `s.f = Vec3(cannotRefract ? 1 : fresnel)` (TIR ⇒ R=1);
transmission `s.f = baseColor·eta²·(1-fresnel)`. → R=0 furnace 1.784 → 0.990.

### A2. Rough transmission missing the incident cosine (furnace ~1.10 at R≥0.1)

`roughTransmissionEval` returns the PBRT-v4 per-steradian BTDF
`D·(1-F)·G·|HdotI·HdotO|/(|cosI·cosO|·denom²)/etap²` and, being reached via an
early return in eval(), never gets eval()'s trailing `* NdotL`. The integrator
adds no cosine, so throughput was inflated by `1/|cosI|` (E[1/|cosI|] > 1 over the
furnace cone). Correct VNDF weight is `f·|cosI|/pdf = G1(cosI)/etap²`
(Heitz 2018 / PBRT-v4 DielectricBxDF).

**Fix:** fold `|cosI|` into the transmission scale. → R=0.1 furnace 1.099 → 0.993.

## Conviction B — GPU, closure-graph reflection-pdf Fresnel orientation

Disney glass lowers to `GMAT_CLOSURE_GRAPH` (scene_upload.cu). The closure-graph
sampler (`gpu_closure_graph_sample`) samples a direction via the disney sampler
(correct inline f/pdf) then **overwrites** `s.f`/`s.pdf` with a re-evaluated
`gpu_closure_graph_eval` / `gpu_closure_graph_pdf` — the standard one-sample-MIS
`f_total/pdf_total` estimator, which is legitimate.

A device-printf trace of sampled-vs-overwritten weights showed the overwrite is a
no-op for transmission samples but diverges by up to ~20× on **internal-reflection
events** (`frontFace=false`, same-hemisphere `cosO·cosI>0`): `pdfOvr` was far
smaller than `pdfSamp`. Root cause: `gpu_disney_pdf`'s reflection-branch Fresnel
used `entering = rec.normal.dot(wo) > 0` — **always true**, because `rec.normal` is
the front-facing (reoriented) normal. For an exit event it computed the air→glass
Fresnel (small) instead of glass→air (≈1 near TIR), so the reflection-branch pdf
was too small and `f/pdf` inflated. The sampler itself uses `rec.frontFace` for
etaI/etaT, so the overwrite disagreed with how the sample was drawn. The gain rises
with roughness because the internal-reflection fraction rises with roughness.

**Fix:** `entering = rec.frontFace` in `gpu_disney_pdf` (mirroring the sampler and
the pkg154 `roughTransmission{Eval,Pdf}` convention). The identical latent bug in
the CPU `disney.cpp pdf()` (line ~908) was fixed too — it does not affect the CPU
furnace (no closure-graph overwrite; the furnace uses the sampler's inline pdf) but
is wrong for NEE/MIS and must stay in parity with the GPU twin. The GPU delta
Fresnel fix (A1) and cosine fold (A2) were also mirrored into `gpu_materials.h`.
→ GPU R=1.0 furnace 2.296 → 0.930.

I did **not** skip the closure-graph overwrite (a superficially-working but broad
change that also masks the separate opaque-Disney defect below); the pdf-orientation
was the actual bug.

## Citation-to-line mapping

| Fix | File / function | Citation |
|---|---|---|
| A1 delta Fresnel | `plugins/materials/disney.cpp` sample() delta branch | PBRT-v4 §9.5 DielectricBxDF::Sample_f |
| A2 cosine fold | `plugins/materials/disney.cpp` roughTransmissionEval | Heitz 2018 VNDF; PBRT-v4 DielectricBxDF |
| B pdf orientation | `plugins/materials/disney.cpp` pdf(); `include/astroray/gpu_materials.h` gpu_disney_pdf | pkg154 frontFace convention; PBRT-v4 |
| A1/A2/B GPU mirror | `include/astroray/gpu_materials.h` gpu_disney_sample / gpu_disney_roughTransmissionEval | CPU twins above |

## Furnace results after fix (256 spp, linear, band [0.92,1.03])

```
ior 1.5   R= 0    0.03   0.1    0.3    0.6    1.0
  CPU     0.990  0.990  0.993  0.980  0.926  0.902   ← R=1.0 below 0.92 floor
  GPU     0.992  0.992  0.992  0.986  0.970  0.930   all in band
ior 1.33  CPU    0.991  0.991  0.993  0.989  0.980  0.980   all in band
ior 1.33  GPU    0.993  0.993  0.992  0.989  0.992  0.988   all in band
controls: plain dielectric 0.993 CPU / 0.992 GPU; opaque disney 0.959 CPU
```

`--runxfail` on `tests/test_disney_rough_glass_furnace.py`: 4 passed, 1 failed —
only `test_disney_rough_glass_furnace_energy_cpu` at R=1.0=0.9017.

## Residual (pending architect decision)

CPU ior 1.5 R=1.0 converges to 0.903 (256/1024 agree). Single-scatter alone is
0.717; pkg151 `ggxGlassCompensationFactor` recovers it to 0.903 but not to ≥0.92.
This is the **multiscatter/compensation family the spec lists as a non-goal**, and
band-widening is forbidden — so it is not touched here. GPU lands at 0.930 (in
band) via the closure-graph one-sample-MIS estimator; the CPU direct estimator
converges ~3% lower — a residual CPU/GPU parity nuance, vastly improved from the
baseline 1.260 vs 2.296.

## Separate out-of-scope finding

GPU **opaque** Disney (metallic=0, transmission=0) furnaces at 1.975 — a flat ~2×
gain across all roughness, present on base main independent of pkg169. It also
stems from the closure-graph re-eval overwrite, but on the diffuse+conductor lobe
recombination (skipping the overwrite drops it to 0.987). CPU opaque conserves
(0.959). A real GPU energy-conservation bug in non-transmissive Disney, outside
pkg169's transmission scope — recommend a new spec.
