# pkg188 — Principled residual spectral-consistency gaps (JH-nonlinearity + clamp class)

**Pillar:** 3/5 (spectral consistency / CPU-GPU parity)
**Track:** A
**Status:** open (found 2026-08-12 during the post-pkg178/pkg182 spectral-
integration audit; **enhancement tier — start after PR #586 lands**)
**Estimated effort:** M
**Depends on:** PR #586 (must land first); pkg168 (RGB→spectral upsampling
parity — the fix template); pkg167 / [[rough-glass-residual-is-multiscatter]]
(the eta² LUT-clamp bug class).

---

## Symptom

Three residual spots where the native Principled BSDF still does spectral math
in the RGB-then-upsample-the-product form that pkg168 already proved wrong for
diffuse. These are **enhancement-tier** — they are not producing a visible
failure today the way pkg187's dispersion does, but they are the exact
nonlinearity/clamp classes the project has repeatedly been bitten by, and they
undermine the "native Principled is spectrally consistent" claim.

### Finding A — film-off transmission still upsamples the product

Film-off transmission is the **only core lobe still evaluated in RGB and then
upsampled as a product** — self-labelled the "Stage-3b upsample hack":
- `plugins/materials/principled.cpp:1648-1658`
- GPU twin `include/astroray/gpu_materials.h:2407-2416`

This is the exact JH-nonlinearity class pkg168 fixed for diffuse
([[spectral-upsample-nonlinearity-scaled-bsdf]]: JH upsampling is nonlinear in
magnitude — upsample the reflectance *colour*, never `albedo·cosθ/π` or a
product). Apply the pkg168 fix shape to the transmission lobe.

### Finding B — assembleLobes multiplies in RGB then upsamples once

`assembleLobes` (`plugins/materials/principled.cpp:658-868`) multiplies base
colour × sheen tint × coat Beer × layering albedos **in RGB**, then upsamples
the product a single time. `upsample(a·b) ≠ upsample(a)·upsample(b)` (the same
nonlinearity as Finding A, at the lobe-assembly level).

Additionally, `upsample()` **clamps to [0,1] with no maxc guard on the weight
path** — the same clamp class as the pkg167 / rough-glass eta² ALBEDO-LUT-clamp
bug ([[rough-glass-residual-is-multiscatter]]: the JH ALBEDO LUT clamps rgb>1,
silently clipping energy). Any weight/product that can exceed 1 before upsample
loses energy here.

### Finding C — thin-wall R'/T' per-channel + GPU delta events (may be descoped)

Listed for completeness; the implementer may **explicitly descope** this to a
follow-up if A+B already consume the package budget:
- Thin-wall R'/T' is per-RGB-channel with a film-on RGB sensitivity LUT (not
  per-λ native).
- GPU delta Principled events **never fill `fSpectral`** (generic maxc/upsample
  guard at `gpu_materials.h:3214`), mirroring the CPU side.

If descoped, file the C follow-up spec at close and note it in Lessons — do not
leave it as an unrecorded gap.

---

## Hard constraint — do not spill the fused shade kernel

Any change **must keep the `<false>` shade-kernel specialization at STACK 3608 /
REG 254** ([[closure-graph-lobe-count-spills-fused-kernel]]: adding Principled
lobes spilled the SHARED shade kernel and caused a +52% non-Principled
regression; the fix was `template<bool HasPrincipled>` if-constexpr isolation,
**not** shrinking the lobe array). **All new per-λ work goes inside the
`HasPrincipled` branch.** Verify with cuobjdump post-link + `ASTRORAY_PROFILE`
(not `ptxas -v`; [[wavefront-shade-kernels-register-saturated]]) and report the
`<false>`-specialization STACK/REG before and after.

---

## Work

1. **Finding A:** rewrite the film-off transmission lobe
   (`principled.cpp:1648-1658` + GPU twin `gpu_materials.h:2407-2416`) to
   upsample the reflectance colour, not the product, per the pkg168 shape.
2. **Finding B:** in `assembleLobes` (`principled.cpp:658-868`), move the
   colour × tint × Beer × layering multiply so upsampling happens on the colours
   (or restructure so the product is not upsampled once); add a maxc guard on the
   weight path before `upsample()` so weights >1 are not clipped.
3. **Finding C:** either implement per-λ thin-wall R'/T' + GPU `fSpectral` fill,
   or descope with a filed follow-up + Lessons note.
4. Re-verify CPU/GPU per-channel parity and furnace energy (linear, with an
   upper bound — [[gamma-furnace-cannot-detect-energy-gain]]) on Principled
   transmission and layered-Principled scenes.

## Acceptance criteria

- [ ] Finding A: transmission lobe upsamples colour, not product; CPU and GPU
      twin both updated; a parity test locks it.
- [ ] Finding B: assembleLobes no longer upsamples an RGB product; weight-path
      maxc guard added; furnace energy conserves (linear, bounded above).
- [ ] Finding C: implemented, or descoped with a filed follow-up spec number
      recorded in Lessons.
- [ ] `<false>` shade-kernel specialization STACK/REG unchanged (3608/254),
      shown via cuobjdump before/after; no non-Principled perf regression
      (min-of-N, burn-in per [[gpu-perf-ab-clock-drift]]).
- [ ] CPU/GPU per-channel mean-ratio parity within band on the Principled
      transmission + layering scenes.

## Hard non-goals

- **No lobe-array shrink** to buy register room — the fix is if-constexpr
  isolation inside `HasPrincipled`, never shrinking shared state.
- **No re-opening reflection/metal spectral work** (pkg182/pkg163 settled those);
  this package is transmission + lobe-assembly + delta-event `fSpectral` only.
- **No start before PR #586 lands** — this is explicitly enhancement-tier and
  sequenced behind it to avoid conflicting edits in `principled.cpp`.
