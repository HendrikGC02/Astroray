# Continuous material-edit commit cost (worker ON)
Continuous Base Color edit storm on the metal_sweep and big scenes; shaded band = the 33 ms tick-gap budget.
Before: ~100% of commit cost was a full sync_viewport_scene (112-120 ms x 46-50 per storm) because every edit
classified as fallback. After: edits dispatch as MATERIALS (replay True 97 / 85), full syncs drop to 2.
Verdict: commit p95 218.6 -> 73.0 ms (metal), 117.9 -> 23.4 ms (big); tick-gap p95 still above 33 ms (80 ms):
the residual is render/present, out of scope for #721.
Provenance: issue #721, PR #831, RTX 5070 Ti, Blender 5.2, 2026-09-19.
