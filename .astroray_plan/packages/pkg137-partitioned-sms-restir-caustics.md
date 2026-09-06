# pkg137 — Partitioned SMS + ReSTIR caustics (Hong et al. SIGGRAPH Asia 2025)

**Pillar:** 3 (light transport / interactive caustics)
**Track:** A (tile-partitioned SMS + reservoir reuse is CPU-verifiable; the wavefront caustics leg is verified on RTX)
**Codex-paste-ready:** no (tile-partitioned specular-manifold sampling fused with ReSTIR spatiotemporal reuse — depends on reservoir SoA infrastructure and SMS internals)
**Status:** superseded — by pkg227 general specular polynomials; partitioned-SMS+ReSTIR never started, no caller today (2026-09-07 backlog triage)
**Estimated effort:** L (high but staged per the research doc — partitioning-alone is a cheaper standalone first increment; the full method presupposes ReSTIR reservoirs)
**Depends on:** **pkg55 Phase C Session C6** (ReSTIR reservoir SoA + wavefront reuse stages — see `.astroray_plan/docs/pkg55-phase-c-plan-2026-07.md` §5) **and pkg127** (Specular Polynomials for SMS seed finding — the deterministic Newton-free seed solver this partitions the manifold walk around). Land after both. The **partitioning-alone** increment (below) can precede C6 as a standalone SMS robustness win.

---

## Goal

**Before:** Astroray's specular-manifold-sampling caustics (pkg64/pkg106 lineage) do
an unbounded Newton manifold walk per seed, with the classic SMS failure modes:
divergence from a bad seed and one-solution-per-seed. Caustics are offline-only and
noisy per frame.

**After:** Port Hong et al.'s **Partitioned SMS + ReSTIR** (SIGGRAPH Asia 2025;
Zeltner — the SMS originator — is a co-author): tile-based **sample-space
partitioning** bounds the Newton manifold walk to a local vicinity plus a per-frame
prior (killing the divergence/one-solution failures), and **ReSTIR spatiotemporal
reuse** amortizes sample generation across pixels and frames. Interactive-quality
caustics; the partitioning half alone is already a robustness win for our existing
SMS.

---

## Design sketch (cite the research doc; don't duplicate it)

Full source record: `.astroray_plan/docs/2026-07-pbr-advances-research.md` finding 2.

- **Sample-space partitioning (the standalone-able half):** partition the sample
  space into tiles; each tile bounds the manifold walk to a local vicinity + a
  per-frame prior, so the Newton solve starts near a solution and stays there. This
  directly attacks our SMS's bad-seed divergence and one-solution-per-seed limits —
  and it does **not** require ReSTIR, so it can ship first as a standalone SMS
  robustness increment.
- **ReSTIR spatiotemporal reuse (the amortization half):** reuse specular-sample
  reservoirs across neighbors and frames, built on the Phase-C C6 reservoir SoA. The
  reservoir `update`/`merge`/`finalizeWeight` core is the shared `__host__ __device__`
  template C6 establishes (`.astroray_plan/docs/pkg55-phase-c-plan-2026-07.md` §5,
  one-generator rule) — reuse it, do not transcribe.
- **Wavefront fit:** SMS seeds + reservoir reuse run as wavefront stages between shade
  and the next intersect, mirroring C6's reuse-stage placement.

**Staging (from the research doc):** partitioning-alone first (cheaper, no reservoir
dependency), then fold in ReSTIR reuse once C6's reservoirs exist.

---

## Implementation plan

- **Phase 0 — license.** Verify the Falcor module `PSMS-ReSTIR` license against the
  actual repo (Falcor base is BSD-3; the module license is the phase-0 check per
  CLAUDE.md §6). Falcor/RTXDI-proprietary reservoir code must not be mirrored — reuse
  our C6 reservoir core.
- **A. Sample-space partitioning (standalone).** Tile the SMS sample space; bound the
  Newton walk to a tile + per-frame prior. Gate: fewer diverged/failed seeds and
  lower caustic variance than current SMS at equal cost. **Can land before C6.**
- **B. ReSTIR reuse over specular reservoirs.** Build on C6's reservoir SoA + shared
  template; add spatiotemporal reuse of specular samples. Gate: temporal variance
  reduction on a caustics scene (analogous to the C6 temporal-variance gate).
- **C. Wavefront integration + caustics gate.** Wire as wavefront stages; verify
  interactive-quality caustics vs the offline SMS reference (SSIM/energy-parity gate
  in the pkg64 style).

---

## Acceptance criteria

- [ ] Phase-0 Falcor `PSMS-ReSTIR` module license verified; no RTXDI/proprietary
      reservoir code mirrored (C6 reservoir core reused).
- [ ] Sample-space partitioning bounds the Newton walk; measurably fewer
      diverged/failed seeds + lower caustic variance than current SMS (standalone,
      before C6).
- [ ] ReSTIR spatiotemporal reuse over specular reservoirs built on the C6 SoA +
      shared reservoir template (one-generator rule honored — no transcription).
- [ ] Interactive-quality caustics gate vs the offline SMS reference (SSIM +
      energy-parity, pkg64 style); temporal-variance reduction demonstrated.
- [ ] CPU↔GPU wavefront-diff parity for the new stages; no regression to offline SMS.

---

## Non-goals

- **Not a new reservoir subsystem.** Reuses pkg55 Phase C C6's reservoir SoA + shared
  template; does not build parallel ReSTIR infrastructure.
- **Not Specular Polynomials seed-finding.** Newton-free polynomial seed finding
  (research finding 1) is **pkg127** (a dependency, not re-implemented here) — this
  package bounds the manifold walk via partitioning around pkg127's seeds; it does
  not replace the solver.
- **Not general ReSTIR-PT / GRIS.** Path-space resampling generalization is the C6 /
  GRIS roadmap; pkg137 is caustics-specific reuse.

---

## Algorithm sourcing (CLAUDE.md §6)

- **Hong, Duan, Wang, Yuksel, Zeltner, Lin**, "Partitioned SMS + ReSTIR" (interactive
  caustics), SIGGRAPH Asia 2025, DOI 10.1145/3757377.3763927 (co-author = SMS
  originator Zeltner). Ref impl: Falcor 8.0 module
  `github.com/Utah-Graphics-Lab/PSMS-ReSTIR` (**Falcor base BSD-3; module license =
  phase-0 VERIFY**).
- **Zeltner et al.** — Specular Manifold Sampling (the SMS foundation Astroray already
  ports, pkg64/pkg106) — the method this bounds.
- **GRIS — Lin, Kettunen, Bitterli, Pantaleoni, Yuksel, Wyman**, "Generalized
  Resampled Importance Sampling", ACM TOG 41(4), SIGGRAPH 2022,
  DOI 10.1145/3528223.3530158 — the reservoir-reuse foundation (cited by C6). **NVIDIA
  RTXDI is proprietary — DISQUALIFIED; do not read or mirror it.**
- **Research doc:** `.astroray_plan/docs/2026-07-pbr-advances-research.md` finding 2
  (3-0, high) + adoption note ("after Phase C's reservoirs exist"; "partitioning alone
  is a cheaper standalone win").
- **C6 design:** `.astroray_plan/docs/pkg55-phase-c-plan-2026-07.md` §5 (reservoir SoA,
  one-generator rule).

---

## Provenance

Filed from the **PBR advances 2023–2026 research sweep (2026-07-17)**
(`.astroray_plan/docs/2026-07-pbr-advances-research.md` finding 2). Owner goal:
interactive-quality caustics for the black-hole / disk showcase. Depends on pkg55
Phase C C6 (ReSTIR reservoirs) + pkg127; the partitioning half is a standalone SMS
robustness win that can land earlier.

---

## Progress

- 2026-09-07 backlog triage: status flipped to `superseded`. Previous status text: still-open — never implemented; no partitioned-SMS/ReSTIR-caustics code in the repo (the existing `plugins/integrators/restir_di.cpp` is a separate ReSTIR direct-illumination path, not this caustics feature). Only the spec-filing PR #492 exists.

- [ ] Phase 0 — Falcor module license verification.
- [ ] A — sample-space partitioning (standalone SMS robustness; can precede C6).
- [ ] B — ReSTIR reuse over specular reservoirs (on the C6 SoA + shared template).
- [ ] C — wavefront integration + interactive-caustics gate.

---

## Lessons

*(Fill in after the package is done.)*
