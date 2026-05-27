"""Cornell box at 256x144, 16 spp.

This is the HARNESS sanity-check scene — small enough to run on every PR.
It is NOT one of the owner-curated vision scenes; those land in Phase 2
of pkg104 after the scene-selection gate (§Open question to owner).
"""

from __future__ import annotations


NAME = "cornell-mini"
WIDTH = 256
HEIGHT = 144
SAMPLES = 16
MAX_DEPTH = 6
SEED = 17


def make_scene(astroray):
    """Build a Cornell-ish scene using the test helpers."""
    # Local import so unit tests can import this module without astroray
    # being on sys.path at import time.
    import sys
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[4]
    sys.path.insert(0, str(repo_root / "tests"))

    from base_helpers import create_renderer, setup_camera, create_cornell_box  # type: ignore

    r = create_renderer()
    create_cornell_box(r)
    setup_camera(
        r,
        look_from=[0.0, 1.0, 4.0],
        look_at=[0.0, 1.0, 0.0],
        vfov=40.0,
        width=WIDTH,
        height=HEIGHT,
    )
    return r
