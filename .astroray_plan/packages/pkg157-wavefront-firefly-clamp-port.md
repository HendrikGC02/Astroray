# pkg157 — Port pkg144 clampDirect/clampIndirect into the wavefront (restore the GPU firefly-clamp feature C7 dropped)

**Pillar:** 3 (GPU feature parity)
**Track:** A (RTX-gated)
**Codex-paste-ready:** no (small but placement-sensitive: clamp semantics must land at the exact accumulation sites or they bias energy)
**Status:** **DONE** — merged as `b6c3ffb` (PR #526, 2026-07-26). RTX 5070 Ti verification: cross-binary clamps-off no-op measured at **2.48e-07 relative to peak** (image sums identical to 6dp), ~40x inside the 1e-5 wavefront MC convention; bounce classification proven directly — `clampIndirect` is EXACTLY inert (0.000000) at `max_depth=1` where no indirect bounces exist and bites (0.294769) at `max_depth=8`, with `clampDirect` depth-invariant at 1.511, which validates the parked-bounce lane for the deferred shadow-resolve. Gate run 8 passed / 1 documented skip at merge; the skip was the firefly-suppression clause, since **un-skipped and GREEN by pkg161** (`1393b13`) — full run now **12 passed**. Contract items 2 and 3 were formally amended on measured evidence (see Contract).
**Estimated effort:** S (device helpers exist; two insertion sites + one revived gate)
**Depends on:** pkg55-C7/PR #524. Reference implementation: pkg144/PR #515 (CPU + the deleted megakernels' `gpu_clampContrib`/`gpu_clampContribMW` wiring — recover the deleted call sites from git history at `9bb058fc`/#515 for the exact semantics).

**Origin:** pkg55-C7 deletion sweep (2026-07-25): the megakernels carried the only GPU wiring of pkg144's `clampDirect`/`clampIndirect` (#515, shipped 2026-07-23). Post-C7 the wavefront ignores both — a user setting clamps on a GPU render silently gets no clamping (defaults 0/0 = off, so default renders are unaffected). Recorded as a dropped feature in the C7 day-arc doc and the pkg55 spec.

---

## Contract

1. Port the clamp application into the wavefront with the SAME semantics as the #515 CPU/megakernel wiring (Cycles `film_clamp_light` lineage — cite as pkg144 did): **direct** clamp at the NEE/shadow-resolve contribution and emission-hit direct accumulation; **indirect** clamp at bounce≥2 path-contribution accumulation. Reuse the existing device helper (`gpu_clampContrib` family); do not re-derive.
2. CPU is the oracle: identical scene + clamps set, CPU vs wavefront clamped outputs agree within the standard per-channel mean-ratio band; clamps-off (0/0) agrees with the pre-pkg157 wavefront output **within the 1e-5 wavefront MC convention** (no-op guarantee). **AMENDED 2026-07-26** (was "BYTE-IDENTICAL"): byte-identity is unsatisfiable by construction on this path -- the wavefront is not bit-identical to *itself* (same seed, same config: 29/27648 elements differ at 1.19e-07, atomic accumulation ordering). VERIFIED at 2.48e-07 relative to peak, cross-binary, ~40x inside the convention.
3. **Revive the #515 GPU gate live** — `test_direct_and_indirect_clamp_controls` (or its successor) must run green against the wavefront on RTX; absence or xfail of the GPU leg is not acceptable evidence (memory `xfail-gated-features-must-unxfail`). Re-verify bright-sun linearity stable. **AMENDED 2026-07-26:** the "clampIndirect=10 suppresses fireflies at <0.02% brightness delta" clause is **DEFERRED to pkg161**, not satisfiable here -- measured tail-heaviness (peak/p99.9) across the whole scene library is 1.04-1.82x at both 16 and 64 spp, i.e. **no gate scene has a firefly population to suppress**. No threshold satisfies both halves: high enough to clip only outliers clips nothing; low enough to bite removes real signal. pkg161 owns building a firefly-bearing scene (validated at peak/p99.9 >= 10x by measurement, not by eye) and un-skipping this gate.
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
NOT DEMONSTRABLE ON ANY EXISTING SCENE.** Initially read as a scene-scaling
problem (a limit of 10 never binds on a Cornell-scale scene, peak ~1.76, so
`max|Δ| = 0.00000` and the criterion is met by the clamp doing nothing — it
would pass with the port entirely unwired). Three hardware rounds of
recalibration proved the cause is deeper: **the scene library contains no
firefly population at all.** Measured tail-heaviness (`peak / p99.9`) at
16/64 spp — diffuse_light_cornell 1.82×/1.53×, thin_glass_cornell 1.66×/1.52×,
disney_cornell 1.66×/1.52×, dielectric_cornell 1.40×/1.13×, metal_cornell
1.07×/1.04×; a genuine firefly tail is tens to hundreds. With a tail that flat
the two halves of the claim are mutually exclusive: a limit high enough to clip
only outliers clips nothing (p99.9 is 99.5% of peak; `max|Δ| = 4.77e-07`), one
low enough to bite removes real signal (0.5× peak → mean moved 4.166%).
**Resolution:** pkg157's gate is `pytest.mark.skip`-ped citing this measurement
(deliberately not xfail — the code is not expected to fail, and an xfail is
never acceptable evidence for a gated feature). Building a firefly-bearing
scene is filed as **pkg161**, which owns un-skipping that gate and restating
item 3 in scene-relative terms. **Item 3 cannot be satisfied by pkg157 and
should not block it** — the clamp's correctness rests on the max_depth=1
bounce-classification result, the clamp sweep, and the cross-binary no-op gate,
all green on hardware.

## Non-goals

- New clamp features/defaults (pkg144's contract is the contract).
- Perf (pkg155) or the naive residual (pkg156).
