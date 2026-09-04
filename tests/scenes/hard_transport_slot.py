"""pkg136 — hard-transport reference scene (Veach-door / light-through-a-slot).

The acceptance scene for the path-guiding variance-reduction gate (spec §6). A
diffuse chamber the camera looks into is lit ONLY through a small slot in its back
wall, behind which sits a bright light in a hidden compartment. Most visible
surfaces cannot see the slot directly, so their radiance arrives via multi-bounce
indirect transport that BSDF sampling almost never aims at the slot — exactly the
high-variance regime path guiding is meant to fix. NEE/two-sided MIS handle the
few directly-slot-visible spots; the rest is hard indirect.

Box: half-extent S=1, camera inside near +z. Back wall at z=-S is built as four
border panels around a central slot; a hidden compartment (z in [-1.5,-1]) holds a
+z-facing area light so light only reaches the chamber through the slot.
"""

S = 1.0
SLOT = 0.16          # half-width of the back-wall slot
COMP = 1.5           # back of the hidden compartment (z=-COMP)


def _quad(r, a, b, c, d, mat, n=None):
    if n is None:
        r.add_triangle(a, b, c, mat)
        r.add_triangle(a, c, d, mat)
    else:
        r.add_triangle(a, b, c, mat)
        r.add_triangle(a, c, d, mat)


def build_scene(renderer):
    white = renderer.create_material("lambertian", [0.73, 0.73, 0.73], {})
    red = renderer.create_material("lambertian", [0.65, 0.05, 0.05], {})
    green = renderer.create_material("lambertian", [0.12, 0.45, 0.15], {})
    light = renderer.create_material("light", [1.0, 0.95, 0.85], {"intensity": 60.0})

    # --- Visible chamber (z in [-S, S]) ---
    # Floor / ceiling
    _quad(r=renderer, a=[-S, -S, -S], b=[S, -S, -S], c=[S, -S, S], d=[-S, -S, S], mat=white)
    _quad(r=renderer, a=[-S, S, -S], b=[S, S, S], c=[S, S, -S], d=[-S, S, S], mat=white)
    # Left (red) / right (green)
    _quad(r=renderer, a=[-S, -S, -S], b=[-S, -S, S], c=[-S, S, S], d=[-S, S, -S], mat=red)
    _quad(r=renderer, a=[S, -S, -S], b=[S, S, S], c=[S, -S, S], d=[S, S, -S], mat=green)
    # Front wall behind the camera (closes the box)
    _quad(r=renderer, a=[-S, -S, S], b=[S, -S, S], c=[S, S, S], d=[-S, S, S], mat=white)

    # --- Back wall at z=-S with a central slot (four border panels) ---
    z = -S
    # bottom border (y from -S to -SLOT), top border (y from SLOT to S)
    _quad(r=renderer, a=[-S, -S, z], b=[S, -S, z], c=[S, -SLOT, z], d=[-S, -SLOT, z], mat=white)
    _quad(r=renderer, a=[-S, SLOT, z], b=[S, SLOT, z], c=[S, S, z], d=[-S, S, z], mat=white)
    # left border (x -S..-SLOT), right border (x SLOT..S), spanning the slot's y band
    _quad(r=renderer, a=[-S, -SLOT, z], b=[-SLOT, -SLOT, z], c=[-SLOT, SLOT, z], d=[-S, SLOT, z], mat=white)
    _quad(r=renderer, a=[SLOT, -SLOT, z], b=[S, -SLOT, z], c=[S, SLOT, z], d=[SLOT, SLOT, z], mat=white)

    # --- Hidden compartment behind the slot (z in [-COMP, -S]) ---
    # walls (white, to bounce light toward the slot)
    _quad(r=renderer, a=[-S, -S, -COMP], b=[S, -S, -COMP], c=[S, -S, z], d=[-S, -S, z], mat=white)   # floor
    _quad(r=renderer, a=[-S, S, -COMP], b=[S, S, z], c=[S, S, -COMP], d=[-S, S, z], mat=white)         # ceiling
    _quad(r=renderer, a=[-S, -S, -COMP], b=[-S, -S, z], c=[-S, S, z], d=[-S, S, -COMP], mat=white)     # left
    _quad(r=renderer, a=[S, -S, -COMP], b=[S, S, z], c=[S, -S, z], d=[S, S, -COMP], mat=white)         # right
    _quad(r=renderer, a=[-S, -S, -COMP], b=[S, S, -COMP], c=[S, -S, -COMP], d=[-S, S, -COMP], mat=white)  # back

    # Area light inside the compartment, facing +z toward the slot.
    LZ = -COMP + 0.15
    LW = 0.5
    renderer.add_triangle([-LW, -LW, LZ], [LW, -LW, LZ], [LW, LW, LZ], light)
    renderer.add_triangle([-LW, -LW, LZ], [LW, LW, LZ], [-LW, LW, LZ], light)

    return dict(white=white, red=red, green=green, light=light)


def setup_camera(renderer, width=64, height=64):
    renderer.setup_camera(
        look_from=[0, 0, 0.9], look_at=[0, 0, -1], vup=[0, 1, 0],
        vfov=70, aspect_ratio=width / height,
        aperture=0.0, focus_dist=1.0, width=width, height=height,
    )
    renderer.set_background_color([0.0, 0.0, 0.0])
