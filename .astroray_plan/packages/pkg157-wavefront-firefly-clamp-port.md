# pkg157 — Port pkg144 clampDirect/clampIndirect into the wavefront (restore the GPU firefly-clamp feature C7 dropped)

**Pillar:** 3 (GPU feature parity)
**Track:** A (RTX-gated)
**Codex-paste-ready:** no (small but placement-sensitive: clamp semantics must land at the exact accumulation sites or they bias energy)
**Status:** open — **TOP-OF-QUEUE FAST-FOLLOW** for the round after PR #524 merges (architect adjudication V3 in the pkg55 spec, 2026-07-25), CONDITIONAL on the owner accepting the gap window (owner item 2 there). If the owner instead demands a pre-merge port, this package's contract executes on the #524 branch before merge (and the HW verification restarts).
**Estimated effort:** S (device helpers exist; two insertion sites + one revived gate)
**Depends on:** pkg55-C7/PR #524. Reference implementation: pkg144/PR #515 (CPU + the deleted megakernels' `gpu_clampContrib`/`gpu_clampContribMW` wiring — recover the deleted call sites from git history at `9bb058fc`/#515 for the exact semantics).

**Origin:** pkg55-C7 deletion sweep (2026-07-25): the megakernels carried the only GPU wiring of pkg144's `clampDirect`/`clampIndirect` (#515, shipped 2026-07-23). Post-C7 the wavefront ignores both — a user setting clamps on a GPU render silently gets no clamping (defaults 0/0 = off, so default renders are unaffected). Recorded as a dropped feature in the C7 day-arc doc and the pkg55 spec.

---

## Contract

1. Port the clamp application into the wavefront with the SAME semantics as the #515 CPU/megakernel wiring (Cycles `film_clamp_light` lineage — cite as pkg144 did): **direct** clamp at the NEE/shadow-resolve contribution and emission-hit direct accumulation; **indirect** clamp at bounce≥2 path-contribution accumulation. Reuse the existing device helper (`gpu_clampContrib` family); do not re-derive.
2. CPU is the oracle: identical scene + clamps set, CPU vs wavefront clamped outputs agree within the standard per-channel mean-ratio band; clamps-off (0/0) renders BYTE-IDENTICAL to pre-pkg157 wavefront output (no-op guarantee).
3. **Revive the #515 GPU gate live** — `test_direct_and_indirect_clamp_controls` (or its successor) must run green against the wavefront on RTX; absence or xfail of the GPU leg is not acceptable evidence (memory `xfail-gated-features-must-unxfail`). Re-verify the #515 headline behaviors on the wavefront: bright-sun linearity stable, clampIndirect=10 suppresses fireflies at <0.02% brightness delta.
4. Update the pkg144 spec with a "wavefront wiring: pkg157" note on completion.

## Non-goals

- New clamp features/defaults (pkg144's contract is the contract).
- Perf (pkg155) or the naive residual (pkg156).
