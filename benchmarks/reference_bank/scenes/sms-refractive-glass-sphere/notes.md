# sms-refractive-glass-sphere

**Vision:** Clear non-dispersive glass sphere illuminated by an area emitter,
casting a sharp focused caustic on the floor below. Tests SMS Newton
path-finding for refractive caustics in the scalar-IOR mode (spectral_newton=0).

**Paired with** `prism-bk7-collimated` — that scene exercises the per-wavelength
Newton mode; this one isolates the scalar-IOR path. If both regress at once,
suspect upstream specular bounce or Newton root-finding; if only this scene
regresses, suspect the achromatic SMS branch specifically.

**Reference notes:** 384×256, 1024 spp CPU, ~30 s.
