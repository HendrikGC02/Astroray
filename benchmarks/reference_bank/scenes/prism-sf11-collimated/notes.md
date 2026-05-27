# prism-sf11-collimated

**Vision:** Same setup as `prism-bk7-collimated` but with SF11 flint glass
(Abbe ~25 vs BK7's ~64). Direct A/B contrast against the BK7 scene catches
a class of bug where the sellmeier preset dispatcher silently shares the
BK7 coefficients across all `dielectric` materials.

**Why two prism scenes:** if BK7 regresses and SF11 doesn't (or vice versa),
that narrows the defect domain quickly. If both regress identically,
the upstream spectral pipeline broke; if only one, the preset table or
material-param plumbing broke.

**Reference notes:** see `../prism-bk7-collimated/notes.md` for the
sphere-vs-prism geometry rationale and integrator wiring. Same params
applied here; only the `sellmeier_preset` differs.
