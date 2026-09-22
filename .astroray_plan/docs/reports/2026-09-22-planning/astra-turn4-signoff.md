**REVISE.** The stage-plan amendments are present, but the package specs do not consistently implement them.

1. **Stage exits and dependency order**

   The [stage plan](/C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray/.astroray_plan/docs/stage-plan-2026-09-22.md:63) defines measurable exits for Stages 0–4: instrumented gate rows; reviewed specs and validated groundwork; quantitative science deliverables; detector statistics and response-corrected line recovery; and a frozen research matrix with passing tolerances. Stage 5 remains conditional and unscheduled, without a delivery exit.

   Two blockers prevent blanket confirmation:

   - **Stage 1a is not closed.** Its exit explicitly requires “Terra verdicts recorded per spec; no open ‘REVISE’.” The reviewed artifacts still end in REVISE; recording that defects were applied is not a closing review.
   - **Normalisation is correctly ordered in the plan, but incorrectly assigned in pkg243.** Stage 1c requires the length/emissivity contract in Phase 1, before quantitative Stage 2 outputs. Yet [pkg243](/C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray/.astroray_plan/packages/pkg243-raw-band-output-provenance.md:116) places it under “Phase 2”: “Scene-length unit: one Blender unit = one metre” and “Emissivity-to-radiance … \(I = \int j\,ds\).” Move those contracts **and their analytic acceptance checks** into Phase 1; retain pixel solid angle and detector conversion in Phase 2.

2. **Three spec spot-checks against Terra’s defect lists**

   - **[pkg278](/C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray/.astroray_plan/packages/pkg278-exit-gate-instrumentation.md:233): partially faithful.** Evidence: “Gate (b) GREEN requires a hash-locked, owner-ratified input manifest and linked evidence for every nonzero classification.” Backend proofs, viewport limits, paired renders and live triage were strengthened. However, Terra’s universal schema-enforced GREEN predicate and artifact existence/hash verification remain unspecified; acceptance still permits “a number or evidence path.” There is also a direct contradiction: line 82 says “SSIM stays a diagnostic print … gate (c),” while the plan and the spec’s gate-(c) section require SSIM ≥ 0.95. Resolve both before dispatch.

   - **[pkg280](/C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray/.astroray_plan/packages/pkg280-gr-transfer-reference-audit.md:112): partially faithful.** Evidence: “Each volumetric path … MUST pass the Phase 1 analytic tests … before it is labelled science-ready.” The Jacobian, bolometric scaling and matched-reference requirements landed consistently with Stage 1b. Terra’s first defect remains incomplete: the file table still routes ADAF/synchrotron work to registration stubs, and explicit fluid-frame-frequency and Doppler/redshift double-counting tests are absent.

   - **[pkg51](/C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray/.astroray_plan/packages/pkg51-telescope-postprocess.md:116): Terra’s principal fixes are present.** Evidence: “T(λ) and QE(λ) enter only inside the Phase 3 detector integral, over flux-normalized radiance microbins.” Wavelength-resolved PSFs, electron-domain noise, response-corrected line recovery and frozen α = 0.01 statistics now follow Stage 3. Its normalisation paragraph still assigns scene-length units to pkg243 Phase 2, contradicting Stage 1c; reconcile that wording.

3. **First next session:** Close these spec discrepancies through a recorded Terra re-review before dispatching pkg278 as the first implementation package.

**VERDICT: REVISE — The acceptance design is substantially improved, but the normalisation phase mismatch and incompletely applied Terra defects prevent final sign-off.**
