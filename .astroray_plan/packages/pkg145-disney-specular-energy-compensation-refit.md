# pkg145 — Disney specular energy-compensation refit vs the true (epsilon-free) D_GTR2

**Pillar:** 2 (BSDF / material energy conservation)
**Track:** A (converge Astroray's Disney energy compensation to the Cycles-faithful path against the true D; regenerate the Astroray-specific tuned pieces; two-toolchain grid gate)
**Codex-paste-ready:** no (a numerical recalibration whose target is the full directional-hemispherical reflectance grid across both toolchains, replacing hand-tuned deflated-D corrections with the Cycles-faithful compensation — judgment at the gate, evidence-first)
**Status:** done (PR #513 merged 2026-07-23) — diffuse-under-
specular Cycles `closure_layering_weight`/OpenPBR coupling added to
`plugins/materials/disney.cpp::eval()`; full 90-config x 3-angle energy grid
1.2048 -> 1.004 (N=65536); pkg143/clearcoat fork resolved by measurement
(kept the original pkg60 clearcoat mechanism, unchanged — the "preferred"
table_ggx_E route regressed on the Dr/Gr fixed-alpha mismatch); quarantine
in `test_disney_energy_conservation.py` retired. GPU parity N/A (`gpu_disney_
eval` carries no CPU compensation twin at all, pre-existing). Head SHA
d4eecbe04a348a7107aac5a7e519ff3ae5fe2085; HW visual gate still pending.
**Estimated effort:** M–L (localized code, but a real calibration loop: regenerate tables + retune/remove ad-hoc terms + full grid green on GCC **and** MSVC + furnace + chi² unchanged)
**Supersedes:** **pkg143** (clearcoat-only refit, PR #508). The pkg89/#498 Round-4 sweep at `5e2080c` proved the clearcoat failure is a **subset** of a whole-specular-lobe problem: with the true D in `eval()`, the deflated-D-fitted compensation over-conserves across grazing and low-roughness rows, not just the one clearcoat config. pkg143's clearcoat contract is fully absorbed below. Close PR #508 as superseded.

**Origin:** #498 (pkg123) Round-4 stop-and-rescope (5-round limit). Coordinator post-eval-fix sweep at `5e2080c`: the eval `clampColor` cap removal fixed the metal regressions (metal-not-black passes, 4 gates xpass, chi² green, 408 passed) and surfaced energy-conservation failures the deflated D had masked.

> **Research note — 2026-07-21 night session (implementation attempt, parked at session limit; no code committed).** An Opus implementer round reached a decisive decomposition: the grazing overshoot is **diffuse + specular summed without inter-layer energy conservation** (Disney 2012's known non-conservation), NOT a defect in either lobe alone. Measured at roughness=0.1, cos_theta_o=0.1 (the worst quarantined config): diffuse integrates to 0.73, specular to 0.48 — neither exceeds 1 alone; the naive sum is 1.20. `diffuseFurnaceScale` barely acts there (0.96). The physically-correct, Cycles-faithful fix direction is **diffuse-under-dielectric-specular coupling** — attenuate the diffuse lobe by the specular layer's directional albedo.
>
> **The exact Cycles/OpenPBR formulation is now researched and cited** (2026-07-23): `.astroray_plan/docs/pkg145-diffuse-specular-coupling-research.md` — Cycles `closure_layering_weight` (`intern/cycles/kernel/closure/bsdf_util.h`, Apache-2.0) applied per-layer in the Principled stack, equivalently OpenPBR's glossy-diffuse albedo scaling `f ≈ f_dielectric + (1 − E_dielectric(wo))·f_diffuse` (Kulla & Conty 2017 lineage). The in-repo D-independent `table_ggx_E` supplies `E_dielectric` — **no new table needed**. Sanity: 0.48 + (1−0.48)·0.73 = 0.86 ≤ 1.0 at the worst config. Implement per that note; fix-contract item 2 (grazing diffuse normalization) is expected to become *removal* once the coupling lands.

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

---

## Hardware verification 2026-07-23

**Hardware:** RTX 5070 Ti. **OS:** Windows 11 Enterprise 10.0.26200. **Driver/CUDA:** CUDA 12.8 (nvcc `v12.8/bin/nvcc.exe`, secondary v12.6 toolkit also present), OptiX 9.1.0, MSVC 14.44.35207 (VS 2022 BuildTools 17.14.10). **PR:** #513. **Head SHA:** `84eb6a8c473807995bf558dc681cea309a856003`.

**Build.** `build_cuda_worktree.bat` failed (exit 5, MSB3721): its `cmake --build build_cuda --target astroray` omits `--config Release`, defaulting to Debug, which clashes `/RTC1` with CUDA's forced `/O2` on `.cu` TUs — this is the known Debug-config footgun (`build-cuda-worktree-debug-config.md`), did not touch the existing Release `.pyd`. Rebuilt clean with `configure_and_build.bat` (MSVC bootstrapped via `vcvars64.bat` in the same shell) — `-DCMAKE_BUILD_TYPE=Release`, "Build succeeded". Confirmed `astroray.__file__` resolves to `build_cuda/Release/astroray.cp313-win_amd64.pyd` inside this worktree (via `tests/runtime_setup.configure_test_imports()`), not the main repo.

**Pass/fail table:**

| Suite | Result |
|---|---|
| `test_disney_energy_conservation.py` | 271 passed, 0 failed |
| `test_disney_reflection_not_black.py` + `test_material_properties.py` | 21 passed, 2 xfailed (pkg144-owned `sLum>20` firefly-clamp masking, pre-existing, unrelated to this PR) |
| `test_disney_rough_glass_furnace.py` | 5 passed |
| `test_pkg123_disney_metal_gpu_cpu_parity.py` | 4 xpassed (pre-existing xfail; GPU Disney eval has no CPU-twin compensation mechanisms — PR item 5 confirms no GPU code touched) |
| `tests/statistical/test_chi2_bsdf.py -m "not slow"` | 7 passed, 1 xfailed (pre-existing, tracked separately as `disney-dielectric-reflection-lobe`, pkg121-disney-pdf-finding.md Round 2d) |

No NEW failures vs the PR body's claimed results.

**Measured numbers (independent re-measurement, full 270-config sweep, N=65536, same `integrate_material_reflectance` rho() integrator):**
- Full grid worst case: **1.004014** at roughness=0.3, metallic=1.0, clearcoat=1.0, cos_theta_o=0.9 — matches the PR body's claimed 1.004 exactly. Well under the 1.02 hard gate.
- pkg123 clearcoat-regression config (roughness=0.3, metallic=0.0, clearcoat=1.0, cos_theta_o=0.9): measured **0.981316** (checked at N=4096/16384/65536/262144, stable in [0.9729, 0.9852]) vs the PR body's claimed **0.947**. Does not reproduce the PR's exact number, but both are comfortably under gate (1.02/1.05) — **flagged as a discrepancy in the PR's reported table, not a gate failure.**
- Grazing-set numbers (roughness=0.1, sheen=0/0.5/1.0, clearcoat=0, cos=0.1): measured 0.847474 / 0.829611 / 0.812430, matching PR-claimed 0.8475 / 0.8296 / 0.8124.
- Grazing roughness=0.3 (sheen=0, cc=0, cos=0.1): measured 0.702473, matching PR-claimed 0.7025.

**Note on an in-repo comment discrepancy:** `tests/test_disney_energy_conservation.py`'s header comment states the fix "brings the whole 90-config x 3-angle grid to <= 1.0 measured at N=65536 (worst 0.999072, roughness=0.3, metallic=1.0, cos_theta_o=0.5)". This is stale/inconsistent with the PR body's own table and with this verifier's independent full-grid sweep, both of which show the true worst case is **1.004014** (clearcoat=1.0, cos=0.9) — i.e. slightly above 1.0, not below. Not gate-relevant (1.004 < 1.02), but the comment should be corrected in a follow-up so it does not mislead future readers.

**Visual inspection:**
- Disney contact sheet (`tests/scenes/disney_contact_sheet.py`, 512x512, 512 spp, depth=12, default gamma) compared against `test_results/overnight_report_2026-07-23/disney_contact_sheet_before.png`: qualitatively matching — no visible over-brightening, no black rings, no clipping on either Disney sphere (top-right and bottom-right, roughness=0.4/metallic=0.3/specular=0.6).
- White-furnace render at the worst-case grid config (roughness=0.3, metallic=1.0, clearcoat=1.0, uniform white background): sphere nearly disappears into the background (mean=0.992), consistent with the 1.004 measured ratio; no bright rim, no dark ring, no banding.
- Grazing-angle low-roughness (0.1) vs high-roughness (0.9) Disney spheres: low-roughness shows a tight bright specular highlight, high-roughness a broad dim one (physically expected); a diff image confirms only the expected highlight/Fresnel-rim difference, no discontinuities. Zoomed rim crops for both show smooth falloff, no bright/dark ring artifacts, no fireflies at the grazing edge.

**Anomalies to watch:**
- The pkg123-regression-row numeric discrepancy above (0.981 measured vs 0.947 claimed) — not gate-blocking, but worth reconciling in the PR discussion or a follow-up note.
- The stale in-file worst-case comment in `test_disney_energy_conservation.py` (claims <=1.0 when true worst is 1.004) should be corrected in a follow-up so it doesn't mislead future readers of that test file.

**Verdict: PASS**, bound to head SHA `84eb6a8c473807995bf558dc681cea309a856003`.
