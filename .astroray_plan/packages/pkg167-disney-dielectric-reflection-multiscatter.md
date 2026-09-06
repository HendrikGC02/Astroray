# pkg167 — Disney dielectric reflection-lobe multi-scatter energy compensation + the pkg150 dead-sample fix it unblocks (bundled, in that order)

**Pillar:** 2 (materials / BSDF energy correctness)
**Track:** A (CPU furnace gates on CI; GPU twin RTX-verified)
**Status:** superseded — Part 1 landed (PR #562); Part 2 (pkg150 dead-sample redistribution) is owned by pkg179 (2026-09-07 backlog triage)
**Estimated effort:** M (the compensation term follows an in-repo shipped pattern; the work is the dielectric-specific `E(μ, roughness, η)` dependence, the GPU mirror, and holding the furnace at all roughnesses with the dead-sample fix re-applied)
**Depends on:** nothing open. The pkg151→pkg154→pkg149 sampler chain is on main (#519/#521/#522), and pkg150's charter is met by it. **Composes with:** pkg60 (CPU Kulla-Conty GGX reflection compensation for the metal lobe, DONE), pkg118 (rough-dielectric *transmission* multiscatter, DONE), pkg160/pkg163 (plain-metal compensation, DONE — the in-repo pattern to mirror), pkg129 (open — *metal*-lobe Turquin LUT unification; see Relationship note). pkg166 (linear furnace conversion) is not a blocker but its rules apply to every gate here.

**Origin:** pkg150 STOP (implementer, 2026-08-02, measured on main `d02fe07`,
worktree pkg150). The pbrt-v4-faithful dead-sample fix — below-horizon VNDF
reflection candidates return `pdf = 0` instead of falling back to a
smooth-mirror delta — **cannot ship alone**. The legacy delta fallback is
energy-load-bearing: it has been ad-hoc compensating for genuinely missing
reflection-lobe multi-scatter energy in the Disney dielectric.

---

## The measured coupling (why this package exists and why it is bundled)

With the delta fallback removed and nothing added (main `d02fe07`, RTX 5070 Ti
+ CPU, linear):

- **White furnace regresses at high roughness:** CPU r=1.0 reads **0.997 →
  0.788** (gate `[0.92, 1.03]`); GPU **1.000 → 0.918**.
- **Dead-sample fraction scales with roughness:** 0.08% at r=0.3 → **7.1% at
  r=1.0**, and the loss **compounds over depth-32** paths — which is why a
  per-event few-percent loss becomes a 21% furnace deficit.
- The reverted dead-sample diff is **preserved in the pkg150 spec** (team-lead
  instruction to the implementer) — re-apply it here, do not re-derive it.

Interpretation (carry into the PR description): the delta fallback was never a
sampling correctness feature; it was an unintentional energy patch. Removing it
exposes the true single-scatter energy deficit of the dielectric reflection
lobe at high roughness. The correct resolution is the same one this repo has
now shipped twice (pkg60 metal-lobe CPU, pkg160/pkg163 plain metal): explicit
multiplicative multi-scatter compensation, then remove the hack.

## Part 1 — reflection-lobe multi-scatter compensation for the Disney dielectric

**Cite — no inventions (CLAUDE.md §6; invoke `cite-algorithm` before coding):**

- Kulla & Conty 2017, "Revisiting Physically Based Shading at Imageworks"
  (the `E(μ)`-based compensation family).
- Turquin 2019, "Practical multiple scattering compensation for microfacet
  models" — the dielectric-reflection treatment, including the **η dependence**
  of the albedo tables (dielectric `E` depends on IOR, unlike the metal case).
- **In-repo pattern (mirror it, don't invent a third heritage):**
  `ggxCompensationFactor` + the shipped Cycles tables in
  `include/astroray/energy_compensation.h` (pkg60), its GPU twin in
  `include/astroray/gpu_materials.h` (pkg160, #527), and the per-λ spectral
  handling from pkg163 (#533) if the term is chromatic. Cycles'
  `intern/cycles/scene/shader.tables` (Apache-2.0, PR #107958) is the
  production cross-check and already the heritage of the in-repo tables.
- Note what already exists on the dielectric: `ggxGlassCompensationFactor`
  (`disney.cpp`, scalar from `fresnelDielectricFss(etap)`) covers the
  glass/transmission side (pkg118 era). This package adds/extends the
  **reflection-lobe** term; record explicitly how the new term composes with
  (or subsumes) that scalar so the two never double-compensate.

**CPU/GPU mirrored** in the same package — the term lands in `disney.cpp`
eval/sampleSpectral and its exact GPU twin in the closure-graph path
(`gpu_materials.h` / wavefront shade), the same way pkg160 did it. A CPU-only
land repeats the pkg60→pkg160 four-week divergence; do not split.

## Part 2 — re-apply the dead-sample fix (same package, AFTER Part 1 is green)

Re-apply the preserved pkg150 diff: below-horizon VNDF reflection candidates
return `pdf = 0` (pbrt-v4 `DielectricBxDF` semantics), delta fallback deleted.
Ordering is load-bearing: Part 1 must hold the furnace on its own build before
Part 2 lands on top, so a bisect can separate the two effects. Ship both in one
PR (the furnace must never regress on main between them), but commit them as
two reviewable steps with the intermediate furnace numbers recorded.

## Acceptance criteria

- [ ] White furnace holds at **ALL of r ∈ {0.3, 0.6, 1.0}, CPU AND GPU, in
      LINEAR with floor+ceiling** (pkg166's rules: `apply_gamma=False`
      explicit, upper bound asserted — a gamma furnace structurally cannot see
      the failure mode Part 1 could introduce). Target band `[0.92, 1.03]` as
      today unless the architect signs off otherwise.
- [ ] The dead-sample fix is re-applied verbatim-or-justified from the pkg150
      preserved diff; dead-sample fraction re-measured and recorded at
      r ∈ {0.3, 0.6, 1.0} post-land.
- [ ] CPU and GPU compensation are the same construction (spectral handling
      per pkg163's class rule); a plain GPU/CPU parity check on a rough
      dielectric sphere stays in the standard band.
- [ ] **chi² caveat encoded:** pkg150's chi² runs carry a quadrature artifact
      at `ires=4` — do NOT pin any gate on a raw `ires=4` number; re-run at
      the higher-resolution quadrature before citing or gating any chi²
      result here. Compensation multiplies throughput, not the sampling pdf,
      so chi² must not regress — but only the artifact-free reading counts.
- [ ] Research note `.astroray_plan/docs/pkg167-dielectric-reflection-multiscatter-research.md`
      with the citations above, the η-dependence decision (table vs analytic
      fit), and the composition rule vs `ggxGlassCompensationFactor`.

## Inherited quarantine — pkg169's CPU ior1.5/R=1.0 transmission-furnace cell (architect disposition, 2026-08-02)

pkg169's single-scatter fixes leave ONE converged out-of-band cell: CPU Disney
transmission furnace, ior 1.5, R=1.0 reads **0.903** vs floor 0.92 (256/1024
spp agree; single-scatter alone 0.717, the pkg151 comp factor recovers to
0.903; the GPU twin passes at 0.930 via the one-sample-MIS estimator). The
residual is near-TIR internal-reflection energy at maximum roughness — the
reflection-lobe multiscatter deficit at its worst-case corner, i.e. exactly
this package's family. Architect verdict (pkg169 fork): the cell is
quarantined `xfail(strict=False)` with a reason string citing THIS package —
kept in the grid so it stays measured every run, no band widening, no comp
tinkering inside pkg169.

**Binding acceptance addition:** this package's fix must RETIRE that xfail —
the cell returns to the standard `[0.92, 1.03]` linear band and the marker is
removed in this package's PR, proven under `--runxfail` (memory
`xfail-gated-features-must-unxfail`). If the compensation term lands and the
cell still fails, that is an escalation to the architect with the residual
decomposition — not a re-quarantine.

## Relationship note — pkg129 (do not merge the scopes)

pkg129 owns the **metal** reflection-lobe LUT unification (Turquin tables via
`adobe/openpbr-bsdf`) and is partially stale: its "GPU placeholder returns 0"
premise predates pkg160/pkg163, and `stage_shade_metal.cu` is now dead code.
This package is the **dielectric** reflection lobe only. If the implementer
finds the cleanest dielectric term is the same Turquin table family pkg129
plans to port, record that in the research note so pkg129 can consume one
table loader — but do not expand into metal here, and do not block on pkg129.

## Non-goals

- Not the metal lobes (pkg60/pkg160/pkg163 shipped; pkg129 owns unification).
- Not transmission multiscatter (pkg118 shipped; `ggxGlassCompensationFactor`
  stays unless the composition rule requires a documented adjustment).
- Not reopening pkg150 (closing as resolved-by-pkg149) or pkg149/pkg151/pkg154.
- No gate-band changes without architect sign-off.
- No LUT regeneration from scratch — borrow license-clean tables (CLAUDE.md §6).

## Provenance

Filed by the architect 2026-08-02 at team-lead request, from pkg150's STOP:
the dead-sample fix's furnace regression (CPU r=1.0 0.997→0.788) proved the
smooth-mirror delta fallback was masking a missing dielectric reflection-lobe
multi-scatter term. Reverted diff preserved in the pkg150 spec. Third member of
the compensation family: pkg60 (metal CPU) → pkg118 (transmission) →
pkg160/pkg163 (plain metal CPU+GPU) → **pkg167 (dielectric reflection)**.

## Progress

- 2026-09-07 backlog triage: status flipped to `superseded`. Previous status text: Part 1 done (PR #562, 2026-08-08 — reflection-lobe glass multiscatter compensation CPU+GPU; CPU furnace r=0.3/0.6/1.0 = 0.9855/0.9368/0.9260, all in [0.92,1.03]; pkg169 xfail retired; GPU verify deferred to lead). **Part 2 (pkg150 dead-sample fix) DEFERRED — premise falsified by measurement: the delta fallback carried ~0.44 furnace energy at r=1.0 (below-horizon reflection rate 22.9%, ~3x pkg150's documented 7.1%), which the reflection-lobe compensation recovers by only +0.009; removing the fallback collapses the furnace to 0.485. ESCALATED to architect/lead — Astroray's split-lobe architecture cannot replicate Cycles' combined-closure energy redistribution via a reflection-lobe multiply. See PR #562 body for the full decomposition.**
