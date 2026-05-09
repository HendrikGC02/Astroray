"""pkg54 deterministic test scene for CPU-vs-GPU multi-wavelength parity.

A small Cornell-like room with a Lambertian sphere (vegetation), a back wall
(concrete) and a floor patch (water), lit by a single emissive ceiling
light. Spectral profiles can optionally be attached (pkg54a) so the IR/UV
parity gates exercise real profile dispatch on both CPU and GPU rather
than the degenerate near-black fallback.
"""
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROFILES_BIN = os.path.join(REPO_ROOT, "data", "spectral_profiles", "profiles.bin")


def build_scene(renderer, *, attach_profiles=False):
    """Populate *renderer* with the parity scene; returns the material id map.

    When *attach_profiles* is True and the profile database is available,
    vegetation / water / aluminium profiles are attached so non-visible
    bands light up via spectral profile dispatch (pkg54a).
    """
    veg_id    = renderer.create_material("lambertian", [0.20, 0.55, 0.30], {})
    water_id  = renderer.create_material("lambertian", [0.05, 0.10, 0.18], {})
    metal_id  = renderer.create_material("lambertian", [0.85, 0.85, 0.88], {})
    light_id  = renderer.create_material("light",      [1.00, 1.00, 1.00],
                                          {"intensity": 8.0})

    if attach_profiles and os.path.exists(PROFILES_BIN):
        import astroray
        astroray.load_spectral_profiles(PROFILES_BIN)
        renderer.set_material_spectral_profile(veg_id,   "deciduous_leaf_green")
        renderer.set_material_spectral_profile(water_id, "water_clear")
        renderer.set_material_spectral_profile(metal_id, "aluminum_polished")

    S = 2.0
    # Floor — vegetation (right half) + water (left half)
    renderer.add_triangle([ 0, -1, -S], [ S, -1, -S], [ S, -1,  S], veg_id)
    renderer.add_triangle([ 0, -1, -S], [ S, -1,  S], [ 0, -1,  S], veg_id)
    renderer.add_triangle([-S, -1, -S], [ 0, -1, -S], [ 0, -1,  S], water_id)
    renderer.add_triangle([-S, -1, -S], [ 0, -1,  S], [-S, -1,  S], water_id)
    # Back wall — aluminium
    renderer.add_triangle([-S, -1, -S], [ S, -1, -S], [ S,  2, -S], metal_id)
    renderer.add_triangle([-S, -1, -S], [ S,  2, -S], [-S,  2, -S], metal_id)
    # Vegetation sphere (right side)
    renderer.add_sphere([0.4, -0.4, 0.0], 0.55, veg_id)
    # Ceiling light
    renderer.add_triangle([-0.6, 1.99, -0.6], [ 0.6, 1.99, -0.6], [ 0.6, 1.99,  0.6], light_id)
    renderer.add_triangle([-0.6, 1.99, -0.6], [ 0.6, 1.99,  0.6], [-0.6, 1.99,  0.6], light_id)

    return dict(vegetation=veg_id, water=water_id, metal=metal_id, light=light_id)


def setup_camera(renderer, width=64, height=64):
    renderer.setup_camera(
        look_from=[0, 0.4, 3.0], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=45, aspect_ratio=width / height,
        aperture=0.0, focus_dist=3.0,
        width=width, height=height,
    )
    renderer.set_background_color([0.05, 0.05, 0.07])
