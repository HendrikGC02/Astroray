# pkg170 — GPU opaque Disney creates ~2× energy: closure-graph re-eval overwrite on the diffuse+conductor recombination (+ the missing GPU opaque-Disney furnace coverage)

**Pillar:** 2/3 (BSDF energy conservation, GPU parity)
**Track:** A (RTX-gated — the defect is GPU-only; the new furnace legs are the lasting coverage)
**Status:** open — dispatchable (HIGH priority: every opaque Disney material on GPU is affected — metallic=0/transmission=0 is the default material class; wider blast radius than pkg169's transmission bug)
**Estimated effort:** S–M (diagnosis mostly done — the seam is convicted; the work is the estimator-correct fix + the coverage gap + verification)
**Depends on:** pkg169's fix PR (the one-sample-MIS-correct treatment this fix must mirror on the diffuse+conductor path, and the device-printf methodology to reuse). Related: memory `gpu-dielectric-lowers-to-closure-graph` (the closure-graph lowering is where this class of bug lives).

**Origin:** pkg169 diagnosis session (2026-08-02, RTX 5070 Ti, linear). While
convicting the transmission-lobe gains, the implementer found an INDEPENDENT
second latent energy bug: **GPU opaque Disney (metallic=0, transmission=0)
furnaces at ~1.975 — a flat ~2× energy gain across ALL roughness. CPU
conserves (0.959).** Independent of pkg169's changes and outside its
transmission scope fence, hence this spec.

---

## Convicted seam (diagnosis carried over — do not re-derive, verify then fix)

Localized by the pkg169 implementer to the **same closure-graph re-eval
overwrite pkg169 convicted on the transmission path, but on the
diffuse+conductor lobe recombination**: bypassing the overwrite reads 0.987
(conserving). The bypass is the DIAGNOSTIC, not the fix — skipping the
overwrite would change the estimator semantics for every closure-graph
material.

**The fix contract: apply the same one-sample-MIS-correct treatment pkg169
applied to the transmission path to the diffuse+conductor recombination.** Do
NOT ship the overwrite-skip. The flat-across-roughness ~2× signature is
consistent with a per-sample double-count in the lobe recombination (two lobes
each contributing full weight where one-sample MIS should weight the selected
lobe by its selection probability) — verify that reading against the actual
code before fixing; if the measured factor is not explained by the lobe-count
arithmetic, stop and extend the diagnosis (device-printf per-event
`(f, pdf, throughput)` dumps — reuse pkg169's methodology verbatim, it is the
proven instrument for this seam).

## Baseline (as reported from the pkg169 session; re-pin exact numbers on the fix branch's base SHA in the PR)

| config (linear, albedo=1, white env) | ratio |
|---|---|
| GPU opaque Disney, all roughness | **~1.975 (flat)** |
| CPU opaque Disney | 0.959 (conserves) |
| GPU with overwrite bypassed (diagnostic only) | 0.987 |

Flat-across-roughness + deterministic = structural weight error
(memory `mc-noise-vs-deterministic`), same class as pkg169.

## The coverage gap this package also owns

pkg166's converted GPU furnace legs did NOT cover opaque-Disney-on-GPU — a
~2× gain on the default material class survived yesterday's linear sweep
unseen. This package adds the missing legs, not just the fix:

- GPU opaque Disney white furnace at R ∈ {0.0, 0.3, 0.6, 1.0}, metallic=0,
  transmission=0, **linear, floor+ceiling** (pkg166 rules), under the pkg166
  naming guard.
- A metallic=1 GPU leg at two roughness values if not already covered (verify
  against pkg166's final converted set before adding — no duplicates).

## Acceptance

- [ ] GPU opaque Disney furnace within `[0.92, 1.03]` linear at all four
      roughness values; CPU cells unchanged (0.959-class — no regression).
- [ ] The fix is the estimator-correct recombination weight (one-sample MIS),
      cited against pkg169's transmission-path treatment and the standard
      one-sample-MIS reference (Veach thesis §9.2.4 / PBRT-v4 BSDF sampling) —
      CLAUDE.md §6 applies to the weight formula.
- [ ] The overwrite-bypass diagnostic is NOT in the shipped code path.
- [ ] New GPU furnace legs merged and guard-covered (they are the lasting
      deliverable — the bug class has now produced two members; the coverage
      is what prevents a third going unseen).
- [ ] Closure-graph neighbours spot-checked: plain dielectric and plain metal
      GPU furnace cells unchanged (the recombination fix must not leak into
      single-lobe paths).
- [ ] Render-level suite beyond the furnace per memory
      `pr-named-tests-insufficient` (reflection_not_black / material_properties
      class) green on GPU — a 2× fix on the default material WILL move real
      renders; verify appearance, not just integrals.

## Non-goals

- pkg169's transmission scope (its PR is held/landing separately; this package
  rebases on it).
- The CPU 0.959 reading (in-band; whether it should sit closer to 1.0 is
  pkg167/pkg129 compensation-family territory, not this weight bug).
- No band changes; no closure-graph architecture refactor — the minimal
  estimator-correct weight fix only.

## Provenance

Filed by the architect 2026-08-02 at team-lead request from the pkg169
diagnosis session's second finding. Second member of the closure-graph
re-eval-overwrite bug class (first: pkg169's GPU transmission pdf using
always-true `entering` instead of `rec.frontFace` — the pkg154 convention).
Discovery credit: pkg169 implementer's device-printf sweep; the opaque-Disney
furnace gap in pkg166's GPU legs is why it survived until today.
