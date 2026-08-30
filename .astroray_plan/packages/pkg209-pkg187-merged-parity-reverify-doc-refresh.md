# pkg209 — pkg187 Cauchy parity re-verify vs merged Cycles + WIP-doc/citation refresh

**Pillar:** 5
**Track:** A (verification + doc/comment refresh; no algorithm change expected).
**Estimated effort:** S.
**Status:** done (PR #664, 2026-08-31 — refreshed the dispersion WIP wording to the
merged Cycles commit `f15daf81bf7c...` (PR #162041 squash-merged 2026-08-18) and
re-verified `cauchyAB`/`gpu_cauchy_ior` character-for-character against the merged
diff, no divergence; also fixed the MNEE citation ("Manakov"→"Fascione") across
`half_vector_constraint.h`, `sms_attempt_device.cuh`, `sms_caustic_path_tracer.cpp`.
Comment/doc-only, no algorithm change).
**Depends on:** nothing (pkg187 shipped; the reference merged 2026-08-18).

## Goal

pkg187's Cauchy dispersion port and its docs/comments pin Cycles PR #162041 as an
**unmerged WIP**. It merged 2026-08-18 (squash commit `f15daf81bf7c…`). Two
things follow: (a) the parity target is now the merged code, which should be
re-verified against Astroray's port bit-for-bit (the report fetched
`bsdf_glass_ior` from the merged `bsdf_microfacet.h` and it matches, but that
match should be an owned, checked-in verification, not a report claim); and (b)
the "WIP"/"unmerged" wording across the repo is stale and must be refreshed.

## Specification

1. **Re-verify the Cauchy fit against the merged commit** (`f15daf81bf7c…`,
   `intern/cycles/kernel/closure/bsdf_microfacet.h` `bsdf_glass_ior`). Confirm,
   with the merged source quoted in the PR (under Apache-2.0, for research):
   - Fraunhofer constants (`lambda_d=0.5876`, `lambda_C=0.6563`, `lambda_F=0.4861` µm),
   - `B = (ior-1)*inv_abbe*fac`, `A = ior - B/lambda_d²`, `n(λ)=A+B/λ²` (OpenPBR
     Eq. 55/56),
   - the `Vd = abbe / dispersion_scale` (i.e. `inv_abbe = dispersion_scale/abbe`)
     mapping,
   against Astroray's `plugins/materials/principled.cpp:229-238` (`cauchyAB`) and
   `include/astroray/gpu_dispersion.cuh:36-39` (`gpu_cauchy_ior`). If they match,
   record the diff-check in the PR and in the pkg187 research note. **If any
   constant or the mapping diverges from the merged code, STOP** and file the
   correction as its own spec (do not silently patch a physics constant here) —
   report the divergence to the architect.

2. **Refresh stale "WIP/unmerged" wording** across the repo (surgical, comments
   and docs only — CLAUDE.md §3):
   - `plugins/materials/principled.cpp:78,221` ("Blender's WIP …", "VERBATIM port
     of Cycles' WIP Principled dispersion"),
   - `include/astroray/gpu_dispersion.cuh:30` ("Cycles' WIP Principled dispersion"),
   - `.astroray_plan/docs/pkg187-principled-dispersion-research.md` (the "unmerged
     WIP" framing),
   - any other hit from `grep -rn "WIP" ...dispersion` context.
   Update each to state the merged commit `f15daf81bf7c…` and merge date
   2026-08-18; keep the citation, drop the "unmerged" claim.

3. **Fix the MNEE citation typo (§6.7 repo hygiene, folded in here).**
   `include/astroray/manifold/half_vector_constraint.h:11` and `:74` list the MNEE
   2015 authors as "Hanika, Droske, **Manakov**" — the published paper is
   "Hanika, Droske, **Fascione**", *Manifold Next Event Estimation*, CGF 34(4),
   DOI 10.1111/cgf.12681. Correct both occurrences (and any other "Manakov" hit;
   `sms_attempt.h` already has it right). Comment-only change.

## Acceptance

- [ ] The parity re-verification is recorded (the merged constants/mapping vs
  Astroray's `cauchyAB`/`gpu_cauchy_ior`, shown side-by-side in the PR); a
  same-scene dispersion render is bit-identical / within MC noise of the pre-change
  baseline (this package changes NO executable code if the constants already
  match — assert byte-identical render output, `.pyd` mtime stated).
- [ ] All "WIP/unmerged" dispersion wording is refreshed to the merged commit;
  `grep -rn "WIP"` over the dispersion files returns no stale unmerged claims.
- [ ] The MNEE "Manakov" → "Fascione" citation is corrected at
  `half_vector_constraint.h:11` and `:74`.
- [ ] Diff is comments/docs only (unless the re-verify uncovers a real constant
  divergence, which is out of scope and gets its own spec). CI green on all matrix
  jobs.

## Non-goals

- **No algorithm change** — if the merged code differs from Astroray's port, that
  correction is a separate spec, not this one.
- **No re-derivation of the physics** — pkg187 already owns the model; this is a
  target-refresh + citation-hygiene pass.

## Provenance

Filed by the architect 2026-08-19 from the dispersion research report
(`...2026-08-19-cycles-dispersion-research.html` §6.2 "Actionable discrepancy #2"
+ §6.7 citation typo, ranked recommendation #2). Grounded in live code:
`principled.cpp:78,221,229-238`, `gpu_dispersion.cuh:30,36-39`,
`half_vector_constraint.h:11,74`. Open-model tier for the doc/citation refresh;
Claude owns the merged-commit constant-parity verification (the last-line-of-
defense physics check).
