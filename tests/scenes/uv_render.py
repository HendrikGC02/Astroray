"""UV rendering test scene for pkg39.

Same outdoor scene as ir_photography but rendered at 300-400 nm to verify
UV behaviour:
  - Vegetation dark (chlorophyll absorbs UV)
  - Metals reflective (aluminium has high UV reflectance)
  - White paint/concrete dark (TiO2 absorbs UV)
"""
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROFILES_BIN = os.path.join(REPO_ROOT, "data", "spectral_profiles", "profiles.bin")


def build_scene(renderer, width=64, height=64):
    import astroray
    astroray.load_spectral_profiles(PROFILES_BIN)

    veg_id   = renderer.create_material("lambertian", [0.13, 0.37, 0.08], {})
    metal_id = renderer.create_material("lambertian", [0.90, 0.90, 0.92], {})
    paint_id = renderer.create_material("lambertian", [0.90, 0.90, 0.90], {})
    light_id = renderer.create_material("light", [0.80, 0.80, 1.00], {"intensity": 3.0})

    if os.path.exists(PROFILES_BIN):
        renderer.set_material_spectral_profile(veg_id,   "deciduous_leaf_green")
        renderer.set_material_spectral_profile(metal_id, "aluminum_polished")
        renderer.set_material_spectral_profile(paint_id, "white_paint")

    S = 4.0
    # Vegetation ground
    renderer.add_triangle([-S, -1, -S], [S, -1, -S], [S, -1, S], veg_id)
    renderer.add_triangle([-S, -1, -S], [S, -1,  S], [-S,-1, S], veg_id)
    # Metal surface (right half)
    renderer.add_triangle([0, -1, -S], [S, -1, -S], [S, -1, S], metal_id)
    renderer.add_triangle([0, -1, -S], [S, -1,  S], [0, -1, S], metal_id)
    # White paint wall
    renderer.add_triangle([-S, -1, -S], [S, -1, -S], [S, 2, -S], paint_id)
    renderer.add_triangle([-S, -1, -S], [S, 2,  -S], [-S, 2, -S], paint_id)
    # UV light source (ceiling)
    renderer.add_triangle([-1, 3, -1], [1, 3, -1], [1, 3, 1], light_id)
    renderer.add_triangle([-1, 3, -1], [1, 3,  1], [-1, 3, 1], light_id)

    return dict(vegetation=veg_id, metal=metal_id, paint=paint_id)


def setup_camera(renderer, width=64, height=64):
    renderer.setup_camera(
        look_from=[0, 1.5, 4], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=45, aspect_ratio=width / height,
        aperture=0.0, focus_dist=4.0,
        width=width, height=height,
    )
    renderer.set_background_color([0.0, 0.0, 0.0])
