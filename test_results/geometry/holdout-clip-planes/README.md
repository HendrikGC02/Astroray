# Holdout and camera clip planes
Sphere over a striped backdrop: normal | holdout | camera clip planes (CPU path).
Verdict: per the pkg274 spec, clip planes use view-axis depths (Cycles z_inv) and holdout cuts the object out.
Provenance: pkg274 (addon gaps), PR #830, 2026-09-19.
