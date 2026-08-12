# pkg194 — Principled tinted-layer spectral-carry + thin-wall per-λ R'/T' (pkg188 Finding C follow-up)

**Pillar:** 3/5 (spectral consistency / CPU-GPU parity)
**Track:** A
**Status:** open (filed 2026-08-12 as the pkg188 Finding-C descope; enhancement tier)
**Estimated effort:** L (register-gate probe up front — may be blocked)
**Depends on:** pkg188 (Findings A+B landed — transmission colour/scalar separation +
weight-path clamp guard); pkg168 (RGB→spectral upsample parity template);
[[closure-graph-lobe-count-spills-fused-kernel]] (the register-spill hazard this
package must probe before committing to the restructure).

> **Concurrency note:** several agents were filing specs when this was created; if
> the number `pkg194` collides with another spec, renumber to the next free slot.

---

## Why this exists

pkg188 fixed the two *cheap, correct-in-the-common-case* residual spectral gaps in
the native Principled BSDF (Finding A: film-off transmission upsampled the RGB
product; Finding B: missing weight-path clamp guard). It **explicitly descoped**
two items that require either a register-hostile restructure or genuinely new
per-λ work. This package carries them.

### Item 1 — tinted-layer `assembleLobes` spectral-carry (the deep Finding B)

`assembleLobes` (`plugins/materials/principled.cpp`) bakes chromatic, view-dependent
attenuation (coat Beer tint, sheen tint, specular-tint layering albedos) × the
lobe reflectance colour into a single RGB `L.weight`, which is then upsampled once
in `evalLobeSpectral` (`wSpec = upsample(L.weight/wMax)·wMax` after pkg188). When two
of those factors are BOTH chromatic (e.g. a coloured coat Beer tint over a coloured
base), this is `upsample(a·b) ≠ upsample(a)·upsample(b)` — a colour×colour JH
nonlinearity that magnitude-normalization does **not** remove (it only fixes the
achromatic-scalar/magnitude class, which pkg188 handled).

**pkg188 measured this residual** (CPU JH upsample, 380–780nm/5nm grid,
`_cpu_rgb_upsample_batch`, MODE_ALBEDO): band-integrated relative error of
`upsample(a·b)` vs `upsample(a)·upsample(b)` for representative tinted-layer stacks
was **up to ~72%** (coloured sheen over dark base), ~35% (saturated coat over mid
base), ~20% (deep coat over bright base), ~5% (specular tint over neutral base). This
is **surprisingly large** — larger than the sub-5% pkg188 expected — which is why
this follow-up is filed with elevated priority rather than as a nicety. It is only
reachable on materials with a *coloured* coat/sheen/specular tint stacked over a
*coloured* base; the common case (white tints) is exactly 0% (`upsample([1,1,1]·b) ==
upsample(b)`). See the pkg188 PR/Lessons table.

**The fix is register-hostile.** Correctly upsampling each colour separately and
multiplying in the spectral domain means carrying per-lobe *spectral* state through
`assembleLobes` (which runs per-shade on device, re-assembled because it is
view-dependent). Adding per-hit spectral live state is exactly the class of change
[[closure-graph-lobe-count-spills-fused-kernel]] warns spilled the fused shade
kernel (+52% non-Principled regression). pkg188's live-state analysis: the running
`weight` is `Vec3`; a spectral carry would widen it to `kSpectrumSamples` floats per
tracked factor.

**Required approach (do this FIRST, before any implementation):**
1. Empirically probe the register cost. Prototype the spectral-carry inside the
   `if constexpr (HasPrincipled)` branch ONLY, build native-sm_120, and read the
   post-link `<false>` AND `<true>` `stageShadeBucketed` specialization
   STACK/REG/CONSTANT via `cuobjdump` (NOT `ptxas -v` —
   [[wavefront-shade-kernels-register-saturated]]). The HARD gate: `<false>` must
   stay at **STACK 3608 / REG 254 / CONSTANT[0] 1700**; `<true>` must not regress
   non-Principled perf (min-of-N, burn-in per [[gpu-perf-ab-clock-drift]]).
2. If the probe spills either specialization, **STOP and report** — the value
   (a sub-X% band error on an uncommon coloured-coat-over-coloured-base material)
   almost certainly does not justify a shared-kernel regression. Prefer a CPU-only
   fix (CPU has no register gate) with the GPU twin left on the pkg188 behaviour and
   the divergence documented, OR park the item.

### Item 2 — thin-wall R'/T' per-λ native

Thin-wall (`thin_wall=true`) glass computes the analytic R'/T' split per-RGB-channel
(`thinGlassFresnelRGB`, `principled.cpp`) with a film-on RGB sensitivity path, not
per-λ native. Bring it to per-λ native (the pkg163/pkg182 discipline) so the
thin-glass reflect/transmit lobes evaluate Fresnel per wavelength. Mirror on the GPU
twin (`gpu_materials.h` `gpu_pr_*` thin-glass functions) inside `HasPrincipled`.

---

## NOT in scope / already correct — do not re-audit

- **GPU delta Principled `fSpectral`** — pkg188 verified this is ALREADY correct:
  delta (smooth-glass) Principled events fill `fSpectral` via the generic
  eta²-clamp guard at `gpu_materials.h:3268-3273` (factor >1 magnitude, upsample the
  normalized tint), mirroring `PrincipledPlugin::sampleSpectral`'s delta branch. The
  pkg188 spec's Finding-C worry that they "never fill fSpectral" was stale. Do NOT
  reopen this.
- Transmission film-off colour/scalar separation and the weight-path clamp guard —
  landed in pkg188 (Findings A+B).

## Acceptance criteria

- [ ] Item 1: register-gate probe run and reported FIRST; restructure implemented
      only if `<false>` stays 3608/254/1700 and `<true>` shows no non-Principled
      regression — otherwise a documented CPU-only fix or an explicit park, with the
      cuobjdump evidence in the PR.
- [ ] Item 1: on a coloured-coat-over-coloured-base scene, the tinted-layer band
      error is measurably reduced vs the pkg188 baseline (report the before/after
      numbers from the same `_cpu_rgb_upsample_batch` harness).
- [ ] Item 2: thin-wall R'/T' evaluated per-λ on CPU + GPU twin; parity test locks
      CPU↔GPU; furnace energy conserves (linear, bounded above).

## Hard non-goals

- **No lobe-array shrink** to buy register room (pkg188/pkg178 rule — if-constexpr
  isolation, never shrink shared state).
- **No reopening** the GPU delta `fSpectral` path (already correct).
