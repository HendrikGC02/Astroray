"""pkg161 -- `firefly_window`: the first scene in this library that has a real
firefly population.

WHY THIS SCENE EXISTS
---------------------
Measured on RTX 5070 Ti, 2026-07-26 (pkg157 / PR #526), tail-heaviness
(peak / p99.9 of output luminance) across the ENTIRE scene suite at 16 / 64 spp:

    diffuse_light_cornell  1.82x / 1.53x      dielectric_cornell  1.40x / 1.13x
    thin_glass_cornell     1.66x / 1.52x      metal_cornell       1.07x / 1.04x
    disney_cornell         1.66x / 1.52x

A genuine firefly population reads in the tens to hundreds. Not one scene had a
tail, so "clampIndirect suppresses fireflies without energy loss" was not
demonstrable anywhere -- pkg157's gate for it is skipped and pkg144 contract
item 3 was formally amended as undemonstrable. This scene closes that hole.

WHAT A FIREFLY REQUIRES (cited, not invented -- CLAUDE.md SS6)
--------------------------------------------------------------
Zirr, Hanika & Dachsbacher, "Re-Weighting Firefly Samples for Improved
Finite-Sample Monte Carlo Estimates", Computer Graphics Forum 37(6):410-421,
2018 (DOI 10.1111/cgf.13335) define a firefly as a sample with "high
contribution but low probability density". The Blender Manual's Cycles
"Clamping" section says the same operationally: "Some light paths have a low
probability of being found while contributing much light to the pixel, causing
fireflies to be found in some pixels and not in others."

Two properties, both required at once:

  1. contribution >> image mean  ->  a physically tiny, very high-RADIANCE
     emitter (radiance, not power -- power stays small);
  2. low sampling probability    ->  that emitter must be unreachable by
     next-event estimation, so only BSDF sampling can ever find it.

Property 2 is what every existing scene here lacks: all their emitters are
NEE-sampled and unoccluded, so the low-variance strategy finds them on nearly
every sample and there is nothing left in the tail.

THE ONE TRANSPORT CHANNEL IN THIS ENGINE THAT CAN CARRY A FIREFLY
-----------------------------------------------------------------
Read out of the source, not assumed (see
.astroray_plan/docs/pkg161-firefly-scene-research.md for the full table):

  * A BSDF ray that hits an emitter after a NON-delta bounce contributes
    NOTHING -- `if (bounce == 0 || wasSpecular)` at include/raytracer.h:2415
    discards it and breaks the path (there is no BSDF-side MIS term; known gap,
    filed as pkg120). GPU twin: src/gpu/wavefront/stage_advance.cu:239-243.
  * NEE is power-heuristic MIS-weighted and its near-field singularity is capped
    at 1000x by `1/(pdf + 0.001)` -- low variance by construction.
  * Russian roulette CANNOT produce unbounded fireflies here: survival is
    `p = min(0.95, XYZ.Y(throughput))`, so a survivor is renormalised to
    Y == 1 (self-limiting), and `throughput.maxValue() > 10` is rescaled every
    bounce anyway (raytracer.h:2528-2530, stage_advance.cu:649-651).

So the ONLY unbounded-variance channel is `diffuse -> delta-specular ->
emitter`: Heckbert's `L S D E` path class, which next-event estimation cannot
connect to by construction (a delta vertex has zero probability of lying on a
shadow ray). The scene is built around that channel and nothing else.

LAYOUT -- "a very bright light outside a window"
------------------------------------------------
        * hidden emitter (tiny sphere, radiance ~10^3)     OUTSIDE the room
        |
  ======#======   opaque ceiling, square aperture sealed by a thin_glass pane
  |            |
  | []      [] |  two ordinary ceiling area lights -> ALL of the bulk light
  |            |
  |   camera   |  looks DOWN: everything at or above camera height is
  |____________|  out of frame, so no specular chain from bounce 0 exists

  * The pane is `thin_glass`, roughness 0 -> `isDelta = true`
    (plugins/materials/thin_glass.cpp:71) and transmits straight through
    (`wi = -wo`, :95). A genuine delta vertex. NOT a single `dielectric` quad:
    that is the two-quad hack memory `general-photon-loop-needs-solid-glass`
    warns about, and a dielectric sphere cannot seal a square aperture without
    either interpenetrating the ceiling or leaving its corners open.
  * Shadow rays are blocked by ANY geometry (raytracer.h:2437 -- the BVH test is
    material-agnostic), so the pane makes the emitter 100% NEE-invisible. Every
    joule it delivers arrives through the delta channel.
  * The firefly path is  camera -> floor (bounce 0, diffuse) -> pane (bounce 1,
    delta) -> emitter (bounce 2).  bounce 2 > 0, so the whole firefly population
    is INDIRECT (clampIndirect) while the entire bulk image is bounce-0 NEE
    (clampDirect). The two halves of pkg157's gate are separated by
    construction, not by luck.
  * The hidden emitter is OUTSIDE rather than a lens inside because a small
    emitter at radiance ~10^3 seen by the camera through any specular chain
    makes a deterministic few-pixel feature at 10^2-10^3x the image mean, which
    would set `peak` with no firefly involved -- a fake tail. An earlier draft
    used the canonical glass-ball-caustic-on-a-floor layout and was discarded
    for exactly that: a ball lens has f ~ 1.5R, so it must sit within about one
    focal length of the receiver to concentrate, which puts it in frame.

TUNING MODEL (this is how to recalibrate; see verify_pkg161_firefly_scene.py)
-----------------------------------------------------------------------------
With  L_e = emitter radiance, r_e = emitter radius, N = pixels, mu = mean
luminance, k = p99.9/mu of the NORMAL population, n_ff = firefly pixel count,
R = peak/p99.9, s = share of image energy carried by the firefly channel:

    R    ~  L_e / spp                 (magnitude = throughput * L_e / spp)
    n_ff ~  N * spp * r_e^2           (hit rate ~ emitter solid angle ~ r_e^2)
    s    =  n_ff * R * k / N   ~  r_e^2 * L_e

i.e. EMITTER_INTENSITY alone sets the ratio, EMITTER_RADIUS alone sets the
count. They are independent and monotone, so two renders solve for both.

Three constraints act at once, and they are tighter than they look:
    R >= 10             (pkg161 contract item 2)
    n_ff <= 0.001 * N   (else p99.9 lands INSIDE the firefly population and R
                         collapses to ~2 -- every firefly has nearly the same
                         magnitude, so the top 0.1% would just be double hits)
    s < 0.02            (pkg157's energy half: the energy a p99.9 clamp removes
                         IS s)
Together they pin n_ff to roughly one decade, and since n_ff ~ N * spp the
firefly count is directly proportional to render cost. Hence the separate,
deliberately-enlarged CPU emitter below.

THE DEFAULT CONSTANTS BELOW ARE DESIGN TARGETS, NOT MEASUREMENTS.
They were derived analytically (implementer had no GPU and ran no renders).
Run scripts/verify_pkg161_firefly_scene.py to measure and replace them.
"""

from __future__ import annotations

import numpy as np


# ---------------------------------------------------------------------------
# Tuned parameters -- see the TUNING MODEL section above.
# ---------------------------------------------------------------------------

#: Emitter radiance. Sets the tail ratio: R ~ EMITTER_INTENSITY / spp.
EMITTER_INTENSITY = 2400.0

#: Emitter radius (metres). Sets the firefly *count* and hence the energy
#: share s ~ r_e^2 * L_e. Does NOT affect the tail ratio.
EMITTER_RADIUS = 0.0075

#: The CPU leg renders ~1/8 the samples of the GPU leg, and n_ff ~ N * spp, so
#: at the shipped radius it would sit in the Poisson-zero-risk regime. Scaling
#: the radius raises the hit RATE (n_ff ~ r_e^2) and leaves the tail RATIO
#: untouched (R ~ L_e / spp only), so the CPU leg measures the same phenomenon
#: at a fraction of the cost. The larger energy share this implies is
#: irrelevant to the CPU leg, which asserts the ratio, not the clamp cost.
CPU_EMITTER_RADIUS_SCALE = 2.0


# ---------------------------------------------------------------------------
# Recommended render configurations.
# ---------------------------------------------------------------------------

#: GPU / pkg157-gate configuration. Large N because n_ff <= 0.001 * N and
#: n_ff >= ~8 for reliability jointly demand N >~ 5e4.
WIDTH = 480
HEIGHT = 360
SAMPLES = 64
MAX_DEPTH = 8
SEED = 16101

#: CPU configuration -- paired with CPU_EMITTER_RADIUS_SCALE.
CPU_WIDTH = 240
CPU_HEIGHT = 180
CPU_SAMPLES = 32


# ---------------------------------------------------------------------------
# Geometry constants (metres, Y up).
# ---------------------------------------------------------------------------

ROOM = 2.0          # room half-extent in x and z
CEILING_Y = 3.0
APERTURE = 0.25     # ceiling hole half-width
PANE_Y = 3.02       # thin_glass pane, just above the ceiling
PANE = 0.32         # pane half-width (> APERTURE, so the hole is sealed)
EMITTER_Y = 3.60    # hidden emitter, outside the room
LIGHT_Y = 2.97      # room area lights, just below the ceiling


def _quad(renderer, p00, p10, p11, p01, mat):
    """Two triangles spanning p00 -> p10 -> p11 -> p01 (winding preserved)."""
    renderer.add_triangle(p00, p10, p11, mat)
    renderer.add_triangle(p00, p11, p01, mat)


def build_scene(renderer, *, emitter_radius=EMITTER_RADIUS,
                emitter_intensity=EMITTER_INTENSITY):
    """Populate *renderer* with the firefly-window scene.

    Returns the material id map. Caller owns seed / integrator / spp, per the
    convention in this directory -- with one deliberate exception, below.
    """
    # DELIBERATE EXCEPTION to "the caller owns render config": adaptive
    # sampling must be off for this scene to mean anything.
    # include/raytracer.h:3001-3007 -- the CPU adaptive mode is an EARLY-OUT: a
    # pixel stops once its running relative std-dev drops below 1%, and
    # normalises by its own sample count. On this scene that (a) cuts the number
    # of chances a pixel gets to catch a firefly and (b) makes a caught
    # firefly's magnitude depend on *when* it was caught. It also does not exist
    # on the GPU wavefront, so leaving it on breaks CPU/GPU comparability. A
    # caller who forgets this gets silently wrong tail statistics, so the scene
    # owns it rather than every call site.
    renderer.set_adaptive_sampling(False)

    white = renderer.create_material("lambertian", [0.73, 0.73, 0.73], {})
    room_light = renderer.create_material("light", [1.0, 1.0, 1.0],
                                          {"intensity": 15.0})
    # roughness 0 -> isDelta (thin_glass.cpp:71). This is the delta vertex the
    # entire firefly channel depends on; do not roughen it.
    pane = renderer.create_material("thin_glass", [1.0, 1.0, 1.0],
                                    {"ior": 1.5, "roughness": 0.0,
                                     "transmission": 1.0})
    hidden = renderer.create_material("light", [1.0, 1.0, 1.0],
                                      {"intensity": emitter_intensity})

    R, C = ROOM, CEILING_Y

    # Floor.
    _quad(renderer, [-R, 0, -R], [R, 0, -R], [R, 0, R], [-R, 0, R], white)
    # Four walls, full height, so the room is closed and the hidden emitter has
    # no line of sight into it except through the aperture.
    _quad(renderer, [-R, 0, -R], [R, 0, -R], [R, C, -R], [-R, C, -R], white)
    _quad(renderer, [-R, 0, R], [R, 0, R], [R, C, R], [-R, C, R], white)
    _quad(renderer, [-R, 0, -R], [-R, 0, R], [-R, C, R], [-R, C, -R], white)
    _quad(renderer, [R, 0, -R], [R, 0, R], [R, C, R], [R, C, -R], white)

    # Ceiling with a square aperture: four quads around the hole.
    A = APERTURE
    _quad(renderer, [-R, C, -R], [R, C, -R], [R, C, -A], [-R, C, -A], white)
    _quad(renderer, [-R, C, A], [R, C, A], [R, C, R], [-R, C, R], white)
    _quad(renderer, [-R, C, -A], [-A, C, -A], [-A, C, A], [-R, C, A], white)
    _quad(renderer, [A, C, -A], [R, C, -A], [R, C, A], [A, C, A], white)

    # The pane seals the aperture. Every straight line from inside the room to
    # the hidden emitter that clears the hole also crosses the pane: the emitter
    # sits on the axis 0.6 above the aperture, so a line from the floor reaching
    # the hole edge (|x| = A) is at |x| = A * (EMITTER_Y - PANE_Y) /
    # (EMITTER_Y - CEILING_Y) ~ 0.25 * 0.58/0.60 ~ 0.24 at the pane's height --
    # far inside PANE = 0.32. Hence NEE to the emitter is ALWAYS occluded.
    P = PANE
    _quad(renderer, [-P, PANE_Y, -P], [P, PANE_Y, -P],
          [P, PANE_Y, P], [-P, PANE_Y, P], pane)

    # Two ordinary ceiling area lights supply all the bulk illumination. Winding
    # matches the library convention (metal_cornell.py:68) so the outward normal
    # is -Y and they emit downward into the room.
    for x0, x1 in ((-1.55, -0.65), (0.65, 1.55)):
        z0, z1 = -0.55, 0.55
        renderer.add_triangle([x0, LIGHT_Y, z0], [x1, LIGHT_Y, z0],
                              [x1, LIGHT_Y, z1], room_light)
        renderer.add_triangle([x0, LIGHT_Y, z0], [x1, LIGHT_Y, z1],
                              [x0, LIGHT_Y, z1], room_light)

    # The hidden emitter. Tiny and extremely bright: high radiance (firefly
    # magnitude) at low power (small energy share).
    renderer.add_sphere([0.0, EMITTER_Y, 0.0], emitter_radius, hidden)

    return dict(white=white, room_light=room_light, pane=pane, hidden=hidden)


def setup_camera(renderer, width=WIDTH, height=HEIGHT):
    """Camera inside the room, looking down.

    Pitched steeply enough that the top of the frame is ~34 degrees below
    horizontal, so the ceiling, the room lights, the pane and the emitter are
    ALL out of frame. That is a correctness requirement, not framing taste: a
    camera that can reach the emitter through a delta chain records a
    deterministic ~10^3 feature that would set `peak` with no firefly involved.
    """
    renderer.setup_camera(
        look_from=[0.0, 2.55, 1.55], look_at=[0.0, 0.0, -0.35], vup=[0, 1, 0],
        vfov=38, aspect_ratio=width / height,
        aperture=0.0, focus_dist=3.2,
        width=width, height=height,
    )
    renderer.set_background_color([0.0, 0.0, 0.0])


# ---------------------------------------------------------------------------
# Tail statistics. Shared by the pkg161 tests, the pkg157 gate and the
# calibration script so all three measure the identical quantity.
# ---------------------------------------------------------------------------

def luminance(pixels: np.ndarray) -> np.ndarray:
    """Rec.709 luminance of a linear RGB image."""
    px = np.asarray(pixels, dtype=np.float64)
    return 0.2126 * px[..., 0] + 0.7152 * px[..., 1] + 0.0722 * px[..., 2]


def tail_stats(pixels: np.ndarray, percentile: float = 99.9) -> dict:
    """Tail-heaviness of a LINEAR-rendered image.

    `ratio` = peak / p99.9 is the statistic pkg161 is specified against. It MUST
    be computed on a linear render: render(..., apply_gamma=True) clamps to
    [0, 1] before the 1/2.2 power (module/blender_module.cpp:1803-1811), which
    annihilates exactly the outliers being measured. Memory:
    `gamma-furnace-cannot-detect-energy-gain`.
    """
    lum = luminance(pixels)
    peak = float(lum.max())
    cut = float(np.percentile(lum, percentile))
    mean = float(lum.mean())
    return {
        "peak": peak,
        "p99_9": cut,
        "mean": mean,
        "ratio": peak / cut if cut > 0.0 else float("inf"),
        "n_pixels": int(lum.size),
        # The firefly population proper: pixels an order of magnitude above the
        # tail cut. This is the design-window diagnostic -- it must stay well
        # under 0.1% of the image, or the 99.9th percentile is itself a firefly
        # and `ratio` collapses toward the ~2x of a double-hit-vs-single-hit
        # comparison. If a calibration run shows n_fireflies > 0.001 * n_pixels,
        # shrink EMITTER_RADIUS; if it shows 0, grow it.
        "n_fireflies": int((lum > 10.0 * cut).sum()),
    }
