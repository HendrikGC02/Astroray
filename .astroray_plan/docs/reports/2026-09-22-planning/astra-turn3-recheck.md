1. **Turn-2 points still incompletely addressed** (against the amendments listed in your prompt):



   - **Stage 4 still lacks a passing condition.** Quote: “**Exit:** a reproducible figure bundle … whose every panel carries its reference value and residual.” This permits arbitrarily wrong panels to pass by documenting their errors. Require each validation panel to satisfy a predeclared observable-specific tolerance. Also, “≥ 3 spins × ≥ 2 inclinations” defines a minimum, not a bounded matrix: freeze the actual cases before dispatch.



   - **Stage 3 line recovery remains underspecified.** Quote: “the Hα/Hβ recovery holds as a mean with CI.” State the recovered quantity—response-corrected integrated **energy** radiance ratio—and require its specified confidence interval to lie wholly inside the target tolerance. Explicitly carry forward Stage 2’s 95% CI and ±2% criterion, or declare and justify a different instrument error budget.



2. **New defects introduced by the revision:**



   - **The new statistical threshold has no calibrated acceptance probability.** Quote: “over ≥ 20 realisations … the electron histogram matches … (χ²/dof in [0.8, 1.25]).” Twenty realisations alone establish neither histogram sample size nor degrees of freedom. The result depends on binning, expected occupancy and fitted parameters; a fixed reduced-χ² interval can reject a correct simulator at an uncontrolled rate. Freeze those choices and use a declared significance level with the corresponding χ² bounds, or a calibrated simulation-based test. [NIST’s goodness-of-fit definition](https://itl.nist.gov/div898/handbook/eda/section3/eda35f.htm) specifies these dependencies. Also separate renderer Monte Carlo uncertainty from detector noise so the histogram tests the declared detector model.



   - **The physical normalisation prerequisite is scheduled after its first use.** Quotes: Stage 2 requires “measured quantity = integrated energy radiance per line” and “independent single-line normalisation check I_line = j_line·L”; Stage 3 first “fixes scene-length units … and physical radiance normalisation.” Stage 1c supplies only raw relative output. Either move the minimal length/emissivity-to-radiance contract before Stage 2’s absolute single-line check, leaving pixel solid angle and detector conversion in Stage 3, or explicitly define Stage 2’s check in independently mapped reference units without claiming calibrated physical radiance.



3. **VERDICT: REVISE — The main amendments are sound, but the remaining acceptance conditions and the normalisation dependency must be made consistent before the plan is executable.**

