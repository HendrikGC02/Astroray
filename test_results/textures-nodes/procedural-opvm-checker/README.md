# Procedural chain into a BSDF socket
Procedural texture through Math / Mix / Color Ramp / Map Range into a BSDF socket: Cycles CPU | Astroray CPU | Astroray GPU.
Verdict: all three show the marbled sphere (not flat) after the op-VM fix; open observation: the generated-coordinate
Checker floor has slightly smaller / phase-shifted cells than Cycles on both Astroray backends.
repro_scene.blend is the Blender repro. Provenance: issue #818, Batch N (PR #821), 2026-09-20.
