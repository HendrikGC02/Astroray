
## Research note — 2026-07-21 night session (implementation attempt, parked at session limit)

An Opus implementer round reached a decisive decomposition before the session
cut out (no code committed; findings preserved here):

- The grazing overshoot is **diffuse + specular summed without inter-layer
  energy conservation** (Disney 2012's known non-conservation), NOT a defect in
  either lobe alone. Measured at roughness=0.1, cos_theta_o=0.1 (the worst
  quarantined config): diffuse integrates to 0.73, specular to 0.48 — neither
  exceeds 1 alone; the naive sum is 1.20. `diffuseFurnaceScale` barely acts
  there (0.96).
- The physically-correct, Cycles-faithful fix direction: **diffuse-under-
  dielectric-specular coupling** — attenuate the diffuse lobe by the specular
  layer's Fresnel transmittance (cf. Cycles' principled dielectric layering /
  OpenPBR coupling). The next implementer should research the exact Cycles
  formulation and validate across the full 270-config grid with the
  importance-sampled rho() oracle (in-tree since pkg123 #498).
