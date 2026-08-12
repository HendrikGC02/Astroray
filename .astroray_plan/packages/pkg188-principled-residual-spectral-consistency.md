# pkg188 — Principled residual spectral-consistency gaps (JH-nonlinearity + clamp class)

**Pillar:** 3/5 (spectral consistency / CPU-GPU parity)
**Track:** A
**Status:** done (PR #599, 2026-08-12 — Findings A+B landed: transmission
colour/scalar separation + weight-path clamp guard, CPU+GPU; `<false>` kernel held at
3608/254/1700; CPU/GPU parity ≤1.02, glass furnace 0.955 no-gain; residual up to ~72%
band error on coloured-tint-over-dark-base → pkg194. Finding C descoped to pkg194.)
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

---

## Lessons (2026-08-12, implementation)

**Finding A was real, not already-fixed.** The film-off transmission spectral eval
already had a `max(rgb, 1.0f)` "maxc guard", so at first glance it looked handled.
But the `1.0f` FLOOR is a *clamp/energy-gain* guard, not a magnitude normalizer: for
a sub-unit BSDF value (`rgb < 1`, the common case) `maxc == 1` and the code upsampled
`colour · achromatic_scalar` directly — the exact JH magnitude-nonlinearity
([[spectral-upsample-nonlinearity-scaled-bsdf]]). The fix separates the chromatic
reflectance colour from the achromatic geometry/Fresnel scalar (incl. the glass
eta², which now lives entirely in `scalar` and never touches the upsample argument):
`upsample(colour)·scalar`, with the `max(colour,1)` clamp-guard retained only for a
(never-reached here) colour>1 case. Done via an optional `(colour,scalar)` out-param
on `transmissionEvalRGB`/`gpu_pr_transmissionEval` so the RGB pipeline is byte-
unchanged (nullptr default). CPU + GPU twin.

**Finding B's clamp guard is a defensive no-op — proven, not assumed.** Traced every
weight-carrying lobe in `assembleLobes`: the running `weight` is seeded at 1 and only
ever multiplied by factors ≤1 (baseColor, tints, layering directional albedos,
metallic/transmission/coat scalars), so `L.weight ≤ 1` always and `wMax == 1`. The
added `max(...,1)` guard on the `wSpec` upsample never bites today; it locks the
invariant against any future >1 weight and satisfies the acceptance criterion.

**The deep Finding B (colour×colour product in `assembleLobes`) was NOT fixed and is
descoped to pkg194.** The magnitude class is handled (Finding A + the guard); the
residual is a *colour×colour* nonlinearity — `upsample(a·b) ≠ upsample(a)·upsample(b)`
— that only appears when TWO layering factors are both chromatic (a coloured coat
Beer / sheen / specular tint stacked over a coloured base). Fixing it correctly
requires carrying per-lobe *spectral* state through the per-shade device
`assembleLobes`, i.e. adding per-hit spectral live state — precisely the class
[[closure-graph-lobe-count-spills-fused-kernel]] warns spilled the fused shade kernel
(+52% non-Principled regression). That is register-hostile and forbidden by this
package's hard `<false>`=3608/254/1700 constraint, so it is deferred with an
empirical register-probe-first plan in pkg194.

**Quantified residual (CPU JH upsample, 380–780nm/5nm, `_cpu_rgb_upsample_batch`):**
band-integrated relative error of `upsample(a·b)` (current) vs
`upsample(a)·upsample(b)` (spectrally-correct per-layer product) for representative
tinted-layer stacks:

| stack (tint a / base b)            | band relErr | max per-λ relErr |
|------------------------------------|-------------|------------------|
| sheen [1,.7,.8] / dark [.1,.1,.12] | **72.5%**   | 387%             |
| saturated coat [.3,.7,1] / mid [.6,.5,.4] | **34.9%** | 94%           |
| deep coat [.2,.4,.9] / bright [.85,.8,.75] | 20.1%   | 72%             |
| specular [.9,.55,.25] / neutral [.7,.7,.7] | 5.4%    | 19%             |

**This is SURPRISINGLY LARGE and raises the pkg194 follow-up's priority** (flagged
per the dispatch's >5% rule). Interpretation: the two forms are the RGB-product
approximation of layering (`upsample(a·b)`, what the code does — integrates to the
RGB product `a·b` under white light) vs the spectrally-correct per-layer reflectance
product (`upsample(a)·upsample(b)`). They diverge most for SATURATED tints over
DARK/MID bases, where the JH sigmoid is most nonlinear. The **common case is
unaffected**: a WHITE tint gives `upsample([1,1,1]·b) == upsample(b)` (0% error), so
only materials with a genuinely COLOURED coat/sheen/specular tint stacked over a
coloured base are hit. The magnitude class (achromatic scalar × colour) that Finding
A/B fixed is orthogonal and fully resolved; this residual is the colour×colour class,
which needs the register-gated spectral-carry restructure (pkg194 Item 1).

**Finding C descoped to pkg194** (thin-wall per-λ R'/T' + the tinted-layer
spectral-carry above). One Finding-C sub-item was found ALREADY CORRECT and must not
be re-audited: GPU delta Principled events DO fill `fSpectral`, via the generic
eta²-clamp guard at `gpu_materials.h:3268-3273` (mirrors the CPU delta branch). The
spec's worry that they "never fill fSpectral" was stale.

**Line-ending hazard (as warned):** `gpu_materials.h` has MIXED endings in HEAD
(2992 CRLF + 313 LF lines). The Edit tool rewrote the whole file to uniform CRLF →
a phantom ~313-line diff. Repaired by restoring HEAD and re-applying the hunks via
byte-level Python replacement with CRLF-matched new lines, leaving the scattered
LF-only lines untouched. Final diff: real hunks only (`git diff --ignore-cr-at-eol`
== `git diff`). `principled.cpp` is uniform LF and was unaffected.
