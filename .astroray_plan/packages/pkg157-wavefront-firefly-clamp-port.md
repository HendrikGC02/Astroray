# pkg157 — Port pkg144 clampDirect/clampIndirect into the wavefront (restore the GPU firefly-clamp feature C7 dropped)

**Pillar:** 3 (GPU feature parity)
**Track:** A (RTX-gated)
**Codex-paste-ready:** no (small but placement-sensitive: clamp semantics must land at the exact accumulation sites or they bias energy)
**Status:** implemented, **HW-VERIFY PENDING** (PR #526, 2026-07-26 — clamp split re-ported to the wavefront at 4 accumulation sites + ReSTIR-DI; both stale whole-path `lum>20` caps removed; `G_WF_NEE_I_LANES` 3→4 to park the NEE sample's bounce depth for the deferred shadow-resolve; call-site + behavioral sweeps clean). **NOT built and NOT run** — the implementer had no CUDA build or GPU access; CI has no GPU, so CI green is not evidence. Flip to `done` only after the RTX verifier reports: build log, byte-identical 0/0 no-op vs pre-change wavefront, CPU-oracle mean-ratio agreement, and the revived #515 gate GREEN (not xfail/skip).
**Estimated effort:** S (device helpers exist; two insertion sites + one revived gate)
**Depends on:** pkg55-C7/PR #524. Reference implementation: pkg144/PR #515 (CPU + the deleted megakernels' `gpu_clampContrib`/`gpu_clampContribMW` wiring — recover the deleted call sites from git history at `9bb058fc`/#515 for the exact semantics).

**Origin:** pkg55-C7 deletion sweep (2026-07-25): the megakernels carried the only GPU wiring of pkg144's `clampDirect`/`clampIndirect` (#515, shipped 2026-07-23). Post-C7 the wavefront ignores both — a user setting clamps on a GPU render silently gets no clamping (defaults 0/0 = off, so default renders are unaffected). Recorded as a dropped feature in the C7 day-arc doc and the pkg55 spec.

---

## Contract

1. Port the clamp application into the wavefront with the SAME semantics as the #515 CPU/megakernel wiring (Cycles `film_clamp_light` lineage — cite as pkg144 did): **direct** clamp at the NEE/shadow-resolve contribution and emission-hit direct accumulation; **indirect** clamp at bounce≥2 path-contribution accumulation. Reuse the existing device helper (`gpu_clampContrib` family); do not re-derive.
2. CPU is the oracle: identical scene + clamps set, CPU vs wavefront clamped outputs agree within the standard per-channel mean-ratio band; clamps-off (0/0) renders BYTE-IDENTICAL to pre-pkg157 wavefront output (no-op guarantee).
3. **Revive the #515 GPU gate live** — `test_direct_and_indirect_clamp_controls` (or its successor) must run green against the wavefront on RTX; absence or xfail of the GPU leg is not acceptable evidence (memory `xfail-gated-features-must-unxfail`). Re-verify the #515 headline behaviors on the wavefront: bright-sun linearity stable, clampIndirect=10 suppresses fireflies at <0.02% brightness delta.
4. Update the pkg144 spec with a "wavefront wiring: pkg157" note on completion.

### ⚠️ Contract defects found during HW verification — OWNER ADJUDICATION NEEDED

Recorded 2026-07-26 (RTX 5070 Ti, PR #526). Two clauses above are **not
satisfiable as written**. Neither is a pkg157 implementation problem; both are
measurement errors baked into the spec. Flagged rather than silently reinterpreted.

**Item 2, "BYTE-IDENTICAL" — unsatisfiable by construction.** The GPU wavefront
is not bit-identical *even to itself*. Measured against itself, same seed, same
config, no clamp calls at all: `run1 vs run2 max|Δ| = 1.19e-07` (29/27648
elements), `run1 vs run3 = 8.94e-08`, neither bit-identical. Cause: `atomicAdd`
accumulation into per-pixel accumulators (`stage_advance.cu` `stageRegenKernel`)
+ non-associative float addition; the order dead paths land in varies per
launch. Predates pkg157 and is independent of it. **Proposed amendment:**
clamps-off agrees with pre-pkg157 output *within the 1e-5 wavefront MC
convention* (~4 orders of magnitude above the measured floor, so a real clamp
leak still fails loudly). Implemented that way in
`tests/test_pkg157_wavefront_firefly_clamp_port.py::test_gpu_wavefront_clamp_zero_is_noop`,
which documents the floor and warns against re-tightening.

**Item 3, "clampIndirect=10 suppresses fireflies at <0.02% brightness delta" —
scene-dependent, vacuous on the gate scene.** A clamp does nothing unless its
limit is below the scene's peak radiance. On a Cornell-scale scene (measured
peak ~1.76 linear) `clampIndirect=10` produces `max|Δ| = 0.00000` — it never
binds, so the "<0.02% delta" is trivially met by the clamp doing nothing, and
would still be met if the port were entirely unwired. #515 measured `10` on a
bright-sun scene with a far larger dynamic range. Measured on the gate scene:
`=1 → max|Δ| 0.14764`, `=0.1 → 0.20867` (both bind, monotonic). **Proposed
amendment:** state the limit as a fraction of the scene's measured peak, and
require the gate to assert the limit *can* bind before asserting its effect.
Implemented that way; the binding assertion runs first so a vacuous pass is
impossible.

## Non-goals

- New clamp features/defaults (pkg144's contract is the contract).
- Perf (pkg155) or the naive residual (pkg156).
