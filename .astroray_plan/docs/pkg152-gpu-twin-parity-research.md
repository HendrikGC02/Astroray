# pkg152 — GPU Disney twin divergence: instrumentation findings

**Spec:** `.astroray_plan/packages/pkg152-gpu-disney-metal-residual-dimness.md`
**Method:** static side-by-side audit (CPU `disney.cpp` vs GPU `gpu_materials.h`,
line-for-line, per the pkg141 precedent) + targeted render-level measurement
(per-channel GPU/CPU mean ratios), per the spec's "convict before fixing"
contract. No live per-event GPU printf harness was built — the divergence
convicted analytically (confirmed-absent code path) and empirically
(measured before/after) without one; the render-level A/B tests are strong
enough evidence for a confirmed-absent-vs-present code path.

## Two symptoms, two DIFFERENT convicted mechanisms (split-clause fires)

The spec's split-clause: "if instrumentation proves the two symptoms have
unrelated mechanisms, fix the #522 blocker here and split the metal
remainder back out as its own package." Confirmed unrelated:

- Symptom (a) metal residual dimness — convicted mechanism (mirrored,
  fixed): `gpu_disney_eval` (`include/astroray/gpu_materials.h`) never
  applied CPU `disney.cpp::eval()`'s Kulla & Conty 2017 multi-scatter
  compensation (`ggxCompensationFactor`), diffuse-under-specular layering
  (`ggxDirectionalAlbedo`/`layeringWeightAfter`), the pkg60 grazing
  diffuse-furnace normalization (`diffuseFurnaceScale`), or the
  sheen/clearcoat table lookups. Confirmed by `grep` returning zero matches
  for any of these names in `gpu_materials.h` prior to this package.
- Symptom (b) the #522 GPU-only rough-transmission furnace deficit —
  DIFFERENT mechanism, in a completely different function
  (`gpu_material_sample_spectral`, the multi-wavelength BSDF-sample
  upsampling wrapper) — see below. The missing symptom-(a) compensation
  terms measured a **zero effect** on symptom (b) (bit-identical furnace
  numbers before/after mirroring them), empirically falsifying the spec's
  hypothesis-1 lead for symptom (b) specifically (it remains the correct
  lead for symptom (a)).

## Symptom (a): missing GPU compensation/layering mirror

### What was checked and ruled out first

Side-by-side, byte-for-byte comparison of `gpu_disney_eval`/`gpu_disney_
sample`/`gpu_disney_pdf`/`gpu_disney_sampleGgxVNDF`/`gpu_disney_
refractMicro` against their CPU twins in `disney.cpp` found these
IDENTICAL (formulas, constants, epsilons, branch structure) — not the
mechanism:

- D_GTR2, smithG_GGX/smithG1_GGX, fresnelSchlick/fresnelDielectric.
- The VNDF sampler (`sampleGgxVNDF`) including pkg149's own azimuth-swap
  fix — already correctly mirrored to GPU.
- `buildOrthonormalBasis` (CPU, `raytracer.h:99`) vs `gpu_buildONB`
  (`gpu_materials.h:18`) — identical formula, ruling out a tangent-frame
  handedness/orthonormality bug.
- The closure-graph routing for a metallic=1.0 Disney material (single
  `GGXConductor` closure, `disneyMetalConductor` flag routes it to
  `gpu_disney_eval`, not `gpu_metal_eval` — pkg141's own fix, confirmed
  still in place and correctly exercised).

### Convicted: the missing compensation/layering terms

`grep -c "ggxCompensationFactor\|ggxDirectionalAlbedo\|layeringWeightAfter\|
diffuseFurnaceScale\|table_ggx_E\|DisneyEnergyCompensationTables"
include/astroray/gpu_materials.h` returned 0 prior to this package,
despite `disney.cpp::eval()` applying all four to every non-delta lobe
(pkg60/pkg118/pkg138/pkg145 series, CPU-only fixes, per pkg141's own
Lessons entry that first flagged this).

### Port

New `include/astroray/gpu_ggx_tables.cuh` / `src/gpu/gpu_ggx_tables.cu` —
mirrors the pkg151 `gpu_glass_tables.cuh`/`.cu` upload pattern exactly
(device global-memory tables, `uploadGgxTables()` one-time host upload,
called from `cuda_renderer.cu` alongside `uploadGgxGlassTables()`). Backs
device-side lookups for the existing CPU tables (`ggx_E.bin`, `ggx_Eavg.
bin`, `sheen_E.bin`, `clearcoat_E.bin` — already in `data/disney_
compensation/`, pkg60/pkg145 provenance, unchanged). New host-side
accessors `DisneyEnergyCompensationTables::{ggxEData,ggxEavgData,
sheenEData,clearcoatEData}()` (`include/astroray/energy_compensation.h`)
mirror the existing `ggxGlassEData()` etc. accessors pkg151 added.

`gpu_disney_eval` wired to mirror `disney.cpp::eval()`'s ordering exactly:
diffuse * `diffuseFurnaceScale`; sheen layering (`layeringWeightAfter`);
clearcoat layering; `spec *= ggxCompensationFactor(...)`; diffuse-under-
specular layering (`ggxDirectionalAlbedo` + `layeringWeightAfter`);
final composition `baseLayer = diffuse*diffuseLayerWeight + spec*
lowerLayerWeight`.

### Second bug found via the spec's hypothesis 3 sweep

Hypothesis 3 asked: "verify no OTHER stale denominator/epsilon remains in
the newly-reachable `gpu_disney_eval` path" (the pkg141 precedent: a stale
`/(4*NdotL*NdotV+0.001f)` divide on the `spec` term, already fixed by
pkg141). Auditing the clearcoat term while adding the layering code found
an IDENTICAL, still-present stale divide + a wrong constant:

```
// before (gpu_materials.h, pre-pkg152):
GVec3 ccTerm = GVec3(mat.clearcoat * Dr * Fr * Gr
                     / (4.f*NdotL*NdotV + 0.001f)) * 0.5f;
// CPU disney.cpp (canonical):
Vec3 clearcoatTerm = Vec3(clearcoat_ * Dr * Fr * Gr) * 0.25f;
```

`Gr` uses the same combined-visibility `gpu_smithG_GGX` form as `Gs` (the
metal spec term pkg141 already fixed) — it already folds in the
`1/(4*cosO*cosI)` factor, so the extra divide double-counts it, AND the
`0.5` should be `0.25` (a second, independent constant error). No test in
the repo currently exercises `clearcoat > 0` on GPU (the pkg123 metal-
parity scene's default is `clearcoat=0`), so this bug was latent/
unmeasured, not a driver of the pkg141 measured ratios — fixed anyway,
same double-divide bug class, GPU-only (CPU `disney.cpp` untouched).

### Measured (RTX 5070 Ti, `tests/test_pkg123_disney_metal_gpu_cpu_
parity.py`, metallic=1.0 sphere, `[0.9,0.6,0.4]` base color)

| roughness | pre-fix ratio (R,G,B) | post-fix ratio (R,G,B) |
|---|---|---|
| 0.00 | 0.6034 / 0.6892 / 0.7565 | 0.6034 / 0.6892 / 0.7565 (unchanged) |
| 0.03 | 0.6034 / 0.6892 / 0.7565 | 0.6034 / 0.6892 / 0.7565 (unchanged) |
| 0.05 | 0.6034 / 0.6892 / 0.7565 | 0.6034 / 0.6892 / 0.7565 (unchanged) |
| 0.10 | 0.6215 / 0.7066 / 0.7675 | 0.6215 / 0.7066 / 0.7675 (unchanged) |
| 0.30 | 0.8628 / 0.9140 / 0.9377 | 0.9984 / 0.9966 / 0.9907 |
| 0.60 | 0.8570 / 0.9132 / 0.9422 | 1.0000 / 1.0000 / 1.0000 |
| 0.90 | 0.6392 / 0.7948 / 0.8857 | 1.0025 / 1.0008 / 0.9985 |

Mid/high-roughness (0.3-0.9) essentially closed. Near-delta (<=0.10) is
**bit-identical to pre-fix** — the `ggxE`/`ggxEavg` table lookups at the
alpha floor (`max(roughness^2, 0.0064)`) return E close to 1.0 (a smooth
GGX lobe has no micro-occlusion energy loss to compensate for, per Kulla &
Conty 2017 theory — the compensation factor `1 + Fms*(1-E)/E -> 1` as
`E -> 1`), so the mirrored term has essentially zero effect there,
confirming both theoretically and empirically that this is NOT the
near-delta mechanism.

### Near-delta metal dimness (roughness <= 0.10): UNRESOLVED, split out

The 0.60-0.77 near-delta ratio is unchanged by this fix and its root
cause is NOT identified by this package. Candidates not yet ruled out:
something in the plain-NDF (non-VNDF) specular importance sampler used for
the metal's non-transmission specular branch (`gpu_disney_sample`'s
`else` branch, `gpu_materials.h` ~975-998) at very small alpha; or a
precision/epsilon effect specific to the near-delta D_GTR2 peak. Per the
spec's split-clause, this remainder is reported here for the architect to
file as a follow-up package rather than blocking the #522 fix below.

## Symptom (b): the #522 GPU-only low-roughness furnace deficit

### What was checked and ruled out first

On the `pkg149-rough-transmission-sample-pdf` branch (`e0fe9d8`, the #522
draft stack), a full line-for-line comparison of `gpu_disney_
roughTransmissionEval`/`Pdf`/`gpu_disney_roughReflectionEval`/
`gpu_disney_sampleGgxVNDF`/`gpu_disney_refractMicro` against their CPU
twins (post pkg149's azimuth fix + pkg154's frontFace/clamp-removal
fixes) found them **byte-identical** — same formulas, same citations, same
epsilons. This matches the e0fe9d8 commit author's own "full side-by-side
audit" note. The missing symptom-(a) compensation terms were measured to
have **zero effect** on this deficit (furnace numbers bit-identical before/
after mirroring them onto the #522 stack) — this DIRECTLY falsifies the
spec's leading hypothesis for symptom (b) (it was speculated, now measured).

### Convicted: `gpu_material_sample_spectral`'s delta-only magnitude guard

The furnace test renders via the **multi-wavelength** path (`[CUDA] MW
render complete` in the test log — `Renderer.render()` dispatches to
`renderMultiwavelength`, not the plain RGB megakernel), so the BSDF sample
consumed by the path tracer's throughput accumulation is NOT `s.f`
directly but `s.fSpectral`, produced by `gpu_material_sample_spectral`
(`gpu_materials.h`). CPU's equivalent wrapper, `Material::sampleSpectral`
(`include/raytracer.h:580-611`), was fixed by pkg118/PR#404's lineage to
factor out any BSDF-value magnitude greater than 1.0 (a legitimate
radiance-transport `eta^2` factor, e.g. 2.25 at ior=1.5 on a transmission
exit event) as a flat spectral scalar BEFORE spectral upsampling — because
the ALBEDO-mode Jakob-Hanika upsampler clamps its RGB input to `[0,1]`, so
an un-factored magnitude >1 is silently clipped back to 1.0, losing
exactly the missing energy. CPU's comment states this explicitly for BOTH
the delta AND non-delta (rough) branches: *"Same eta^2-clamp guard for the
rough (non-delta) glass lobe: the rough transmission eval also exceeds 1
on exit, and the albedo LUT would clip it."*

GPU's `gpu_material_sample_spectral` had this guard **DELTA-ONLY**:

```
// before:
if (s.isDelta && m > 1.0f) { factor-and-rescale }
else                       { direct upsample (clips magnitude>1!) }
```

For rough (non-delta) Disney-glass transmission — exactly `_ROUGH =
[0.1, 0.3, 0.6, 1.0]`, the gate's own grid — every exit event with
`f > 1.0` (a legitimate, unbiased, un-capped estimator value at low
roughness once pkg154's closure-level-clamp removal makes the heavy
D_GTR2 tail reachable) took the `else` branch and had its magnitude
silently clipped to 1.0 by the ALBEDO Jakob-Hanika LUT before even
reaching the accumulation loop — the multi-wavelength analog of the
`#404`/pkg118 bug, on the ONE code path (rough, not delta) that #404
itself did not touch (that PR predates the rough VNDF transmission
lobe). The deficit is worst at low roughness because the un-capped
D_GTR2 tail (removed by pkg154) is heaviest there, producing the largest
un-factored magnitudes; it shrinks toward roughness=1.0 as the lobe
flattens — exactly the observed profile (R=0.1/0.3 failing, R=0.6 a near
miss, R=1.0 passing).

### Fix

One-line condition change, `gpu_materials.h::gpu_material_sample_
spectral`: drop the `s.isDelta &&` guard so the magnitude-factoring
applies whenever `m > 1.0f`, regardless of delta/non-delta — this is a
pure superset of the prior behavior (identical for every case that
previously worked; only newly fires for the previously-unguarded
non-delta `m > 1.0` case).

### Measured — THE decisive #522 gate

On the #522 stack (pkg149 azimuth fix + pkg151 compensation + pkg154
frontFace/clamp fixes + this package's compensation mirror AND this fix),
measured on a local throwaway branch (`git diff origin/main
origin/pkg149-rough-transmission-sample-pdf -- plugins/materials/
disney.cpp include/astroray/gpu_materials.h` applied cleanly on top of
this package's commit):

| roughness | pre-fix GPU | post-fix GPU | CPU (same stack) | gate [0.90,1.06] |
|---|---|---|---|---|
| 0.05 | (not gated pre-fix) | 0.998757 | 0.998624 | PASS |
| 0.10 | 0.129525 | 0.998741 | 0.998593 | PASS |
| 0.30 | 0.283335 | 0.999264 | 0.998739 | PASS |
| 0.60 | 0.896775 | 1.000000 | 0.998513 | PASS |
| 1.00 | 1.000000 | 1.000000 | 0.996989 | PASS |

`test_disney_rough_glass_furnace.py` (5/5), `test_pkg123_disney_metal_gpu_
cpu_parity.py` (7/7), `test_gpu_caustic_parity.py` (1 passed, 1 xfailed —
pre-existing) all green on the same stack + both pkg152 fixes.

## Citations (CLAUDE.md §6)

- Kulla, C. & Conty, A. (2017). "Revisiting Physically Based Shading at
  Imageworks," SIGGRAPH Course Notes — the `1 + Fms*(1-E)/E` compensation
  and Eq. 6-9 layering formulation; already the CPU `disney.cpp` citation,
  mirrored verbatim.
- Blender Cycles `intern/cycles/kernel/closure/bsdf_microfacet.h`
  (`microfacet_ggx_preserve_energy`, BSD-3-Clause), `bsdf_util.h`
  (`closure_layering_weight`, Apache-2.0) and `src/kernel/svm/closure.h`
  (Apache-2.0) — production cross-reference for the same terms; already
  cited in `disney.cpp`, mirrored here to the GPU port.
- pkg60/pkg118/pkg138/pkg145 (in-repo, `disney.cpp`) — the original CPU
  derivations/measurements this package ports verbatim; no new algorithm
  invented.
- pkg118/PR #404 lineage (in-repo, `raytracer.h::Material::sampleSpectral`,
  `gpu_materials.h::gpu_material_sample_spectral`'s existing delta-branch
  comment) — the eta^2-radiance-transport / ALBEDO-LUT-clamp mechanism this
  package's symptom-(b) fix extends to the non-delta branch; the mechanism
  itself (and its citation trail, Veach 1997 non-symmetric scattering) is
  unchanged, this package only widens an existing guard's condition.
