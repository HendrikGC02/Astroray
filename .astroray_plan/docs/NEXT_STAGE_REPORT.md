# Astroray Next Stage Report

**Date:** 2026-05-30 (Round 15 Wave 5 closeout — GPU glass energy + Heitz-2018 VNDF rough transmission, PR #404; refbank showcase re-author, PR #405)
**Prepared by:** Claude (Anthropic Code) — rewritten at the Wave 5 closeout (glass-energy fix + showcase polish).
**Scope:** post-Wave-5 next stage.

> Strategic gate: **RELEASED 2026-05-10** by pkg56 Phase C. Strategy in
> [`ROADMAP.md`](ROADMAP.md), full status in [`STATUS.md`](STATUS.md) (the
> Round 15 Wave 5 section is authoritative for the current state).

> ⚠️ The previous version's lead track was the general-caustics chain
> (pkg109→pkg110→pkg111). That chain is now **CPU-complete** (PRs #395/#397/#403).
> The new lead pool is the **glass / rough-transmission follow-ups** + the
> **CPU-only small fixes** + **pkg76 Classroom Gap 2 continuation**. The GPU
> photon-map port (pkg113) and the pkg64-gpu re-baseline are GPU-gated (no GPU
> in CI) — do them on RTX, not overnight.

---

## 1. Current state (one screen)

- **General-caustics chain CPU-COMPLETE.** pkg109 (world-space photon-map kd-tree,
  PR #395) → pkg110 (BSDF-driven photon bounce, hybrid auto-select, PR #397) →
  pkg111 (k-NN gather on any receiver into the default `path_tracer`, PR #403).
  "Drop ANY glass + light → caustics on ANY surface through the default path" now
  works on CPU.
- **GPU clear-glass energy bug FIXED (PR #404 / `8b7184b`).** The delta refraction
  `f = eta^2` was albedo-clamped to [0,1] by the JH upsampler in
  `gpu_material_sample_spectral`; white-furnace went **0.705 → 0.991 flat @ ior 1.5**
  (CPU was always 0.985). Also landed a **Heitz-2018 VNDF microfacet-dielectric
  rough-transmission rewrite** (PBRT-v4 `DielectricBxDF`, BSD-3-Clause; cross-checked
  vs Cycles `bsdf_microfacet.h`) — GPU rough glass is now energy-conserving for R≥0.1.
- **Showcase polish (PR #405 / `07a7d65`).** 6 reference-bank scenes re-authored
  (≥512², gate-green on RTX): true SF11 prism, glass-sphere-caustic, sms-reflective-
  metal-sphere, gr-schwarzschild, gr-kerr-94-faceon. pkg104's full harness/CI
  acceptance is **not** complete — these are Phase 2/3 implementation progress only.
- **No open PRs.** The PR queue is empty.
- **Blocked / not-overnight:** pkg113 (GPU photon-map port), the pkg64-gpu re-baseline,
  pkg55-B' CUDA sessions, pkg86-B GPU light tree — all need RTX hardware-verified gates
  (CI has NO GPU).

---

## 2. Deployable set (prioritized)

Ordered by value × overnight-shippability. CI is **Linux/CPU only** — pick CPU
work whose correctness can be gated without a GPU.

**OPEN ITEMS surfaced at the Wave 5 closeout (top of queue — pick these up first):**

1. **CPU rough-glass low-α residual** (S/M, CPU, gated locally). The Heitz-2018 VNDF
   rewrite fixed high roughness, but the CPU still loses energy at the R=0.05–0.1
   boundary (alpha 0.0064 floor) and lags GPU by a few % mid-roughness. Currently
   **xfail'd** (`test_disney_rough_glass_furnace_energy_cpu`). Needs the deeper
   low-alpha / smooth-fallthrough investigation (where does the rough lobe hand off to
   the delta lobe; is the alpha floor or the masking-shadowing term the loss). Likely a
   focused follow-up package. **Cite:** Heitz 2018 VNDF + PBRT-v4 `DielectricBxDF` (the
   same sources the GPU path already uses) — see
   `.astroray_plan/docs/vndf-microfacet-dielectric-research.md`.

2. **Two GPU gates need re-baselining/recalibration with written justification**
   (GPU-gated — do on RTX, NOT overnight; flag for the next HW sweep). The Wave 5 glass
   fixes legitimately changed GPU output for the better, so two pkg64-gpu gates now read
   below their floor: **pkg64-gpu parity SSIM 0.835 < 0.85** (dielectric caustic — GPU
   now diverges from the CPU's residual) and **pkg64-gpu Phase-3 prism PSNR delta
   −0.59 < −0.5 dB** (SMS caustic shift). These do **not** run on CI (no GPU) so they
   merged green. Re-baseline the references and/or recalibrate the floors **with written
   justification** under owner adjudication; do not silently lower a floor. Specs:
   `packages/pkg64-gpu-sellmeier-session2-multi-ior.md`,
   `packages/pkg64-gpu-spectral-caustics.md` (gate floors left UNCHANGED at this closeout
   pending that adjudication).

3. **disney-sweep Cycles reference.png needs a Blender re-render by the owner**
   (owner action, not an agent task). The Astroray-side fix landed (PR #405:
   `cycles_bless.py` sets `sensor_fit=VERTICAL` before `angle` so Blender derives the
   30° vfov on the vertical axis, matching Astroray), but the cross-engine Cycles
   `reference.png` is cross-engine and cannot be auto-blessed — it must be re-rendered
   via Blender by the owner.

4. **Rough-glass variance reduction / denoising-default** (M, CPU+GPU, candidate future
   package — NOT a correctness bug). Rough glass is high-variance: verified it frosts
   correctly at high spp; the see-through look at 72 spp is MC noise, not an energy bug.
   A rough-glass variance-reduction or denoising-default optimization is a candidate
   future package (cite the OIDN/OptiX denoiser path already in-tree, or a roughness-
   aware MIS / multiple-importance-sampled transmission lobe).

**Standing CPU-shippable pool (work top-down after the open items above):**

5. **pkg101 / pkg102 / pkg100** (S each, no research) — addon viewport vfov, HDRI/DOF
   aperture units, .blend importer camera intrinsics. Branches exist on origin;
   re-verify vs current main (some may already be on main — the Wave-4 re-verify check
   found pkg100/101/102 already landed for those), finish + merge any genuine gaps.
   Independent — parallelizable.
6. **pkg76 Classroom Gap 2 continuation** (M, partial) — Gap 2 landed the non-Principled
   shader-graph walk (PR #394), but the Classroom SSIM ≥0.85 gate is GPU-gated and was
   deferred. Land any remaining importer-side code + bpy-free unit tests on CI; defer the
   GPU SSIM gate to the next HW sweep.
7. **pkg104 reference-bank harness/CI completion** (M) — PRs #400/#405 re-authored
   showcase *scenes*, but the spec's harness/CI acceptance criteria (smoke job <60 s in
   CI, deliberately-broken-PR fails ≥1 gate, dark_disk / hue_spread sign-flip checks)
   are not all met. Finish the CPU-checkable harness pieces; the disney-sweep Cycles
   gate is blocked on open item 3.

NOT overnight: **pkg113 — GPU photon-map caustics + CPU/GPU parity** (the GPU port of the
now-CPU-complete chain), the pkg64-gpu re-baseline (open item 2), pkg55-B' CUDA sessions,
pkg86-B GPU light tree, SPPM-progressive + VCM (owner decision). All GPU-gated; CI has no
GPU. The full CPU↔GPU-equivalence picture + the SMS-vs-photon-map caustics fork is in
`.astroray_plan/docs/cpu-gpu-parity-status.md`. **Owner decision (2026-05-30):** the photon
map is the canonical caustic path on CPU+GPU; SMS-GPU (pkg64-gpu) is frozen/legacy — no
further SMS-GPU work, but the existing pkg64-gpu gates still need the documented re-baseline
above so the HW sweep isn't reporting a phantom regression.

---

## 3. Drop-in prompt for the next session

The authoritative overnight instructions live with the owner (the "overnight
ship-packages" prompt). In short: **work the §2 set top-down, one mergeable PR per
package, CPU-only, full local test + stale-call-site sweep before each push, poll CI
then `gh pr merge --squash --delete-branch`.** Start with the §2 OPEN ITEMS — item 1
(CPU rough-glass low-α residual) is the highest-value CPU-shippable follow-up; items 2
and 3 are GPU/owner-side and should be left for the HW sweep / owner, not attempted
overnight. Then work the standing pool (pkg101/102/100 re-verify, pkg76 Gap 2
continuation, pkg104 harness completion) in parallel. Cite papers per CLAUDE.md §6 for
any new algorithm (`/cite-algorithm`); for the rough-glass residual the sources are
already in `vndf-microfacet-dielectric-research.md`. Do NOT touch GPU-gated packages
(no GPU in CI) — pkg113, pkg64-gpu re-baseline, pkg55-B', pkg86-B all wait for RTX.

---

## 4. Coordination

- **One PR per package**, doc-only closeouts auto-merge on green CI (pr-reviewer
  doc-only rule). Source PRs need the independent-review SIGN-OFF/BLOCK gate (pkg98)
  before push.
- **CI is blind to GPU correctness** — a green CI is necessary but not sufficient for
  any glass/caustic/GR render change. Do not declare a round clean on CI green alone;
  run the full RTX hardware sweep at closeout (memory: `ci_has_no_gpu_runtime_blindspot`).
  The Wave 5 pkg64-gpu gate drift (open item 2) is exactly this class — it merged green
  and only the HW sweep will see it.
- **Visual check is mandatory for caustic/dispersion/rough-glass renders** — both
  `hue_spread` and `bright_coverage` can pass on dense chromatic salt-and-pepper noise,
  and rough glass looks see-through at low spp (MC noise, not a bug). Eyeball the PNG
  (memory: `general-photon-loop-needs-solid-glass`).
- **Grep `^Status:` (or `**Status:**`) in the spec before dispatching** — this report's
  §2 prose can go stale vs STATUS.md; the spec header is authoritative for done/open
  (memory: `orchestrator-next-stage-report-stale`).

---

## 5. After the round

- Flip any landed spec `Status:` lines to `done (PR #N, date — headline numbers)`.
- Update STATUS.md (new Wave section + the next pickup queue), ROADMAP.md (pillar
  status + long-tail), and rewrite this report's §1/§2 for the next round.
- Run the RTX hardware sweep; in particular re-baseline the two pkg64-gpu gates
  (open item 2) with written justification and re-confirm the Wave 5 glass fixes hold
  on hardware (white-furnace 0.991 flat across IOR, GPU rough glass energy-conserving
  for R≥0.1).
- Open ONE doc PR for the closeout; it is doc-only and auto-merge eligible.
