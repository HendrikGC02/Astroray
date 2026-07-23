# pkg143 — Disney clearcoat energy recalibration (refit against the epsilon-free D_GTR2)

**Pillar:** 2 (BSDF / material energy conservation)
**Track:** A (refit an Astroray-specific compensation table against the corrected D, evidence-first; two-toolchain gate — needs a build, not a mechanical patch)
**Codex-paste-ready:** no (a numerical recalibration whose target is a directional-hemispherical reflectance sweep; the fix is a regenerated table + possibly a re-tuned clamp, validated on both GCC and MSVC — judgment at the gate)
**Status:** SUPERSEDED by pkg145 (2026-07-21, PR #510 — the clearcoat failure is a subset of the whole-specular-lobe refit; pkg143's contract is fully absorbed by `pkg145-disney-specular-energy-compensation-refit.md`). Do NOT dispatch.
**Estimated effort:** S–M (localized to the clearcoat compensation + its `.bin` table; cost is the calibration sweep + two-toolchain green + furnace re-check)
**Depends on:** pkg123 (PR #498) — this package refits *against the epsilon-free D_GTR2* that #498 establishes. Refitting before #498 lands would calibrate against the wrong (deflated) D again. Land order: #498 → pkg143.

**Origin:** #498 Round-4 adjudication (commit `5e2080c`, `pkg121-disney-pdf-finding.md` Round 4). The clearcoat CI failure was explicitly declared out-of-scope collateral of the pkg123 epsilon removal and deferred to this focused follow-up.

---

## Context — how the epsilon removal woke a mis-calibrated clearcoat compensation

pkg123 (#498) correctly removed the `+0.001f` chi²-era epsilon from `D_GTR2`. That
epsilon had **deflated** the GGX specular D at every roughness. The Disney clearcoat
lobe **shares `D_GTR2`** (`plugins/materials/disney.cpp:366`,
`Dr = D_GTR2(NdotH, clearcoatGloss_²)`), so the epsilon removal **restored the
clearcoat lobe's true (larger) energy**.

But pkg60's clearcoat compensation was **numerically calibrated against the deflated
D**. Cycles has **no** `clearcoat_E` table (confirmed
`.astroray_plan/docs/disney-energy-compensation-research.md:188-201,262-265`); the
`data/disney_compensation/clearcoat_E.bin` directional-albedo slice and the
`min(1/clearE, 1.25)` compensation are **Astroray-specific** (owner-approved in
pkg60). The mechanism of the regression:

```cpp
// plugins/materials/disney.cpp:366-379
float Dr = D_GTR2(NdotH, clearcoatGloss_ * clearcoatGloss_);        // now epsilon-free → larger
...
Vec3 clearcoatTerm = Vec3(clearcoat_ * Dr * Fr * Gr) * 0.25f;       // raw lobe: larger post-#498
const float clearE = std::max(compensationTables.clearcoatE(NdotV), 1e-4f);  // table baked with DEFLATED D → too small
clearcoatTerm *= std::min(1.0f / clearE, 1.25f);                    // 1/clearE too large → under-compensates the now-larger lobe
lowerLayerWeight = layeringWeightAfter(lowerLayerWeight, Vec3(clearcoat_ * (1.0f - clearE)));
```

`clearcoat_E.bin` is the directional albedo of the clearcoat lobe. It was integrated
with the deflated D, so it is **smaller than the true albedo**; `1/clearE` therefore
over-scales the now-restored (larger) raw lobe, and the layering deduction
`(1 - clearE)` under-removes energy from the lower layer. Net: the clearcoat lobe
carries more energy than it conserves.

### Symptom (measured)

`test_disney_energy_conservation` config **`[0.9-1.0-0.0-0.0-0.3]`** measures
**1.0206** vs the **1.02** hard gate — GCC CI only (does not reproduce on MSVC; the
loose 1.05 gate passes on both). Resolving the pytest id (stacked-parametrize,
innermost decorator first: `cos_theta_o - clearcoat - sheen - metallic - roughness`):
**cos_theta_o=0.9, clearcoat=1.0, sheen=0.0, metallic=0.0, roughness=0.3**,
`clearcoat_gloss=0.25` (fixed in the harness, `test_disney_energy_conservation.py:35`).
This is a **clearcoat=1.0** config, confirming the lobe attribution. For reference,
pkg60's *pre-fix* worst case was **1.0159 with the epsilon present**, at a
**clearcoat=0** (base-lobe) config — the epsilon removal lifted a clearcoat=1.0 config
past it.

---

## Fix contract (adjudicated in #498 — do exactly this, not the alternatives)

**Refit the clearcoat compensation against the epsilon-free `D_GTR2`.** Concretely:

1. **Regenerate `data/disney_compensation/clearcoat_E.bin`** by re-integrating the
   clearcoat lobe's directional albedo `E_clearcoat(μ)` with the **epsilon-free**
   `D_GTR2` (i.e. the D that #498 ships), using the same `clearcoat_gloss` / fixed-alpha
   assumption pkg60 used for the slice (`disney.cpp:373` comment; the
   `clearcoat_gloss²` → `α = 0.0625` for the test's 0.25 gloss). The corrected (larger)
   `clearE` makes `1/clearE` smaller and the `(1-clearE)` layering deduction larger, so
   the compensated lobe conserves.
2. **Re-tune the `1.25` clamp cap** (`disney.cpp:376`) only if the refit sweep shows it
   still binds after the table is corrected. The clamp is a firefly guard on
   `1/clearE`; with the correct (larger) `clearE` it should rarely bind, but confirm
   against the sweep rather than assuming. If it binds, set it to the smallest value
   that keeps the whole grid ≤ 1.0 without visibly darkening clearcoat at grazing μ.
3. Keep the change **evidence-first**: drive the refit off the actual reflectance
   integrator the gate uses — `renderer.integrate_material_reflectance(id, cos_theta_o,
   SAMPLES)` across the full `CLEARCOATS × ROUGHNESSES × cos_theta_o` grid — and record
   the before/after worst case per config. The target is directional-hemispherical
   reflectance **≤ 1.0** (with the 1.02 gate as the hard ceiling and 1.05 as the loose
   bug ceiling).

### Explicitly NOT permitted (adjudicated)

- **NOT** a bare epsilon restore into `D_GTR2` — #498 removed it deliberately; the
  epsilon-free D is required by the chi² pdf gates (pkg121/pkg123). Re-adding it
  re-breaks those.
- **NOT** a gate loosening — the 1.02 hard gate stays. The fix makes the physics
  conserve, it does not move the goalpost.
- **NOT** a blind layering-weight tweak divorced from the recalibration.

---

## Gates

**Primary — energy-conservation grid green on BOTH toolchains.**
`test_disney_energy_conservation::test_disney_directional_hemispherical_reflectance_is_conserved`
(the full `5 roughness × 2 metallic × 3 sheen × 3 clearcoat × 3 cos_theta_o` grid)
passes the **1.02** hard gate on **GCC** (the failing toolchain — verify via
`gh run view` on the branch HEAD, matrix jobs; memory
`mingw_local_vs_gcc_ci_divergence` — a green local MSVC build is NOT sufficient) **and**
MSVC. Report the post-refit worst case and its config.

**Secondary — furnace unchanged.** `test_disney_energy_conservation::test_disney_mixed_metallic_sampler_does_not_glow_in_gray_furnace` stays green, and the broader Disney
white-furnace / glass-furnace suite is unchanged (this refit touches only the
clearcoat compensation, not the base spec/diffuse/transmission lobes). Show the
furnace numbers before/after to prove no collateral.

**Tertiary — GPU parity if the GPU clearcoat path exists.** If the device Disney eval
mirrors the clearcoat compensation, regenerate/upload the same corrected table and
re-verify GPU==CPU on RTX (don't run concurrently with another CUDA verifier — memory
`cuda_verifier_concurrency`). If the GPU path has no clearcoat compensation, note that
and skip.

**Build evidence** (CLAUDE.md): show `.pyd` mtime vs `git log -1 HEAD` and
`astroray.__file__ = build_cuda/Release/` before running the gates; a table `.bin`
change still requires a re-import to take effect.

---

## Flagged, NOT fixed here — the dormant roughTransmissionEval 4.0 clamps

`roughTransmissionEval` carries a hard **`clamp(..., 0, 4.0)`** on its result on both
sides — CPU `plugins/materials/disney.cpp:194-196` and GPU
`include/astroray/gpu_materials.h:622-624` (the #498 message cites these as
disney.cpp:197-199 / gpu :625-627; the caps are the observed `4.0`/`4.f` lines a few
lines above the `return`). This is the **same dormant-cap shape** that #498 just
removed from `eval()` — an upper clamp on a BSDF closure value that will silently
break `f/pdf` cancellation if the transmission D ever reaches it. **The glass furnace
currently passes**, so it is dormant today and out of scope for this energy-conservation
refit. Recorded here so it is not forgotten: a future package should replace the `4.0`
cap with a bare `max(·, 0)` floor (mirroring the #498 eval() fix) and move firefly
control to the integrator, verified by the glass furnace. Do **not** fix it in pkg143.

---

## Definition of done
- [ ] `clearcoat_E.bin` regenerated against the epsilon-free `D_GTR2`; regeneration method noted in the PR (and, if a sweep script was written, committed under `scripts/`).
- [ ] `1.25` clamp re-tuned only if the corrected sweep shows it binds; justified with numbers.
- [ ] Full `test_disney_energy_conservation` grid ≤ 1.02 on **GCC CI** (`gh run view` HEAD) and MSVC; post-refit worst case + config recorded.
- [ ] Furnace tests green, before/after numbers shown; no non-clearcoat lobe moved.
- [ ] GPU clearcoat parity re-verified on RTX, or explicitly noted as N/A.
- [ ] roughTransmissionEval 4.0 clamp left untouched and re-flagged in the PR body for a future package.
