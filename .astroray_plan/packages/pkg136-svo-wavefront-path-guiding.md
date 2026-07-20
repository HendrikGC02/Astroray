# pkg136 — SVO-based wavefront path guiding (Yalçıner & Akyüz 2024)

**Pillar:** 3 (light transport / path guiding)
**Track:** A (SVO build + cone-trace PDF query is CPU-verifiable; the wavefront guiding leg is verified on RTX)
**Codex-paste-ready:** no (a global sparse-voxel-octree of radiant exitance + on-the-fly PDF/CDF via cone tracing, wired into wavefront sampling — a guiding subsystem, research-grade)
**Status:** open
**Estimated effort:** M (moderate per the research doc — one global SVO, cone-trace query, no persistent per-region PDF storage)
**Depends on:** **pkg55 Phase C completion** — guiding wires into the wavefront sampling stage, and Phase C stabilizes the wavefront as the *only* pipeline (a moving target otherwise). **Phase-0 task:** locate and license-verify a public reference implementation; if none exists, plan a **paper-only port** (the research doc flags "no confirmed public repo — VERIFY availability"). Land after Phase C.

---

## Goal

**Before:** Astroray samples continuation directions from the BSDF (and NEE for
direct light). In scenes where indirect radiance is concentrated (accretion-disk
glow, bright envmap regions seen through complex transport), unguided sampling wastes
paths on low-contribution directions — high variance that adaptive sampling (pkg131)
can only partly absorb.

**After:** Port the **SVO-based wavefront path-guiding** method (Yalçıner & Akyüz,
Computers & Graphics 2024): a single global **sparse voxel octree** stores
directionless **radiant exitance**; guiding PDFs/CDFs are generated **on-the-fly** via
cone-trace queries in shared memory — no persistent per-region PDF storage. Fixed
~3.96 MiB SVO (vs a PPG SD-tree at 19→37 MiB) makes it the **wavefront-native,
VRAM-frugal** guiding option — the uniquely-fitted match for our CUDA wavefront +
8–16 GB budgets. Guided sampling reduces variance on indirect-heavy scenes.

---

## Design sketch (cite the research doc; don't duplicate it)

Full source record: `.astroray_plan/docs/2026-07-pbr-advances-research.md` finding 7.

- **Global SVO of radiant exitance:** one sparse voxel octree over the scene stores a
  directionless radiant-exitance value per occupied voxel (built/updated from path
  contributions — cheap, no directional histograms per region).
- **On-the-fly PDF/CDF via cone tracing:** at a shading point, cone-trace the SVO in
  shared memory to synthesize a directional guiding PDF/CDF on demand, then sample it
  (optionally MIS-combined with the BSDF pdf). No persistent per-region PDF store —
  this is what keeps VRAM flat (~3.96 MiB).
- **Wavefront fit:** the query is a bounded cone-trace per guided sample, done inside
  the wavefront shade stage (`src/gpu/wavefront/stage_advance.cu`) — no per-region
  learned structure to store or synchronize across the SoA.

**Why this one and not OpenPGL:** OpenPGL is CPU-oriented (Cycles' guiding is
CPU-only) — a design reference, not a GPU drop-in. The SVO method is the wavefront-
native choice (research-doc finding 9 vs 7). Compose guiding with the BSDF via MIS.

---

## Implementation plan (after Phase C)

- **Phase 0 — reference + license.** Locate a public implementation; verify its
  license (Apache/BSD/MIT/MPL per CLAUDE.md §6). If none, plan a paper-only port and
  record that decision.
- **A. Global SVO build/update.** Sparse voxel octree of radiant exitance, updated
  from path contributions across waves.
- **B. Cone-trace PDF query + guided sampling.** Shared-memory cone-trace → on-the-fly
  directional PDF/CDF → sample; MIS-combine with the BSDF pdf in the wavefront shade
  stage.
- **C. Variance gate.** On an indirect-heavy reference scene, guided sampling reaches
  a target noise level in fewer samples than unguided (measured variance reduction);
  SVO VRAM stays within the paper's ~few-MiB envelope; guiding is unbiased (matches
  the unguided converged image within noise).

---

## Acceptance criteria

- [ ] Phase-0 reference-availability + license verification recorded (public impl or
      documented paper-only port).
- [ ] Global SVO of radiant exitance built/updated on the wavefront within a bounded
      (few-MiB) VRAM budget.
- [ ] On-the-fly cone-trace PDF/CDF query + guided sampling, MIS-combined with the
      BSDF; **unbiased** (converges to the unguided image within noise).
- [ ] Measured variance reduction vs unguided on an indirect-heavy scene.
- [ ] CPU↔GPU wavefront-diff parity for the guided-sampling path; no regression when
      guiding is off.

---

## Non-goals

- **Not OpenPGL / SD-tree guiding.** CPU-oriented; reference only. This package is the
  SVO wavefront-native method exclusively.
- **Not ReSTIR-PG.** Guiding × resampling fusion (research finding 10) is a horizon
  item requiring both a guiding and a ReSTIR-PT subsystem — out of scope.
- **Not photon-guiding.** 3D-Gaussian / photon-emission guiding (findings 4) augments
  the photon stage, a separate concern.

---

## Algorithm sourcing (CLAUDE.md §6)

- **Yalçıner & Akyüz**, "SVO-based wavefront path guiding", Computers & Graphics 121
  (2024) 103945, arXiv:2405.06997 — first guiding method designed for a wavefront GPU
  path tracer; global SVO of radiant exitance, on-the-fly PDF/CDF via cone tracing,
  ~3.96 MiB SVO. **No confirmed public repo — phase-0 VERIFY availability.**
- **OpenPGL** `github.com/OpenPathGuidingLibrary/openpgl` — Apache-2.0 — CPU-oriented
  guiding, **algorithm/design reference only** (not a GPU drop-in).
- **Research doc:** `.astroray_plan/docs/2026-07-pbr-advances-research.md` finding 7
  (3-0 core / 2-1 priority) + finding 9 (why not OpenPGL); NEXT_STAGE_REPORT horizon
  list ("the architectural match to our wavefront kernel — VERIFY repo availability").

---

## Provenance

Filed from the **PBR advances 2023–2026 research sweep (2026-07-17)**
(`.astroray_plan/docs/2026-07-pbr-advances-research.md` finding 7). Owner goal: the
wavefront-native, VRAM-frugal path-guiding option — variance reduction on
indirect-heavy scenes without the SD-tree memory cost. Sequenced after Phase C
stabilizes the wavefront as the only pipeline.

---

## Progress

- [ ] Phase 0 — reference-availability + license verification.
- [ ] A — global SVO of radiant exitance (build/update on wavefront).
- [ ] B — cone-trace PDF query + MIS-combined guided sampling.
- [ ] C — variance gate + VRAM-budget check; unbiasedness verified.

---

## Lessons

*(Fill in after the package is done.)*
