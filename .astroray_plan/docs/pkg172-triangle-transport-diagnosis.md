# pkg172 — diagnosis: the residual is NOT triangle-specific; it decomposes into (A) a universal ~0.6%/bounce diffuse epsilon energy-loss + (B) a separate GPU-only ~0.4% loss that owns pkg156

**Date:** 2026-08-02 (RTX 5070 Ti). **Branch:** pkg172-triangle-transport-bias
(base 80d4ec0, #541 not merged — findings below use NEUTRAL albedo, which is
#541-independent per pkg168 Step 2). **No fix applied — escalating.**

## The spec's premise is falsified, and all three named candidates are cleared

**(1) NOT triangle-specific.** With a clean full-frame single-bounce measurement
(camera face-on, uniform white env, spp 16384), a **sphere and a triangle wall
give the IDENTICAL ratio** 0.99570 (per-channel, neutral albedo 0.5). My pkg168
Step-2 "sphere-clean / triangle-dirty" reading was a camera/depth/masking
confound (the sphere and floor probes used different camera heights and path
depths). The bias is geometry-INDEPENDENT.

**(2) Candidate (c) epsilon — CLEARED.** Scratch rebuild with the throughput
epsilon `f/(pdf+1e-3)` → `1e-6` on BOTH legs left the ratio unchanged (0.99587 →
0.99590). Not the epsilon.

**(3) Candidates (a)/(b) normal/cosθ — CLEARED.** The bias is achromatic,
depth-independent (constant 0.99587 across depth 2–8 on a flat wall — no
multi-bounce, no off-by-one), and identical for sphere vs triangle. Both legs use
the normalized face normal + matching `frontFace`; a mis-normalized or non-ONB
frame cancels in `f/pdf` anyway.

Also ruled out by inspection/measurement: the JH upsampling tables (Step 1,
neutral matches to 1.000000), the diffuse closure weight (=1.0), the GPU contrib
clamp (`clampDirect/Indirect` default 0 = identity). (toXYZ/CMF NOT yet cleared —
now a prime suspect for effect (B); see below.)

## CORRECTION (clean rebuild) — the table below the line was contaminated

My first cross-check ran against a stale `.pyd`: after the epsilon probe I
reverted the SOURCE but did not rebuild, so the run used a build where the epsilon
was zeroed in `multiwavelength_path_tracer` (line 238) + GPU `stage_advance` (685)
but NOT in `path_tracer` (`raytracer.h:2549`). That falsely made CPU-mw read
0.500 "analytic-exact." RETRACTED. Corrected numbers (clean build, epsilon 1e-3
everywhere):

| integrator | reflected luminance | vs analytic 0.5 |
|---|---|---|
| CPU `multiwavelength_path_tracer` | [0.49699, 0.49777, 0.48845] | −0.6% |
| CPU `path_tracer` | [0.49699, 0.49777, 0.48845] | −0.6% (BIT-IDENTICAL to mw) |
| GPU wavefront (naive) | [0.49486, 0.49572, 0.48652] | −1.0% |

## The real structure: TWO separate effects

**(A) Universal ~0.6%/bounce diffuse energy loss — the `f/(pdf+1e-3)` epsilon.**
All three legs undershoot the analytic 0.5 by ~0.6% (CPU-mw == CPU-pt
bit-identical). An additive `1e-3` epsilon on a cosine-sampled diffuse pdf loses
exactly `2π·eps ≈ 0.628%` (E[1/cosθ]=2 over the cosine-weighted hemisphere),
matching to the digit; rebuilding at `1e-6` restores 0.500. **The pkg156 oracle
(CPU-mw) is NOT exempt — my earlier claim is RETRACTED.** This confirms the
architect's BRANCH-1 that a real ~0.6%/bounce loss exists; it is universal.
Fixing it brightens ALL diffuse ~0.6%/bounce → the large coordinated re-pin.

**(B) A separate GPU-only extra ~0.4% loss.** The GPU (0.495) sits below the
bit-identical CPU legs (0.497) even with the GPU `stage_advance` epsilon set to
`1e-6` — a DISTINCT second GPU site, upstream of the throughput update. Because
(A) cancels in the GPU/CPU ratio, **(B) — not (A) — is what the pkg156 gate ratio
(0.9957) measures.** Fixing (A) alone does NOT restore pkg156; pkg156 needs (B).

Cleared for (B): the cosine samplers are byte-identical (CPU
`Vec3::randomCosineDirection` == GPU `gpu_randomCosineDir`); GPU `f/pdf = albedo`
exactly for the single diffuse closure lobe; CMF/toXYZ share the SAME
`data/spectra/cie_cmf.inc` and MC formula; D65 norm matches (direct-bg render is
clean); the contrib clamp is default-off (identity). Every component provably
matches, yet the GPU is a stable ~0.4% low on one diffuse bounce.

**New clue — (B) is ALBEDO-DEPENDENT** (single bounce, white env, GPU/CPU ratio):

| albedo | GPU/CPU | abs deficit |
|---|---|---|
| 0.5 | 0.99589 | 0.00213 |
| 0.8 | 0.99700 | 0.00252 |

A pure throughput epsilon would give an albedo-INDEPENDENT fractional loss, so (B)
is NOT a scalar epsilon — it is a spectral-shape / spectral-product / toXYZ-
interaction effect that depends on the upsampled albedo spectrum's shape. Since
every static component matches, convicting (B) to a line now requires per-hit GPU
instrumentation ([pkg172-diag] kernel printf of throughput, envSpec, and the
per-λ contribution + XYZ for one pixel/sample, diffed against the same on CPU) —
a focused instrumented build, recommended as the next step. (B) owns pkg156.

## UPDATE 2 — (B) split further: single-bounce (B)=#541; a distinct MULTI-BOUNCE (B') remains

Cherry-picking #541 (commit 19fb009) onto pkg172 + clean rebuild (`.pyd` mtime
1785649939 > HEAD e9d2034 ctime 1785649784) shows:

- **Single-bounce (B) IS #541.** Face-on wall, single diffuse bounce, GPU/CPU:
  0.9959 → [0.99988, 1.00005, 1.00021] for every albedo. The "GPU-only 0.4% site"
  was the pkg168 Step-2 upsample-of-pre-scaled-value bug, small for neutral
  albedo. #541 fixes it. **pkg156 needs #541 merged.**

- **A separate MULTI-BOUNCE residual (B') survives #541.** pkg156 room gate WITH
  #541 present is still [1.016, 1.010, 1.016] / SSIM 0.9955. Minimal reproducer
  (grey albedo 0.6, grey env, #541 present, GPU/CPU): single floor 1.0096 (const
  across depth); corner/2-walls 1.0145 (d4); box/4-walls 1.0368 (d4), 1.063 (d2).
  Divergence scales with inter-reflection and is GPU-BRIGHTER.

Ruled out for (B'): epsilon (probe negative), the JH tables (Step 1), the
per-bounce throughput (invariant `throughput_after/before == albedo` holds exactly
per-path on both legs regardless of RNG), and simple occlusion parity — a ceiling
occluder REDUCED the divergence (floor 1.0096 → floor+ceiling 1.001 @d4), the
opposite of an under-occlusion story. The effect is strongly config-sensitive
(face-on clean; grazing/multi-bounce diverge), which points at a path-length /
escape-distribution or camera/first-hit interaction rather than a single
per-bounce factor. Convicting it requires a per-hit deterministic trace (per-path
bounce-count + throughput + escape, GPU vs CPU) — a focused instrumented build,
NOT rushed (this session already hit one un-rebuilt-revert contamination error).

## UPDATE 3 — per-hit trace: (B') is an ESCAPE-DISTRIBUTION / first-hit geometry difference, not a per-bounce transport term

[pkg172-diag] device-printf (GPU env-miss) + fprintf (CPU env-miss), dumping the
escape bounce# and throughput-at-escape, on the actual pkg156 scene (12×12, 64
spp, #541 present; diag since removed). Escape throughput summed by bounce:

| bounce | CPU Σthr | GPU Σthr | GPU/CPU | CPU events | GPU events |
|---|---|---|---|---|---|
| 0 (camera direct-miss) | 634.0 | 661.0 | 1.043 | 634 | 661 |
| 1 (one diffuse bounce → escape) | 3204.3 | 3581.3 | **1.118** | 5769 | 6115 |
| 2 | 148.9 | 157.0 | 1.055 | 1215 | 1331 |
| 3 | 30.6 | 33.9 | 1.108 | 455 | 511 |
| total | 4017.8 | 4433.3 | 1.103 | 8073 | 8618 |

The divergence is DOMINATED by **bounce-1 escapes** (+11.8%), which splits into
two geometric effects: GPU has ~6% MORE bounce-1-escape events (6115 vs 5769 —
more rays escape to the background after one bounce) AND ~5.5% higher throughput
per escape (0.586 vs 0.555). Since #541 makes per-surface throughput match
(single-bounce wall is bit-clean), the higher per-escape throughput means GPU
rays land on a BRIGHTER distribution of surfaces, and the extra events mean more
rays escape after one bounce rather than hitting a second surface.

**Both are camera-ray / bounce-ray GEOMETRY-SAMPLING differences (which surface
is hit / whether the continuation ray escapes), NOT a spectral or per-bounce
transport term.** This is the same family as the documented, accepted GPU
camera-ray simplification (stage_init.cu: GPU uses a simplified lens/filter, not
CPU std::mt19937 — pkg55 accepted a ≤4-ULP PostInit geometry difference). It
persists at 8192 spp (the gate's [1.016]), so it is a systematic direction/hit
bias, not sample jitter.

**Implication:** (B') is likely NOT a surgical transport fix — it is CPU↔GPU
geometry-sampling parity (camera-ray + BVH continuation-ray hit distribution).
Fixing it means reconciling the GPU's ray generation / intersection with the CPU
oracle, which touches the accepted ≤4-ULP simplification and the BVH. Recommend
architect input before implementing: this is a parity-of-samplers question, not a
one-line term, and may be a fundamental precision limit rather than a bug. pkg156
stays 0.995. #541 must still merge (fixes the single-bounce component).

## Status

- **(A) convicted** (epsilon; `2π·eps` math + `1e-6` probe → 0.500). Fix =
  guarded pdf at the sample site (pbrt-v4: reject when `pdf==0`, divide by the
  true pdf; never an additive bias). Broad re-pin sweep + architect sign-off
  before push.
- **(B) located** as a distinct GPU-only site, not yet convicted to a line; owns
  the pkg156 restoration.
- **pkg156 stays at 0.995; no re-pin** until (B) is fixed and measured full-scene.
- Shared −1.7% B-channel deficit vs analytic across all three legs: separate
  sensor/illuminant-normalization question, flagged for a future filing.

## pkg153 intel

No fix applied, so no movement to report. But the discriminator is now sharper:
pkg153's drift is CHROMATIC/emitter-linked; this is ACHROMATIC and present with no
emitter (env-only). Distinct mechanisms, consistent with the scope fence.
