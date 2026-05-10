"""pkg74 showcase — defaults shared by the runner and tests.

These constants exist so that --quick mode is *actually* quick: the
end-to-end pytest gate asserts the run completes in < 30 s on the
reference workstation. If you need to push samples up, do it with a
CLI flag, not by editing the QUICK_* defaults.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHOWCASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SHOWCASE_DIR / "output"

# --- --quick defaults (asserted-fast in the pytest gate) -----------------
QUICK_RESOLUTION = 96
QUICK_SPP = 32                       # for the material zoo
QUICK_SPP_SERIES = [1, 4, 16, 64, 256]   # for the convergence grid + curve
QUICK_MAX_DEPTH = 6
QUICK_SEED = 0xCAFE

# --- --full defaults (used by Phase 2; documented here for forward ref) --
FULL_RESOLUTION = 256
FULL_SPP = 256
FULL_SPP_SERIES = [1, 4, 16, 64, 256, 1024]
FULL_MAX_DEPTH = 8

# --- Material zoo --------------------------------------------------------
# Per-material-type defaults so the registry-driven zoo gets a useful
# render for each type without hardcoding every entry. Anything not in
# this map falls back to the GENERIC default (mid-grey diffuse).
#
# These are *parameter defaults*, not a curated list — the entry set
# comes from astroray.material_registry_names() at runtime.
MATERIAL_ZOO_DEFAULTS: dict[str, tuple[list[float], dict]] = {
    "lambertian":   ([0.72, 0.45, 0.28], {}),
    "metal":        ([0.95, 0.78, 0.42], {"roughness": 0.12}),
    "mirror":       ([1.0, 1.0, 1.0],   {}),
    "dielectric":   ([1.0, 1.0, 1.0],   {"ior": 1.5}),
    "thin_glass":   ([1.0, 1.0, 1.0],   {"ior": 1.5, "transmission": 1.0}),
    "phong":        ([0.55, 0.30, 0.18], {"shininess": 32.0}),
    "disney":       ([0.65, 0.22, 0.18], {"roughness": 0.4}),
    "subsurface":   ([0.85, 0.40, 0.25], {"scatter_distance": [1.0, 0.4, 0.2], "scale": 1.0}),
    "oren_nayar":   ([0.72, 0.45, 0.28], {"sigma": 0.5}),
    "isotropic":    ([0.85, 0.85, 0.85], {}),
    "two_sided":    ([0.72, 0.72, 0.72], {}),
    "normal_mapped": ([0.72, 0.72, 0.72], {}),
}
GENERIC_MATERIAL_DEFAULT: tuple[list[float], dict] = ([0.72, 0.72, 0.72], {})

# Materials that should be skipped from the zoo on visual grounds — they
# either render as black-on-black (light/emissive at default geometry)
# or are wrappers that need an inner material (two_sided/normal_mapped).
ZOO_SKIPLIST = {
    # Emitters — bare on a sphere they either render flat or wash neighbours.
    "light",
    "emission",
    "emissive",
    "diffuse_light",
    "blackbody",
    "blackbody_emitter",
    "line_emitter",
    "laser_emitter",
    # Wrappers / decorators — need an inner material to render.
    "two_sided",
    "normal_mapped",
}
