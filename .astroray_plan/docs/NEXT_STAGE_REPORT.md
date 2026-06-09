# Astroray Next Stage Report

**Date:** 2026-06-10 (Round closeout — pkg118 COMPLETE, pkg113 COMPLETE, pkg112 COMPLETE)
**Prepared by:** Claude (Anthropic Code) — rewritten at the 2026-06-10 round closeout (pkg118/pkg113/pkg112 closed).
**Scope:** post-2026-06-10 next stage.

> Strategic gate: **RELEASED 2026-05-10** by pkg56 Phase C. Strategy in
> [`ROADMAP.md`](ROADMAP.md), full status in [`STATUS.md`](STATUS.md) (the
> Round 15 Wave 6 section is authoritative for the current state).

> ⚠️ **UPDATE 2026-06-10:** **pkg118 SOLVED** (PR #423, 2026-06-08). The rough-glass
> furnace deficit was the **η² albedo-LUT clamp** (the CPU twin of the #404 GPU glass-dark
> bug): `Material::sampleSpectral` upsampled glass throughput through `RGBAlbedoSpectrum`,
> whose Jakob-Hanika ALBEDO LUT clamps rgb>1 to 1, clipping the exit refraction's eta²=2.25
> radiance recovery. Fix: factor the >1 magnitude out as a flat spectral scalar (mirrors
> GPU #404), upsample only the normalized tint. CPU furnace 0.77/0.82/0.92/0.97/0.96 →
> 0.89/0.94/1.00/1.00/1.00; `test_disney_rough_glass_furnace_energy_cpu` PASSES [0.92,1.03].
> **pkg118 DONE.** Also closed: **pkg113** (GPU photon-map caustics, all 3 phases merged +
> RTX-verified, PR #422/#424/#425) and **pkg112** (batched geometry upload, 31.7× speedup,
> PR #427).
>
> The next autonomous lead pool is **pkg114** (two-level BVH, TLAS/BLAS) → **pkg55**
> (wavefront SoA refactor) → **pkg64** (spectral caustics). All GPU-gated + RTX-verifiable.
> Clean CI-only CPU wins are exhausted; the next substantive work is GPU-gated (do on this
> RTX with hardware verification).
>
> **Owner directives (2026-06-08):** (1) **Pillar 4 (pkg45/46/48/49/50/51 + pkg107) is ON
> PAUSE** until the rest is working/stable/sufficiently progressed — do not pick it up.
> (2) The broken old-Blender benchmark scenes (Classroom/BMW27/Junkshop/UDIM_monster) were
> **removed**; **pkg76 Classroom/BMW27/Junkshop fidelity is dropped** from the pool.
> cornell is the only remaining Cycles-parity scene.

---

## 1. Current state (one screen)

- **pkg118 + pkg113 + pkg112 COMPLETE (2026-06-08→10).** pkg118 (rough-glass energy) SOLVED
  (PR #423): the η² albedo-LUT clamp (CPU twin of #404 GPU glass-dark bug) — fix = factor
  >1 magnitude out as flat spectral scalar; CPU furnace 0.77→0.89+, test PASSES [0.92,1.03].
  pkg113 (GPU photon-map caustics) all 3 phases merged + RTX-verified (PR #422/#424/#425):
  store, emission, gather; the phase-3 follow-up resolved (CPU exit-refraction sign bug,
  not GPU). pkg112 (batched geometry upload) 31.7× speedup (PR #427): one
  `add_triangles_bulk` pybind call per mesh, bit-identical render + real-Blender end-to-end.
- **pkg64-gpu SMS gates drift documented (GPU improved, frozen gates measure vs stale
  baselines).** PR #409 confirmed on RTX: parity SSIM 0.8352 < 0.85, Phase-3 prism PSNR
  −0.59 dB < −0.5. Cause: Wave-5 glass fix (PR #404) legitimately improved GPU; the
  frozen SMS-GPU gates didn't update. Evidence doc `pkg64-gpu-hw-sweep-2026-05-31.md`;
  OWNER-RESERVED (no floor change applied). PSNR gate needs re-bless; SSIM parity gate
  needs owner choice (xfail-as-legacy recommended, or recalibrate).
- **Blender 5.1 is installed on this machine.** Agents CAN now re-bless cross-engine
  Cycles references (was "owner Blender re-render"; PR #410 did it).
- **No open PRs.** The PR queue is empty.
- **Next autonomous work: GPU-gated + RTX-verifiable.** pkg114 (two-level BVH TLAS/BLAS) →
  pkg55 (wavefront SoA refactor) → pkg64 (spectral caustics). pkg108/pkg88 owner-blocked
  (reproduction scenes / open questions). Pillar 4 (pkg45/46/48/49/50/51 + pkg107) ON PAUSE
  per owner directive 2026-06-08.

---

## 2. Deployable set (prioritized)

Ordered by value × overnight-shippability. **pkg118, pkg113, pkg112 are DONE** (closed
this round). CI is **Linux/CPU only** — pick CPU work whose correctness can be gated
without a GPU.

**Top priority (autonomous, GPU-gated — do on RTX):**

1. **pkg114 — two-level BVH (TLAS/BLAS)** (GPU, RTX-verifiable, AUTONOMOUS). Enables
   instancing; natural follow-up to pkg112 (batched geometry upload). Large/multi-session;
   needs §6 research (cite Cycles `bvh2.cpp` TLAS/BLAS, PBRT-v4 ch.7 BVH construction,
   NVIDIA OptiX Programming Guide TLAS/BLAS split). **Start with a research pass** —
   locate canonical refs, save to `.astroray_plan/docs/pkg114-tlas-blas-research.md`,
   then implement.
2. **pkg55 — wavefront SoA refactor** (GPU, large, research already signed off per its
   spec). Laine 2013 per-material shade kernels; the pkg81-measured viewport-parity
   blocker (CUDA 104 ms vs CPU 58 ms — megakernel register pressure). Multi-session.
3. **pkg64 — spectral caustics** (huge, ~3–4 wk). The SMS CPU spectral caustic path.

**GPU-gated pool (OWNER-BLOCKED or owner-reserved):**

4. **pkg108 — addon residual triage** (owner questions: BUG-09/BUG-14 need the owner's
   reproduction scene; only BUG-16 subsurface is a candidate autonomous fix). Blender
   integration parity spec.
5. **pkg88 — motion blur** (4 owner questions remain in the spec). Blender integration
   parity spec.
6. **pkg64-gpu SMS gate resolution** (owner-reserved). PR #409 HW-sweep evidence doc
   `pkg64-gpu-hw-sweep-2026-05-31.md` confirms both SMS gates drifted: parity SSIM
   0.8352 < 0.85, Phase-3 prism PSNR −0.59 dB < −0.5. Root cause: Wave-5 glass fix
   (PR #404) legitimately improved GPU; the frozen SMS-GPU gates measure vs stale
   baselines. Owner action required — do NOT silently lower a floor.
7. **pkg116 — exporter cache refactor** (M, addon). Blender integration parity spec.
8. **pkg115 — shader-node textures**. Blender integration parity spec.
9. **pkg76 Classroom fidelity** — GPU investigation (SSIM ≥0.85 gate deferred from Gap 2).
   NOTE: the broken old-Blender benchmark scenes (Classroom/BMW27/Junkshop/UDIM_monster)
   were removed per owner directive 2026-06-08; pkg76 Classroom/BMW27/Junkshop fidelity
   is DROPPED from the pool. cornell is the only remaining Cycles-parity scene.
10. **pkg55-B' CUDA sessions** (wavefront port continuation), **pkg86-B GPU light tree**,
    **SPPM-progressive + VCM** (owner decision). All GPU-gated; CI has no GPU.

**Pillar 4 (PAUSED per owner directive 2026-06-08):**

- **pkg45/46/48/49/50/51 + pkg107** — all ON PAUSE until core rendering is
  working/stable/sufficiently progressed. **Do NOT pick up Pillar-4 specs.**

**Standing CPU-shippable pool (low priority or already verified stale):**

- **pkg101 / pkg102 / pkg100** (S each, no research) — addon viewport vfov, HDRI/DOF
  aperture units, .blend importer camera intrinsics. Branches exist on origin;
  re-verify vs current main (Wave-4 check found pkg100/101/102 already landed — may be
  no work needed). Independent — parallelizable.
- **pkg76 Classroom Gap 2 continuation** (M, partial) — Gap 2 landed the non-Principled
  shader-graph walk (PR #394), but the Classroom SSIM ≥0.85 gate is GPU-gated and was
  deferred. Land any remaining importer-side code + bpy-free unit tests on CI; defer the
  GPU SSIM gate to the next HW sweep. **OBSOLETED** by the 2026-06-08 owner directive
  (Classroom scene removed).

**Note on test suite:** The full local test suite has **ONE expected failure**: the
pkg64-gpu parity SSIM gate (`test_pkg64_gpu_cpu_parity_ssim`) — this is the legitimate
owner-reserved drift (item 6 above), NOT a regression. Do not mis-diagnose it.

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
