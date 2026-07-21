# pkg145 — Disney specular energy-compensation refit vs the true (epsilon-free) D_GTR2

**Pillar:** 2 (BSDF / material energy conservation)
**Track:** A (converge Astroray's Disney energy compensation to the Cycles-faithful path against the true D; regenerate the Astroray-specific tuned pieces; two-toolchain grid gate)
**Codex-paste-ready:** no (a numerical recalibration whose target is the full directional-hemispherical reflectance grid across both toolchains, replacing hand-tuned deflated-D corrections with the Cycles-faithful compensation — judgment at the gate, evidence-first)
**Status:** open — dispatchable (does not block #498; see "Relationship to #498")
**Estimated effort:** M–L (localized code, but a real calibration loop: regenerate tables + retune/remove ad-hoc terms + full grid green on GCC **and** MSVC + furnace + chi² unchanged)
**Supersedes:** **pkg143** (clearcoat-only refit, PR #508). The pkg89/#498 Round-4 sweep at `5e2080c` proved the clearcoat failure is a **subset** of a whole-specular-lobe problem: with the true D in `eval()`, the deflated-D-fitted compensation over-conserves across grazing and low-roughness rows, not just the one clearcoat config. pkg143's clearcoat contract is fully absorbed below. Close PR #508 as superseded.

**Origin:** #498 (pkg123) Round-4 stop-and-rescope (5-round limit). Coordinator post-eval-fix sweep at `5e2080c`: the eval `clampColor` cap removal fixed the metal regressions (metal-not-black passes, 4 gates xpass, chi² green, 408 passed) and surfaced energy-conservation failures the deflated D had masked.

> **Target-set re-anchoring (evidence update, supersedes the "13-config" enumeration below).** The `13` failing configs were measured with `test_disney_energy_conservation`'s **broken** `integrateMaterialReflectance` (uniform Halton, 4096 samples), which itself relied on the eval cap and is not a valid oracle for the near-delta true-D integrand: it produces **both false-positives** (metallic r=0.1, cos=0.9 reads 1.31 at 4096 but **1.003 at 1M**; furnace render 0.997 — clean) **and false-negatives** (dielectric r=0.1, cos=0.1 grazing *passes* at 4096 but reads **1.243 at 65536** — a REAL hidden violation). So the "13-at-4096" set is a **measurement artifact**; the real-violation set differs. #498 (within pkg123 scope) replaces the estimator with an **importance-sampled `rho()` per pbrt-v4 §14.1** (test-integrator correctness — it uses the sampler pkg123 just made consistent), and the **fixed-integrator enumeration** of genuine violations lands in #498's final PR body + finding doc. **pkg145's real targets = the grazing-incidence dielectric and Burley-retro violations; metallic near-normal is clean.** Re-anchor this spec's config list to that enumeration when it lands; the sections below are correct on *mechanism* but their specific 4096-era config coordinates are superseded.

---

## Root cause — Astroray's hand-tuned deflated-D corrections, not the Cycles tables

The chi²-era `+0.001f` epsilon in `D_GTR2` **deflated** the GGX specular D to ≤~0.32 at every roughness (worst at the alpha floor / low roughness). pkg123 (#498) correctly removed it so `pdf()`/`sample()` are consistent (chi² green) and `eval()` now uses the **true** near-delta D (~1e3–1e4 at the alpha floor), with the dormant `eval()` cap removed so `f/pdf` cancels (metal fixed).

Key distinction (`.astroray_plan/docs/disney-energy-compensation-research.md`):

- The **Cycles-derived** `table_ggx_E` (32×32) and `table_ggx_Eavg` (32) directional-albedo tables are **D-independent** (they are Cycles' Apache-2.0 albedo integrals). The Cycles compensation `energy_scale = 1/E`, `Fms = Fss·Eavg/(1−Fss·(1−Eavg))`, net `1 + Fms·((1−E)/E)` **conserves by construction when applied to the true GGX D** — that is exactly what Cycles renders with. So the Cycles path is *correct* under the true D; it was the **deflated** D that made Astroray's lobe integrate below E and hide the tuning error.
- The failures come from **Astroray-specific pieces that were numerically tuned against the deflated-D total**, and which now over-correct on top of the (now-correct-magnitude) true-D lobe:
  1. **`clearcoat_E.bin` + `min(1/clearE, 1.25)`** (`plugins/materials/disney.cpp:366-379`) — an Astroray-invented clearcoat table (Cycles has **no** `clearcoat_E`; it routes coat through the same GGX dielectric preserve-energy path — research doc §"Clearcoat Discrepancy", :188-201). Fitted to the deflated D → over-scales the true-D clearcoat lobe (the known 1.0206 config).
  2. **The roughness-0.9 grazing Burley-diffuse "directional furnace normalization"** added in the pkg60 follow-up (research doc :290-293) to pull retro-reflection under 1.02 — fitted to the deflated-D total, now mis-tuned (the `[cos=0.1, roughness=0.3]` grazing rows, and the historical worst case was roughness=0.9 grazing).
  3. Any residual **ad-hoc `ggxMultiScatterCompensation` / `msWeight`** term (research doc :205-228, `include/raytracer.h`) stacked on the Cycles path — a double-compensation risk under the true D.

So the fix is **not** "invent a new fudge": it is to **converge Astroray's Disney compensation onto the Cycles-faithful path so the true D conserves without deflated-D hand-tuning** (CLAUDE.md §6).

---

## Fix contract

Refit **the whole Disney specular/coat/diffuse-grazing compensation against the true epsilon-free `D_GTR2`**, preferring Cycles-faithful replacement over re-tuning where possible:

1. **Clearcoat (absorbs pkg143).** Either (preferred, Cycles-faithful) route coat through the **same GGX `E`/`Eavg` dielectric preserve-energy path Cycles uses** (research doc :199, `bsdf_microfacet_setup_fresnel_dielectric` → `microfacet_ggx_preserve_energy`) and retire `clearcoat_E.bin`; **or**, if the owner wants to keep the Astroray-specific coat table, **regenerate `clearcoat_E.bin` against the true D** and re-tune/remove the `1.25` clamp. Decide against the sweep, not by assumption.
2. **Grazing diffuse normalization.** Re-derive or remove the pkg60 roughness-0.9 grazing Burley-diffuse normalization against the true D so the grazing rows conserve without it distorting mid-grazing (`cos=0.1`) configs. Prefer the Cycles/Burley formulation over the ad-hoc normalization.
3. **De-duplicate multi-scatter.** Confirm only **one** GGX multi-scatter compensation is active (the Cycles `1 + Fms·((1−E)/E)` net factor); remove/gate any leftover ad-hoc `ggxMultiScatterCompensation`/`msWeight` so the true-D lobe is not double-compensated.
4. **Keep the Cycles `table_ggx_E`/`table_ggx_Eavg` data as-is** — they are correct and D-independent; do not regenerate them. Only the Astroray-specific tuned pieces change.
5. Evidence-first: drive every change off `renderer.integrate_material_reflectance(id, cos_theta_o, SAMPLES)` over the **full** grid (`5 roughness × 2 metallic × 3 sheen × 3 clearcoat × 3 cos_theta_o`); record before/after worst-case per config.

---

## Gates

- **Full energy-conservation grid ≤ 1.02 on BOTH toolchains.** All 90 configs pass the **1.02** hard gate on **GCC CI** (`gh run view` HEAD — a green local MSVC build is not sufficient; memory `mingw_local_vs_gcc_ci_divergence`) **and** MSVC. Restore the 13 configs #498 temporarily relaxes (see below) to the 1.02 assert. Record the post-refit worst case + config.
- **chi² unchanged (green).** The pkg121/pkg123 Disney chi² gates and the Disney-metal GPU/CPU near-delta parity stay green — this refit touches compensation magnitude, **not** the `pdf()`/`sample()` D or the eval cap that #498 fixed. Do not reintroduce any D epsilon or eval cap.
- **Furnace unchanged.** White-furnace / glass-furnace and the mixed-metallic gray-furnace glow test (`test_disney_energy_conservation.py:69`) stay green; show before/after.
- **GPU parity.** If the device Disney eval mirrors the compensation, apply the same refit and re-verify GPU==CPU on RTX (not concurrent with another CUDA verifier — memory `cuda_verifier_concurrency`).
- **Build evidence** (CLAUDE.md): `.pyd` mtime vs `git log -1 HEAD`, `astroray.__file__ = build_cuda/Release/`; a `.bin` change needs a re-import.

---

## Relationship to #498 (the rescope this package enables)

Adjudicated (design authority, this round): **#498 ships now; the refit decouples here.** Concretely, #498 should:

1. **Keep `5e2080c`'s render** — the uncapped **true-D** `eval()` with integrator-level firefly control. This is the **physically correct** render (metal fixed, `f/pdf` cancels, chi² green) — **not** a regression to revert. Do **not** restore the eval cap: with the true D a restored cap re-darkens metal (the very regression `5e2080c` fixed). *(The Round-4 option-(c) premise "restore the cap = no regression vs main" does not hold — the deflated D was simultaneously masking the chi² sampler error and this energy non-conservation, so removing it to green chi² necessarily surfaces the energy error; you cannot get chi²-green + zero-render-change + energy-green at once.)*
2. **Fix the test integrator first (in pkg123 scope): importance-sampled `rho()` per pbrt-v4 §14.1**, then quarantine **only the measured-real refit-pending set** from the fixed integrator, each with an inline `# TODO(pkg145)` pointer and the exact id list.
   **Quarantine safety property (refined for the real set).** The self-guarding intent is preserved, but note the real violations are **pre-existing on `main`** (hidden by the broken 4096 integrator + deflated D), and at least one measures **~1.243** (dielectric r=0.1, cos=0.1 grazing) — i.e. **above 1.05**. So the guard is **not** a flat "1.05 ceiling on all 90" (that would wrongly block #498 on a pre-existing leak). The correct property: **every config outside the enumerated real-refit set must stay ≤ its `main` baseline / the 1.05 visible-glow ceiling** (catches any NEW regression), while the enumerated real set is explicitly quarantined at its measured value with a committed pkg145 fix. This keeps the auto-guard against new glow, does not mask a pre-existing leak as "shippable-clean," and does not falsely fail #498 on leaks it did not introduce.
3. Point #498's PR body + the test TODO at this package. pkg145 restores the quarantined real set to 1.02.

Net: #498 ships the correct render + chi² value + the corrected test oracle; pkg145 fixes the genuine (pre-existing) grazing energy leaks the fixed oracle exposes.

---

## Definition of done
- [ ] Clearcoat conserved via the Cycles GGX dielectric preserve-energy path (or a true-D-regenerated `clearcoat_E.bin`); pkg143 fully absorbed, PR #508 closed as superseded.
- [ ] Grazing diffuse normalization re-derived/removed vs true D; grazing rows conserve.
- [ ] Single (non-duplicated) GGX multi-scatter compensation; ad-hoc term removed/gated.
- [ ] Full 90-config grid ≤ 1.02 on GCC CI (`gh run view`) and MSVC, measured with the **fixed importance-sampled `rho()` integrator** (#498); the quarantined real-refit set restored to 1.02; worst case recorded.
- [ ] Target config set re-anchored to #498's fixed-integrator enumeration (not the superseded 4096-uniform "13" set).
- [ ] chi² + Disney-metal GPU/CPU parity + furnace all green; no D epsilon / eval cap reintroduced; before/after shown.
- [ ] GPU compensation parity re-verified on RTX, or noted N/A.
- [ ] Cycles/Kulla-Conty attribution preserved for any regenerated table (`data/disney_compensation/README.md`).
