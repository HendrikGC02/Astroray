# cornell-mini

**Vision:** Standard Cornell box at low resolution + low spp. Red wall left,
green wall right, white floor/ceiling/back, area light on top, no objects
inside. This is the harness sanity check — a smoke scene to ensure the
runner, metrics, and result writer all work end-to-end on every PR.

**What it is NOT:** This is not a Pillar-1/2/3/4/5 vision scene. It cannot
catch spectral, GR, or caustic regressions by design. Those scenes belong to
the owner-curated set decided in Phase 2 of pkg104.

**Reference status:** captured via `--bless` on a known-good commit.
Re-blessing should be a deliberate owner decision, not automatic.
