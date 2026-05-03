"""IR photography test scene for pkg39.

Outdoor scene with vegetation (deciduous leaf), water, and concrete/building.
Rendered in visible and near-IR side-by-side to verify qualitative IR behaviour:
  - Vegetation bright (Wood effect — high NIR reflectance)
  - Water dark (strong NIR absorption)
  - Concrete/building mid-grey
"""
import sys
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROFILES_BIN = os.path.join(REPO_ROOT, "data", "spectral_profiles", "profiles.bin")


def build_scene(renderer, width=64, height=64, use_profiles=True):
    """Populate *renderer* with a simple outdoor scene.

    Materials: green vegetation plane, dark water plane, concrete wall.
    Attach spectral profiles when *use_profiles* is True and profiles.bin exists.
    Returns a dict mapping name → material_id.
    """
    import astroray
    astroray.load_spectral_profiles(PROFILES_BIN)

    veg_id  = renderer.create_material("lambertian", [0.13, 0.37, 0.08], {})
    water_id = renderer.create_material("lambertian", [0.05, 0.10, 0.15], {})
    concrete_id = renderer.create_material("lambertian", [0.50, 0.48, 0.46], {})
    sky_id  = renderer.create_material("light", [0.70, 0.80, 1.00], {"intensity": 2.0})

    if use_profiles and os.path.exists(PROFILES_BIN):
        renderer.set_material_spectral_profile(veg_id,      "deciduous_leaf_green")
        renderer.set_material_spectral_profile(water_id,    "water_clear")
        renderer.set_material_spectral_profile(concrete_id, "concrete_gray")

    # Ground plane: vegetation
    S = 4.0
    renderer.add_triangle([-S, -1, -S], [ S, -1, -S], [ S, -1,  S], veg_id)
    renderer.add_triangle([-S, -1, -S], [ S, -1,  S], [-S, -1,  S], veg_id)
    # Water patch (recessed, left side)
    renderer.add_triangle([-S, -1.01, -1], [-0.5, -1.01, -1], [-0.5, -1.01, 1], water_id)
    renderer.add_triangle([-S, -1.01, -1], [-0.5, -1.01,  1], [-S,  -1.01, 1], water_id)
    # Concrete back wall
    renderer.add_triangle([-S, -1, -S], [ S, -1, -S], [ S, 2, -S], concrete_id)
    renderer.add_triangle([-S, -1, -S], [ S, 2, -S], [-S, 2, -S], concrete_id)
    # Ceiling light
    renderer.add_triangle([-1, 3, -1], [1, 3, -1], [1, 3, 1], sky_id)
    renderer.add_triangle([-1, 3, -1], [1, 3,  1], [-1, 3, 1], sky_id)

    return dict(vegetation=veg_id, water=water_id, concrete=concrete_id)


def setup_camera(renderer, width=64, height=64):
    renderer.setup_camera(
        look_from=[0, 1.5, 4], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=45, aspect_ratio=width / height,
        aperture=0.0, focus_dist=4.0,
        width=width, height=height,
    )
    renderer.set_background_color([0.1, 0.1, 0.15])
