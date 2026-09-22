- Spec lines 96–108: It conflates total `ε_line` with per-steradian `j_line` and has no absolute-value oracle. Fix: define `j_line = n_e n_p α_eff hc/(4πλ)` explicitly and require a pinned absolute Hβ check, not ratios alone.

- Spec lines 153–159: `n_p/n_e`, ion fractions, and the ionising SED are not uniquely specified, so absolute emissivity cannot be reproduced. Fix: pin their values/models and parameters in metadata for every grid point.

- Spec lines 161–164: “log-linear” interpolation does not define interpolation of coordinates versus values, nor an off-grid accuracy check. Fix: give the exact interpolation formula and require independently calculated off-grid golden cases.

- Spec lines 141–142, 184–189, 204: Discrete integrated lines lack a renderer-facing spectral representation; point-sampled spectral evaluation can miss a line entirely. Fix: specify delta-line sampling or a normalized profile/bin convention with an energy-conservation test proving `∫jλdλ = j_line`.

NO — the contract identifies units and line centres, but it does not yet make absolute integrated emissivity reproducible through interpolation and spectral evaluation.

VERDICT: REVISE - Pin the absolute-normalisation inputs and define/test an energy-preserving discrete-line spectral injection contract.
