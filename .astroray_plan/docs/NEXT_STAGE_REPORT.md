# Astroray Next Stage Report

**Date:** 2026-08-25 (FRESH ARCHITECT-LED planning pass — autonomous-session
open). Regenerates the 2026-08-23 report (pkg219a/b/c + pkg217 have since LANDED —
#640/#641/#642/#643). Canonical pickup queue for the orchestrator / dispatch-next.
Every item is grounded in the live project index or a cited in-code finding; grep
`^**Status:**` in each spec before dispatch (memory
`orchestrator-next-stage-report-stale`).

> Strategy: `ROADMAP.md`. Full state: `STATUS.md` (top entry 2026-08-21→22).

---

## 0. Pending-state facts the orchestrator must carry (NOT tasks to redo)

- **Stale `.pyd`:** rebuild `build_cuda` before ANY GPU verification this session
  (memory `stale_pyd_locations`, `incremental-build-signature-staleness`; verify
  `astroray.__file__` canonical + `cuobjdump --list-elf` sm_120 before trusting a
  gate). CI has no GPU — never declare a caustic/normal-map round clean on CI alone
  (memory `ci_has_no_gpu_runtime_blindspot`).
- **pkg214fix** (sodium/mercury energy-normalization; PR #629 was HW-FAIL) may still
  be in flight on branch `pkg214fix`. It **BLOCKS pkg222** (same generator +
  `profiles.bin`). Confirm it landed before dispatching pkg222; re-verify sodium AND
  mercury together (peak-vs-energy normalization coupling).
- **Pillar 4 remains PAUSED** (pkg45/46/48/49/50/51/107, incl. pkg218 Thread B — the
  swappable observer / camera response function). Surface the unpause decision to
  the owner; do not self-dispatch it. pkg222 extracts ONLY the pkg218 Thread A data
  fix (spectral correctness), which is not Pillar-4-paused.

---

## 1. State in one screen

- Spectral milestone + Blender-integration sweep shipped. Shader-node compatibility
  advanced hard: **pkg219a (coordinate/Mapping unification), pkg219b (bounded op-VM
  core), pkg219c (opcode fill-out) all LANDED** (#640/#641/#642). **pkg217 caustics
  LANDED via Path A** (#643) — but see §2: the caustic wiring exposed two deeper
  physics bugs the wiring fix did NOT address.
- Owner live priorities: **Blender shader-node compatibility, caustics, Cycles +
  CPU/GPU parity, opportunistic perf** (1.5s perf ceiling STAYS — no dedicated perf
  packages, memory `wavefront-perf-ceiling-owner-decision`).
- **New this pass (two caustic physics findings, CONFIRMED IN CODE):** the
  now-wired GPU caustic (a) rebuilds a byte-identical photon map every iteration so
  its noise never averages (→ pkg220), and (b) samples photon λ uniformly and
  deposits SPD-blind power so a narrow-line lamp throws an impossible rainbow caustic
  (→ pkg221). These are separate from pkg217's addon-wiring fix.

---

## 2. Prioritized set for THIS session (4–7, ordered)

Tier key: **grunt** = open-weight via `delegate`, evidence-verified; **impl** =
`package-implementer`; **dv4** = deepseek-v4-pro / sonnet (well-specified, gated);
**Claude** = last-line judgment (register/ABI/parity); **hw** = `hardware-verifier`.

### FILED THIS PASS (thorough, self-contained specs — dispatch-ready)

1. **pkg220 — Progressive GPU photon-caustic seed.** *What:* thread a per-iteration
   seed into `kEmitSceneCaustic`/`buildCausticAim` so successive photon maps are
   independent and the caustic averages ~1/√N. *Why now:* caustics are permanently
   grainy — a visible quality bug that the pkg217 wiring fix newly exposed. *Effort:*
   S–M. *Tier:* **dv4** (plumbing + a clean convergence gate; register-neutral).
   *Gating:* none. **Cheapest high-value win — dispatch first.**

2. **pkg221 — Photon λ importance-sampled from the light SPD.** *What:* draw photon
   wavelengths ∝ the emitting light's SPD (CDF built host-side, CPU+GPU), weight the
   deposit so white stays white and narrow-line lamps throw line-colored caustics.
   *Why now:* emission-line dispersion is physically impossible today (SPD-blind,
   engine-wide). *Effort:* M–L. *Tier:* **dv4** + `cite-algorithm` (PBRT spectral IS)
   + `cycles-parity-reviewer`. *Gating:* shares `kEmitSceneCaustic` with pkg220 —
   land pkg220 first, rebase this on top.

3. **pkg222 — Atomic-line lamp SPDs: cited, chromatically-correct.** *What:* re-derive
   preset atomic-line lamp line intensities from NIST/measured data, regenerate
   `profiles.bin`, audit every lamp's chromaticity (mercury magenta→greenish-white).
   *Why now:* every atomic-line lamp renders the wrong color; makes pkg221's
   emission-line dispersion *correct-colored*. *Effort:* M (data, no engine C++).
   *Tier:* **dv4** (citation + A/B render discipline). *Gating:* **BLOCKED by
   pkg214fix** (same generator) — confirm it landed first.

4. **pkg223 — Normal Map node (pkg219d part 1).** *What:* tangent-space normal-texture
   perturbation of the shading normal, CPU+GPU, behind `<bool HasNormalPerturb>`.
   Bump deferred. *Why now:* normal maps are ubiquitous and silently do nothing today
   — the biggest remaining shader-node usability gap after pkg219a-c. *Effort:* M–L.
   *Tier:* **dv4** implement, but the **GPU shade-kernel register budget is
   Claude-last-line** — HARD `cuobjdump` REG probe gate + `cpp-abi-guard` + Claude
   review before merge; spill → escalate. *Gating:* reuses pkg219a coordinate path.

### EXISTING OPEN WORK — weighed, sequenced behind the above

5. **pkg201 Stage 3 — per-type bounce counters + `filter_glossy` + native caustic
   toggles.** Closes the last register-hostile pkg200 honour-matrix rows. *Effort:* L.
   *Tier:* **Claude** (register-hostile). *Note:* the caustic-toggle row now LOGICALLY
   couples to the landed pkg217 + the new pkg220/221 caustic work — wire the toggle to
   the existing pipeline, don't reimplement. Non-caustic rows (bounce counters,
   filter_glossy) can go independently as a **dv4** slice. Pick up behind 220–223.

6. **pkg131 — Zero-knob adaptive sampling, wavefront leg.** Long-standing; convergence
   quality (not raw perf — respects the ceiling). *Effort:* L. *Tier:* impl/dv4.
   *Gating:* none; fill a free slot behind Themes above.

### NOT this session (surface to owner)

- **pkg218 Thread B** (swappable CIE observer / camera spectral-sensitivity) —
  Pillar-4-paused; research-grade capability, owner said "not the current main
  focus." Leave paused; do not dispatch. pkg222 already carves out Thread A.
- **pkg217 SMS-NEE-cull quality upgrade** — the sharper forward-caustic method noted
  in pkg217's CORRECTION; only if the photon caustic (post-220/221) shows residual
  quality limits. Do not pre-empt.

---

## 3. Real forks for the owner (not an artificial ballot)

- **Caustic depth:** pkg220 (decorrelate) + pkg221 (SPD λ) make the *existing* photon
  caustic converge and be spectrally correct — cheap, high-value, dv4-implementable.
  The alternative "sharper" path (SMS-NEE-cull, pkg217's deferred design) is L,
  register-hostile, and Claude-only. **Recommendation:** ship 220+221 first; only
  invest in SMS if their converged quality proves insufficient. Owner: agree, or go
  straight for SMS?
- **pkg222 vs pkg214fix ordering:** both touch `build_spectral_profiles.py` /
  `profiles.bin`. pkg222 is BLOCKED on pkg214fix landing. If pkg214fix has stalled,
  the owner may want to fold the mercury green-line fix INTO the pkg214fix branch
  rather than a separate pkg222. **Flag:** is pkg214fix still open?
- **pkg223 register risk:** Normal Map perturbs the REG:254 shade normal. If the probe
  spills despite `<bool HasNormalPerturb>` isolation, do we accept a bounded non-map
  STACK cost, or hold the feature? Default: hold + escalate (never ship a fleet-wide
  regression).

---

## 4. Top items to dispatch first (with routing)

1. **pkg220** → `package-implementer` (dv4 tier). Independent, cheapest high-value
   caustic fix; clean convergence gate. Rebuild the stale `.pyd` first.
2. **pkg221** → dv4 implementer + `cite-algorithm` + `cycles-parity-reviewer`, AFTER
   pkg220 (shared kernel).
3. **pkg223** → dv4 implementer, HARD REG-probe gate + `cpp-abi-guard` + Claude
   review before merge.
4. **pkg222** → dv4 implementer — ONLY after confirming pkg214fix landed.

Breadth research (NIST line intensities for pkg222, extra caustic/normal-map parity
scenes, Cycles Normal Map handedness confirmation) → `delegate` open-weight,
evidence-verified, scoped to ONE narrow deliverable each (memory
`delegate-grunt-budget-bound-tight`).

---

## 5. Specs filed this pass

- **pkg220** — `packages/pkg220-caustic-per-iteration-seed.md` (Track A, dv4).
- **pkg221** — `packages/pkg221-photon-wavelength-spd-importance-sampling.md`
  (Track A, dv4).
- **pkg222** — `packages/pkg222-atomic-line-lamp-spd-chromaticity.md` (Track A, dv4;
  extracts pkg218 Thread A; BLOCKED on pkg214fix).
- **pkg223** — `packages/pkg223-normal-map-node.md` (Track A, dv4 + Claude gate;
  pkg219d part 1, Bump deferred).
