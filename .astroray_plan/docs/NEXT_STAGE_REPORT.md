# Astroray Next Stage Report

**Date:** 2026-05-31 (Round 15 Wave 6 closeout — pkg104 CPU+cross-engine acceptance closed, pkg118 rough-glass root-cause, pkg64-gpu HW-sweep evidence, pkg117 nonmesh geometry)
**Prepared by:** Claude (Anthropic Code) — rewritten at the Wave 6 closeout (pkg104/pkg117 complete; pkg118 filed).
**Scope:** post-Wave-6 next stage.

> Strategic gate: **RELEASED 2026-05-10** by pkg56 Phase C. Strategy in
> [`ROADMAP.md`](ROADMAP.md), full status in [`STATUS.md`](STATUS.md) (the
> Round 15 Wave 6 section is authoritative for the current state).

> ⚠️ **UPDATE 2026-06-08:** pkg118 was attempted and **the multi-scatter-table
> approach is a DEAD-END** (see STATUS.md 2026-06-08 + `pkg118-multiscatter-energy-research.md`).
> Part A (forced-TIR pdf) landed (PR #415) but is gate-neutral; the furnace deficit is
> NOT single-scatter masking (it is worst at LOW roughness) — it is the CPU bespoke RGB
> `disney_sample` diverging from the energy-conserving GPU spectral closure path. pkg118
> is OPEN, **re-scoped** to a CPU formulation fix and is **no longer a quick CPU win**.
> The deployable set below (§2) treats pkg118 item 1 as superseded by this finding.
>
> The remaining lead pool is **pkg64-gpu gate resolution** (RTX owner adjudication) + the
> standing GPU-gated work (pkg113 GPU photon-map, pkg116, pkg108, pkg115, pkg76 Classroom).
> Clean CI-only CPU wins are largely exhausted; the next substantive work is GPU-gated
> (do on this RTX with hardware verification) or the pkg118 CPU rough-glass rewrite.

---

## 1. Current state (one screen)

- **pkg104 + pkg117 COMPLETE.** pkg104 (visual reference bank) closed CPU + cross-engine
  acceptance: PR #407 added 3 tests (`test_reference_bank_smoke.py`) on the REAL
  references (broken-render gate-fails; prism hue_spread 0.753 ≥ 0.7; Schwarzschild
  dark_disk 0.053 ≥ 0.03); PR #410 re-rendered the disney-sweep Cycles reference via
  Blender 5.1 with the FOV fix → SSIM 0.7611 ≥ 0.65. pkg117 (nonmesh geometry) routes
  CURVE/SURFACE/FONT/META via `to_mesh()` + `to_mesh_clear()` (PR #411, 4 tests + 10
  existing pass; Blender 5.1 headless check confirms 288/58/170 polys).
- **pkg118 filed — rough-dielectric multi-scatter energy compensation.** The xfail'd
  `test_disney_rough_glass_furnace_energy_cpu` residual is **NOT** VNDF/low-alpha — it
  is **missing Kulla-Conty multi-scatter** (single-scatter masking loss + forced-TIR
  delta over-count partially cancel at high roughness, diverge at low). PR #408 documented
  the root cause + filed `packages/pkg118-rough-dielectric-multiscatter-energy.md` with
  the fix plan (dielectric E precompute table + PBRT-v4 TIR pdf correction).
- **pkg64-gpu SMS gates drift documented (GPU improved, frozen gates measure vs stale
  baselines).** PR #409 confirmed on RTX: parity SSIM 0.8352 < 0.85, Phase-3 prism PSNR
  −0.59 dB < −0.5. Cause: Wave-5 glass fix (PR #404) legitimately improved GPU; the
  frozen SMS-GPU gates didn't update. Evidence doc `pkg64-gpu-hw-sweep-2026-05-31.md`;
  OWNER-RESERVED (no floor change applied). PSNR gate needs re-bless; SSIM parity gate
  needs owner choice (xfail-as-legacy recommended, or recalibrate).
- **Blender 5.1 is installed on this machine.** Agents CAN now re-bless cross-engine
  Cycles references (was "owner Blender re-render"; PR #410 did it).
- **No open PRs.** The PR queue is empty.
- **Blocked / not-overnight:** pkg113 (GPU photon-map port), pkg64-gpu gate resolution
  (owner adjudication), pkg55-B' CUDA sessions, pkg86-B GPU light tree — all need RTX
  hardware-verified gates (CI has NO GPU).

---

## 2. Deployable set (prioritized)

Ordered by value × overnight-shippability. CI is **Linux/CPU only** — pick CPU
work whose correctness can be gated without a GPU.

**Top priority (CPU-shippable):**

1. **pkg118 — CPU rough-dielectric multi-scatter energy compensation** (M, CPU-gated).
   The xfail'd `test_disney_rough_glass_furnace_energy_cpu` now has a root-cause
   (PR #408 / `packages/pkg118-rough-dielectric-multiscatter-energy.md`): missing
   Kulla-Conty multi-scatter on the rough dielectric transmission lobe. Single-scatter
   masking loss + forced-TIR delta over-count partially cancel at high roughness (~0.96),
   diverge at low (0.77/0.81). Fix: (A) correct the forced-TIR delta throughput (PBRT-v4
   §9.5 TIR pdf = 1, not Fresnel×transmission), (B) precompute `E_glass(alpha, mu, eta)`
   table (MC integration of the single-scatter rough dielectric BSDF, Heitz 2016 + Kulla-
   Conty 2017 multi-scatter factor), apply to rough transmission like the reflection
   lobe already does. Furnace gate wants [0.95, 1.02] for R∈{0.1,0.3,0.6,1.0}. **Cite:**
   PBRT-v4 `DielectricBxDF`, Cycles `bsdf_microfacet.h` energy-conserving dielectric,
   Kulla-Conty 2017, Heitz 2016. Sources already in `vndf-microfacet-dielectric-research.md`
   UPDATE 3.

**Standing CPU-shippable pool:**

2. **pkg101 / pkg102 / pkg100** (S each, no research) — addon viewport vfov, HDRI/DOF
   aperture units, .blend importer camera intrinsics. Branches exist on origin;
   re-verify vs current main (Wave-4 check found pkg100/101/102 already landed — may be
   no work needed). Independent — parallelizable.
3. **pkg76 Classroom Gap 2 continuation** (M, partial) — Gap 2 landed the non-Principled
   shader-graph walk (PR #394), but the Classroom SSIM ≥0.85 gate is GPU-gated and was
   deferred. Land any remaining importer-side code + bpy-free unit tests on CI; defer the
   GPU SSIM gate to the next HW sweep.

**GPU-gated (NOT overnight — do on RTX):**

4. **pkg64-gpu gate resolution** (owner adjudication needed). PR #409 HW-sweep evidence
   doc `pkg64-gpu-hw-sweep-2026-05-31.md` confirms both SMS gates drifted: parity SSIM
   0.8352 < 0.85, Phase-3 prism PSNR −0.59 dB < −0.5. Root cause: Wave-5 glass fix
   (PR #404) legitimately improved GPU; the frozen SMS-GPU gates measure vs stale
   baselines. The two gates need different fixes: (a) PSNR gate = re-bless the stored
   high-spp reference (clean reference update); (b) SSIM parity gate = owner picks
   xfail-as-legacy (recommended; SMS-GPU frozen, pkg113 photon-map is canonical) OR
   recalibrate the floor. Owner action required — do NOT silently lower a floor.
5. **pkg113 — GPU photon-map caustics + CPU/GPU parity** (L, multi-session, GPU-verifiable
   on RTX). The GPU port of the now-CPU-complete chain (pkg109→pkg110→pkg111). Caustic
   photon map is the canonical path on CPU+GPU; SMS-GPU (pkg64-gpu) is frozen/legacy per
   owner decision 2026-05-30. Full CPU↔GPU-equivalence picture + caustics fork in
   `cpu-gpu-parity-status.md`.
6. **pkg116 — exporter cache refactor** (M, addon). Blender integration parity spec.
7. **pkg108 — addon residual triage**. Blender integration parity spec.
8. **pkg115 — shader-node textures**. Blender integration parity spec.
9. **pkg76 Classroom fidelity** — GPU investigation (SSIM ≥0.85 gate deferred from Gap 2).
10. **pkg55-B' CUDA sessions** (wavefront port continuation), **pkg86-B GPU light tree**,
    **SPPM-progressive + VCM** (owner decision). All GPU-gated; CI has no GPU.

**Note on test suite:** The full local test suite has **ONE expected failure**: the
pkg64-gpu parity SSIM gate (`test_pkg64_gpu_cpu_parity_ssim`) — this is the legitimate
owner-reserved drift (item 4 above), NOT a regression. Do not mis-diagnose it.

---

## 3. Drop-in prompt for the next session

The authoritative overnight instructions live with the owner (the "overnight
ship-packages" prompt). In short: **work the §2 set top-down, one mergeable PR per
package, CPU-only, full local test + stale-call-site sweep before each push, poll CI
then `gh pr merge --squash --delete-branch`.** Start with **pkg118** (CPU rough-
dielectric multi-scatter energy compensation, §2 item 1) — this is the highest-value
CPU-shippable package. Then work the standing pool (pkg101/102/100 re-verify, pkg76
Gap 2 continuation) in parallel. Cite papers per CLAUDE.md §6 for any new algorithm
(`/cite-algorithm`); for pkg118 the sources are already in
`vndf-microfacet-dielectric-research.md` UPDATE 3 + `pkg118-rough-dielectric-multiscatter-energy.md`.
Do NOT touch GPU-gated packages (no GPU in CI) — pkg64-gpu gate resolution, pkg113,
pkg55-B', pkg86-B, pkg116, pkg108, pkg115, pkg76 Classroom SSIM all wait for RTX.

---

## 4. Coordination

- **One PR per package**, doc-only closeouts auto-merge on green CI (pr-reviewer
  doc-only rule). Source PRs need the independent-review SIGN-OFF/BLOCK gate (pkg98)
  before push.
- **CI is blind to GPU correctness** — a green CI is necessary but not sufficient for
  any glass/caustic/GR render change. Do not declare a round clean on CI green alone;
  run the full RTX hardware sweep at closeout (memory: `ci_has_no_gpu_runtime_blindspot`).
  The Wave-6 pkg64-gpu gate drift (§2 item 4) is exactly this class — it merged green
  and only the HW sweep sees it.
- **Visual check is mandatory for caustic/dispersion/rough-glass renders** — both
  `hue_spread` and `bright_coverage` can pass on dense chromatic salt-and-pepper noise,
  and rough glass looks see-through at low spp (MC noise, not a bug). Eyeball the PNG
  (memory: `general-photon-loop-needs-solid-glass`).
- **Grep `^Status:` (or `**Status:**`) in the spec before dispatching** — this report's
  §2 prose can go stale vs STATUS.md; the spec header is authoritative for done/open
  (memory: `orchestrator-next-stage-report-stale`).
- **Blender 5.1 is installed on this machine** — agents can re-bless cross-engine Cycles
  references (PR #410 proves it). No longer an "owner Blender re-render" blocker for
  pkg104-family cross-engine work.

---

## 5. After the round

- Flip any landed spec `Status:` lines to `done (PR #N, date — headline numbers)`.
- Update STATUS.md (new Wave section + the next pickup queue), ROADMAP.md (pillar
  status + long-tail), and rewrite this report's §1/§2 for the next round.
- Run the RTX hardware sweep; in particular adjudicate the two pkg64-gpu gates (§2
  item 4 — PSNR re-bless + SSIM parity xfail-vs-recalibrate owner choice) and re-confirm
  the Wave-5/6 glass fixes hold on hardware (white-furnace 0.991, GPU rough glass
  energy-conserving R≥0.1).
- Open ONE doc PR for the closeout; it is doc-only and auto-merge eligible.
