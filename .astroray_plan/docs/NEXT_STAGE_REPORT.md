# Astroray Next Stage Report

**Date:** 2026-08-23 (FRESH ARCHITECT-LED planning pass — goal-capture mode).
**Prepared by:** architect. This regenerates the stale prior report and is the
canonical pickup queue for the orchestrator / dispatch-next. Every item below is
grounded in the live project index (`scripts/project_index.py`) or a cited
research note; grep `^**Status:**` in each spec before dispatch (memory
`orchestrator-next-stage-report-stale`).

> Strategy gate RELEASED (pkg56 Phase C, 2026-05-10). Strategy: `ROADMAP.md`.
> Full state: `STATUS.md` (top entry 2026-08-21→22).

---

## 0. Pending-state facts the orchestrator must carry (NOT tasks to redo here)

- **PR #638 (GPU lamp red-shift fix) is OPEN, CI-green, NOT merged** — needs RTX
  hardware verification before merge. Dispatch a `hardware-verifier` on it.
- **The `build_cuda` `.pyd` is STALE vs HEAD** — rebuild before ANY GPU
  verification this session (memory `stale_pyd_locations`,
  `incremental-build-signature-staleness`; verify `astroray.__file__` +
  `cuobjdump --list-elf` sm_120 before trusting a gate).
- **Pillar 4 remains PAUSED** (pkg45/46/48/49/50/51/107, incl. pkg218 spectral
  colorimetry) — no new unpause directive; skip for autonomous work. Surface the
  unpause decision to the owner but do not self-dispatch it.

---

## 1. State in one screen

- Spectral milestone shipped (pkg213/214/215/206/216 + #635/#637/#638); fresh
  `dist/astroray-4.0.0-cuda.zip` built + headless-verified. 0 open PRs at closeout
  except #638 (above).
- The Integration Milestone is closed; the owner's live priorities are now
  **Blender shader-node compatibility, caustics, Cycles + CPU/GPU parity, and
  opportunistic perf** (perf ceiling of 1.5s STAYS — no dedicated perf packages,
  memory `wavefront-perf-ceiling-owner-decision`).
- **Key discovery this pass:** the two headline "hard" items are *less* hard than
  their stubs implied. pkg217 caustics is a **wiring** problem (CPU SMS + device
  solver + caster-flag plumbing all already exist — see research note); pkg219
  shader-graph is **decomposable** into an independently-useful pkg219a plus a
  bounded op-VM. Both specs are now refined to implementable and their forks decided.

---

## 2. Prioritized roadmap for THIS session (ordered, by owner theme)

Effort key: S<M<L<XL. Tier: **grunt** = open-weight via `delegate` skill,
evidence-verified; **impl** = `package-implementer`; **Claude** = judgment-heavy
implementer/parity; **research/architect** = me; **hw** = `hardware-verifier`.

### THEME A — Blender shader-node compatibility (BIGGEST usability lever; owner-named #1)

1. **pkg219a — Coordinate + Mapping unification.** Full 3-D Mapping matrix (incl.
   X/Y rotation) + real Generated/Object/Camera/Window TexCoord. *Why now:* fixes
   half the owner's `Material.001` repro on its own, needed regardless of the VM
   fork, unblocks 219b. *Effort:* M. *Tier:* impl. *Gating:* none. **Dispatch first.**
2. **pkg219b — Bounded op-VM core.** `uint4` bytecode compiler + CPU + GPU
   evaluator, static stack bound, `<bool HasProgram>` isolation, REG probe gate.
   Ships Color-Ramp / Mix / Math / MapRange. *Why now:* kills the single biggest
   usability gap (Color-Ramp-on-texture always greys). *Effort:* L. *Tier:* Claude
   (register budget + GPU device interpreter = last-line-of-defense judgment).
   *Gating:* after 219a (shares the coordinate path); needs `cite-algorithm`
   (Cycles SVM) + `cpp-abi-guard` + REG probe.
3. **pkg219c — Opcode coverage fill-out.** HSV/Invert/Gamma/BrightContrast/
   Separate-Combine/Bump/NormalMap, each a Cycles parity render. *Effort:* M.
   *Tier:* impl. *Gating:* after 219b (extends its opcode table).

### THEME B — Cycles + CPU/GPU parity (owner-named; unblocks honour-matrix debt)

4. **pkg201 Stage 3 — per-type bounce counters + `filter_glossy` + native caustic
   toggles.** Closes the last register-hostile pkg200 honour-matrix rows. *Why now:*
   register-contention window is clear per its own Status; direct Cycles-parity debt.
   *Effort:* L. *Tier:* Claude (register-hostile, probe-gated). *Gating:* the
   `caustics_reflective/refractive` toggle rows LOGICALLY OVERLAP pkg217 — sequence
   201-S3's caustic-toggle row *with or after* pkg217, do not implement the toggle
   twice. Non-caustic rows (bounce counters, filter_glossy) can go independently.

### THEME C — Caustics (owner-named; real feature, owner-deprioritized vs above)

5. **pkg217 — GPU refractive/dispersive caustics (wiring).** New
   `stage_caustic_connect.cu`, ordinary-NEE cull, reuse `sms_attempt_device.cuh`.
   *Why now:* the black-shadow-through-glass is a visible correctness bug and the
   machinery already exists; owner deprioritized vs shader nodes but it is L not XL.
   *Effort:* L. *Tier:* Claude (wavefront + register gate + NEE-cull correctness =
   judgment). *Gating:* `cite-algorithm`, REG probe HARD gate, visual+parity gates;
   verify the CPU refractive-caustic path first (may already work post-#637).
6. **pkg127 — Specular Polynomials for SMS seed finding (deferred seed upgrade).**
   *Why now:* only AFTER pkg217 lands and shows residual seed-failure noise; it is a
   quality upgrade, not a prerequisite. *Effort:* L. *Tier:* Claude. *Gating:* do
   NOT couple to pkg217; dispatch only if 217's caustics show seed-waste.

### THEME D — Opportunistic quality (no dedicated perf packages — ceiling stays)

7. **pkg131 — Zero-knob adaptive sampling, wavefront leg.** Long-standing open;
   convergence quality win, not a raw-perf lever (respects the 1.5s ceiling).
   *Effort:* L. *Tier:* impl. *Gating:* none; low priority — pick up if a slot is
   free behind Themes A–C.

### IN-FLIGHT / carried (finish before starting new work in the same files)

- **#638 HW verify + merge** — `hardware-verifier`, then `pr-reviewer`. **Do first.**
- **pkg214fix** — physics-correct energy-normalisation on branch `pkg214fix` (PR
  #629 HW-FAIL, do NOT merge as-is). Re-verify sodium AND mercury together. *Tier:*
  Claude + hw. Blocks anything touching `build_spectral_profiles.py`.
- **pkg206** — re-verify the flat-baseline SSIM gate specifically (prior failure
  mode) on branch `pkg206impl*`. *Tier:* hw.

---

## 3. Real forks for the owner (not an artificial ballot)

- **pkg219 depth:** ship 219a+219b now (bounded VM) vs commit to full-SVM (a) as
  one XL. I chose the staged bounded-VM (research note) — it delivers usable value
  in M+L and is a strict on-ramp to (a). Owner can override toward full-SVM if the
  op-VM coverage proves insufficient in practice.
- **pkg217 vs pkg201-S3 caustic-toggle ordering:** these two touch the same
  caustic-honour surface. Either (i) do pkg217 first then 201-S3 wires the toggle to
  it, or (ii) 201-S3 lands the toggle as a no-op stub then pkg217 fills it. (i) is
  cleaner — recommended.
- **Sequencing pressure:** Theme A (shader nodes) is the owner's stated #1 usability
  lever; Theme C (caustics) is owner-deprioritized. If implementer slots are scarce,
  spend them A → B → C, not C first.

---

## 4. Top 3 to dispatch first (with routing)

1. **#638 HW-verify + merge** → `hardware-verifier` then `pr-reviewer`. (Rebuild the
   stale `.pyd` first.)
2. **pkg219a — Coordinate + Mapping unification** → `package-implementer` (impl
   tier). Independently useful, unblocks 219b, no gating.
3. **pkg219b — Bounded op-VM core** → Claude-implementer (register + GPU
   interpreter judgment), after 219a; run `cite-algorithm` (Cycles SVM) +
   `cpp-abi-guard` + REG probe.

Research fan-out / breadth scouring (opcode-semantics enumeration for 219c, extra
caustic-scene collection) → delegate to open-weight models via the `delegate`
skill, evidence-verified.

---

## 5. Specs filed / refined + research saved this pass

- Refined `pkg217` → implementable (wiring reframing, separate-stage design).
- Decided + staged `pkg219` → 219a/219b/219c, fork (c) bounded op-VM.
- Research note `docs/pkg217-wavefront-caustic-integration-research.md`.
- Research note `docs/pkg219-per-texel-svm-evaluator-research.md`.
