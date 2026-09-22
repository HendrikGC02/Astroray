Defects:

- pkg50:26–33, 173–174 — `Q` algebraically restates the point-mass implementation formula and can be falsely green if read from the deflection field. Fix: require `α` to be recovered from rendered source-grid displacements or independent geodesic endpoints, never from pass internals.
- pkg50:35–40, 134–140 — “analytic lens equation” and Einstein-radius checks reuse the selected point-mass model, so they are not independent validators. Fix: make geodesic-propagated background-grid positions and finite-difference Jacobians the required oracle outputs.
- pkg50:139–140, 180–182 — the geodesic comparison lacks a frozen equivalence protocol (observer/lens/source distances, coordinate mapping, asymptotic-`b` extraction, sampling, and measurement method). Fix: specify these inputs and compare independently measured exit directions/image positions across the declared overlap range.
- pkg50:151–160, 177–179 — uniform-background conservation tests remapping integrity, not lens-model correctness; it is not tied to the geodesic oracle required by the stage plan. Fix: retain it as an invariant, but add geodesic-reference magnification/Jacobian and parity acceptance criteria.

YES — the required comparison with independently propagated Schwarzschild geodesics can validate the point-mass lens model, but its observable-extraction protocol must be made non-circular and testable.

VERDICT: REVISE - Preserve the geodesic oracle, but bind rendered positions and Jacobians to it with a frozen independent measurement protocol.
