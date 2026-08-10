# pkg182 — Principled/Disney `ggxReflect` eval-D vs pdf-D consistency: low-roughness metal/specular near-black fix

**Pillar:** 2 (materials / BSDF energy correctness)
**Track:** A (CPU+GPU byte-mirrored, RTX-verified)
**Status:** done (PR #582, 2026-08-10 — grey-furnace centre luminance: metallic
r=0.02/0.05/0.10 0.067→**0.604** (matches the `metal` reference), r=0.30
0.567→0.603; dielectric-specular r=0.02/0.05/0.10 0.025→**0.231**, r=0.30
0.217→0.230. Register-neutral: `<false>` STACK 3608 B / `<true>` STACK
6592 B unchanged. 14 new/extended tests + 73-test regression green, RTX
5070 Ti hardware-verified.)
**Estimated effort:** S (eval-only fix, sampler/pdf untouched)
**Depends on:** `disney.cpp` / `gpu_materials.h` GGX reflect evaluators
(metallic + specular + anisotropic lobes); discovered as a blocker for
**pkg178** Stage 4 PR-4 (thin-wall) — the same regularizer mismatch made
thin-glass render black before this fix.

## Origin

Surfaced during pkg178 Stage 4 PR-4 (thin wall / thin glass, 2026-08-10):
the thin-glass reflect lobe rendered black at low roughness. Root-caused to
a pre-existing defect in the (much older) Principled/Disney metallic and
specular reflect evaluators, not the new thin-glass code — filed and fixed
as its own package since it affects every existing low-roughness
metal/specular render, not just thin-glass.

## The defect

Reflect **eval** used a regularized GGX D: `a2 / (π·denom² + 1e-4)`. Reflect
**sample**'s pdf used the unregularized `D_GTR2` (no epsilon). At the
specular peak (`denom→0`) the `+1e-4` collapses eval-D up to **~19000× at
r=0.02** relative to pdf-D, driving `f/pdf → 0` and the surface toward
black. The anisotropic path carried the twin defect (`ggxAnisoD` eval
regularizer `1e-4` vs pdf regularizer `1e-12`).

## Fix

Make eval-D **equal** pdf-D: unregularized `D_GTR2` for the isotropic
metallic/specular/anisotropic reflect evaluators (aniso regularizer
tightened `1e-4 → 1e-12` to match the sampler), CPU + GPU byte-mirrored.
**Eval-only** — the sampler and pdf are untouched (they were already
`D_GTR2`). Same discipline as the existing Transmission lobe and the
pkg178 Stage-4 thin-glass lobe. Cites Heitz 2014 (GGX D term).

## Acceptance criteria

- [x] Grey-furnace centre luminance in-band at low roughness for metallic
      and dielectric-specular (`test_principled_reflection_not_black`).
- [x] GPU furnace + CPU/GPU parity green.
- [x] Register-neutral (`<false>`/`<true>` STACK unchanged).
- [x] chi² invariant (eval-only change; sampler/pdf untouched).
- [x] Full regression suite green (73 tests), RTX 5070 Ti hardware-verified.

## Non-goals

- Not the sampler or pdf (already correct — `D_GTR2` unregularized).
- Not the transmission lobe (already used the correct unregularized form).
- Not a general regularizer-policy change across every closure — scoped to
  the three reflect evaluators that carried the mismatch.

## Provenance

Filed by the lead 2026-08-10, discovered during pkg178 Stage 4 PR-4 review
(thin-glass black-render blocker); fixed and merged the same day as PR #582.
