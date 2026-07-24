# pkg154 — Rough-transmission furnace deficit under the corrected VNDF sampler: root-cause investigation (the pkg151 multiscatter hypothesis is FALSIFIED)

**Pillar:** 3 (BSDF correctness / energy conservation)
**Track:** A
**Codex-paste-ready:** no (investigation-first, pkg146-style contract: measurement ledger before any fix; the fix ships only if convicted and localized)
**Status:** ✅ DONE (investigation + fix found, 2026-07-25 — docs PR, no code merged to main this round). **Two convicted, unambiguous bugs**, both fixed and measured: (H1) `roughTransmissionEval`/`roughTransmissionPdf` derived enter/exit from `cosO>0` on the front-facing (ray-oriented) `rec.normal`, which is provably always `>=0` regardless of true enter/exit — measured 274,809/274,809 (100%) calls read `entering=true`, including the 61% that were genuine exit events; same bug class as the already-fixed `dielectric.cpp` frontFace bug, never ported here. (H4, new — not one of the spec's ranked H1-H3) a closure-level `clamp(0,4)` on the transmission eval, inconsistent with the file's own no-cap doctrine already documented for metal reflection (pkg123), truncated the low-roughness estimator's legitimate heavy tail. Together: furnace 0.11–0.82 -> **0.997–0.999** across roughness {0.05,0.1,0.3,0.6,1.0} on the pkg149+pkg151 stack, well inside [0.92,1.03]; peak alignment stays green; chi² unchanged (pkg149's own gate, as expected). **Both fixes are measured no-ops on main's current sampler** (bit-identical furnace numbers with/without) — ships as a patch file (`.astroray_plan/docs/pkg154-frontface-and-clamp-fix.patch`), not a direct main PR, to avoid a disney.cpp merge conflict with the still-unmerged pkg151/PR #519 (same function). pkg149 should apply this patch alongside its own rebase once #519 merges. Full findings: `.astroray_plan/docs/pkg154-furnace-deficit-findings.md`.
**Estimated effort:** M (ledger + term-by-term comparison; the fix itself is likely small once convicted)
**Depends on:** pkg151/PR #519 (glass LUT infrastructure — merged state is the measurement baseline, conditional on its adjudication checklist) + the pkg149 corrected sampler `670e583` (worktree `Astroray-pkg149`, unpushed) cherry-picked for all measurements. Coordinate: `disney.cpp` single-writer discipline continues — this package inherits Lane A's slot.

**Origin:** pkg151/PR #519 implementation (2026-07-25). The implementer probed the extracted Cycles glass tables BEFORE wiring them (`.astroray_plan/docs/pkg151-glass-multiscatter-magnitude-notes.md`): the Cycles `microfacet_ggx_preserve_energy` glass compensation tops out at **~1.03×** at ior=1.5 across the whole gate grid, versus the **1.2×–11×** needed to close the measured furnace deficit. With pkg151 + `670e583` stacked, the furnace is statistically unchanged (0.11–0.82). The pkg149→pkg151 premise — "the corrected sampler exposed missing multi-scatter energy" — is **falsified**: the deficit's dominant cause is something else, and a ~90% energy loss at low roughness is structural, not a few-percent tail.

---

## Measured state (corrected sampler + pkg151 compensation, ior=1.5)

| roughness | furnace (gate band [0.92, 1.03]) |
|---|---|
| 0.1 | 0.217 |
| 0.3 | 0.357 |
| 0.6 | 0.596 |
| 1.0 | 0.817 |

Deficit is WORST at LOW roughness and shrinks as roughness grows — the OPPOSITE roughness profile of missing microfacet multi-scatter (which grows with roughness). Whatever is eating energy acts per-transmission-event, and the furnace recovers as more energy exits via the reflection lobe instead.

## Hypotheses (ranked; convict by measurement, not argument)

**H1 (leading) — the eta² radiance-compression factor does not cancel across enter/exit.** Arithmetic consistency: at ior=1.5, one uncancelled 1/ior² = 0.444; applied at BOTH enter and exit (exit computed with the wrong eta orientation instead of the reciprocal), (1/ior²)² = **0.198 ≈ the measured 0.217 floor at roughness 0.1**, rising toward 1.0 exactly as the reflection fraction grows with roughness. A white furnace must conserve: the per-event radiance-compression factors must cancel over any closed enter/exit path. Re-examine the pkg149 research claim that the single-scatter estimator median "matches `G1(wi)/ior²` theory" — **state WHICH theory value the furnace expects**; if the per-event throughput legitimately carries 1/ior², the exit event must carry ior², and a median at `G1/ior²` for closed paths is itself the anomaly. This is a known in-repo bug class with three precedents: memory `refraction-frontface-bug` ("glass too dark: eta² didn't cancel" — dielectric used normal-sign not `rec.frontFace`), memory `photon-caustic-exit-refraction-oriented-normal` (exit eta from the ray-oriented normal instead of the geometric outward normal), and pkg118/PR #423 + PR #404 (exit eta²=2.25 clipped by albedo clamps on CPU and GPU respectively). The pkg149 azimuth fix changed which half-vectors are sampled — it can easily have changed which eta-orientation branch the exit events take.

**H2 — sample()/pdf() Jacobian or branch mismatch introduced/exposed by the corrected construction** (Walter eq. 17/38 denominator, `dwm/dwi` convention) — would show as f/pdf bias per event rather than a clean 1/ior² factor; the ledger separates it from H1 by magnitude signature.

**H3 — Fresnel double-counting on the transmission branch** ((1−F) applied in both the lobe-selection weight and the throughput) — predicts a roughly Fresnel-sized (~4–9% at normal incidence), not 4.6×, deficit; likely a contributor at most.

## Investigation contract (pkg146 discipline — no blind fixes)

1. **Per-bounce energy ledger** at the worst config (roughness 0.1, ior 1.5, furnace scene): for each path, log event type (reflect/transmit enter/transmit exit/TIR), the eta used, the applied throughput factor decomposed into (Fresnel, D/G/Jacobian, eta² term, compensation), on the `670e583`+pkg151 stack. The ledger must show WHERE the 0.217 arises — a single table that sums to the measured furnace value.
2. **Term-by-term comparison against pbrt-v4 `DielectricBxDF::Sample_f`/`PDF` transmission branches** (Apache-2.0, `src/pbrt/bxdfs.cpp`) INCLUDING the radiance-mode `ft /= Sqr(etap)` convention and its cancellation over closed paths; and against the CPU plain-`dielectric.cpp` path (which passes its furnace — diff WHERE Disney's transmission throughput differs from the passing implementation).
3. Fix only the convicted term(s), citing the reference (CLAUDE.md §6); one derivation shared by sample()/pdf()/eval().
4. Re-run: rough-glass furnace [0.92, 1.03] across R ∈ {0.05, 0.1, 0.3, 0.6, 1.0} on the stack; pkg149 peak-alignment stays <2°; white-furnace + smooth-glass + caustic/prism refbank unchanged with mandatory visual check (memory `general-photon-loop-needs-solid-glass`); CPU==GPU parity per-channel mean-ratio.

## Non-goals

- Re-opening the pkg149 azimuth fix itself (peak alignment is measured-correct; it stays).
- The Cycles glass-LUT compensation (pkg151 ships it faithfully; its ~1.03× is correct-as-designed, just not the dominant cause).
- pkg150's reflection-candidate masking (own package, re-baseline after this lands).
- Un-xfailing chi² glass[0.3-45] — ownership stays with pkg149; it flips only when peak-alignment AND furnace are green together on the final stack.

## Provenance

Filed by the architect from the PR #519 adjudication (2026-07-25). Falsification evidence: `.astroray_plan/docs/pkg151-glass-multiscatter-magnitude-notes.md` (implementer's pre-registered magnitude probe — flagged before measuring, exemplary). Supersession chain: pkg118 Part B ("multi-scatter rejected") was confounded by the azimuth-swapped sampler; pkg151 then showed multi-scatter is real but ~1.03×; the deficit's true owner is this package.
