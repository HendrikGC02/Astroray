# Viewport material edits, worker ON vs OFF
Nine edits on a Principled sphere (base colour, roughness, node link, image swap, emission): worker_on_sheet and
worker_off_sheet (downscaled viewport screenshots); centre_rgb_chart plots the centre pixel per step.
Verdict: PASS. ON and OFF match within ~1% on every edit, so the incremental-replay fix (#721) adds no staleness.
Emission 0 -> 5 does not visibly light the sphere in either mode (pre-existing GPU emission gap, fixed later in #835).
Provenance: issue #721, PR #831, RTX 5070 Ti, Blender 5.2, 2026-09-19.
