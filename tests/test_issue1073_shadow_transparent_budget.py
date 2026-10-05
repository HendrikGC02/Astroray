"""#1073 / #1047 item 3 - shadow rays share the path's transparent budget (CPU + GPU).

Cycles (kernel/integrator/intersect_shadow.h integrate_shadow_max_transparent_hits,
kernel/bvh/intersect_filter.h bvh_shadow_all_anyhit_filter, Apache-2.0): a shadow ray
may cross max(transparent_max_bounce - path.transparent_bounce, 0) transparent
surfaces; the next one blocks it. Verified against Blender 5.2 Cycles (CPU,
transparent_max_bounces = T, N Transparent-BSDF sheets between a floor and a sun):
  * camera sees the floor directly (path pass count 0): lit iff N <= T
    (N=3: T=2 black, T=3 lit; N=2: T=1 black, T=2 lit);
  * 3 sheets between camera AND wall (3 camera passes, then 3 shadow hits): lit iff
    T >= 6 (T = 3, 4, 5 black).
Before the fix the CPU kept its own 8-hop cap (leaking light past it) and the GPU walk
had the same constant, so neither read transparent_max_bounces.

#1047 item 3 claimed Cycles reads Is Singular Ray / Is Reflection Ray on a shadow ray
from the parent path_flag. Cycles 5.2 does not (shade_shadow.h evaluates the shadow
shader with PATH_RAY_VISIBILITY_SHADOW and PATH_RAY_FLAG_NONE): on a shadow ray both
are 0 even when the parent is a singular mirror reflection, while the parent's
Glossy Depth / Diffuse Depth counters ARE read (shadow_path copies the counters).
The engine already matches (shadow context = LPF_SHADOW only), pinned below.
"""
import pytest
from test_issue991_light_path import _UV, BACKENDS, _renderer, _roi
from test_issue1033_transparent_bounce import _wall_value

SUN_W = 3.0


def _quad(r, mat, c, u, v):
    """Quad centre c, half-edges u, v, with its true flat normal u x v (the #991
    helper passes the corner POSITIONS as normals, which shades a horizontal floor
    as if it were vertical)."""
    n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
    ln = sum(x * x for x in n) ** 0.5
    n = [x / ln for x in n]
    p = [[c[i] + su * u[i] + sv * v[i] for i in range(3)]
         for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    r.add_triangle_layers(p[0], p[1], p[2], mat, _UV, n, n, n)
    r.add_triangle_layers(p[0], p[2], p[3], mat, _UV, n, n, n)


def _floor_scene(use_gpu, sheets, spacing=0.1):
    """Camera (0,-6,2) sees the floor origin directly; `sheets` Alpha-0 horizontal
    2x2 quads at z = 0.5 + spacing*i above it (the camera ray never crosses them),
    straight-down sun."""
    r = _renderer(use_gpu)
    r.set_background_color([0.0, 0.0, 0.0])
    r.add_sun_light_dedicated([0.0, 0.0, -1.0], 0.01, {'mode': 'rgb', 'color': [1.0, 1.0, 1.0]},
                              SUN_W, 0, 0)
    floor = r.create_material("principled", [0.8, 0.8, 0.8],
                              {"roughness": 1.0, "specular_ior_level": 0.0})
    _quad(r, floor, [0, 0, 0], [20.0, 0, 0], [0, 20.0, 0])
    sheet = r.create_material("principled", [1.0, 1.0, 1.0], {"alpha": 0.0})
    for i in range(sheets):
        _quad(r, sheet, [0, 0, 0.5 + spacing * i], [1.0, 0, 0], [0, 1.0, 0])
    return r


def _floor_value(use_gpu, sheets, limit):
    from base_helpers import setup_camera
    r = _floor_scene(use_gpu, sheets)
    setup_camera(r, look_from=[0, -6, 2], look_at=[0, 0, 0], vup=[0, 0, 1], vfov=10,
                 width=32, height=32)
    img = r.render(48, 4, None, False, -1, -1, -1, -1, limit)
    return float(_roi(img, 16, 16, 3).mean())


@pytest.mark.parametrize("use_gpu", BACKENDS)
@pytest.mark.parametrize("sheets", [2, 3, 10])
def test_shadow_ray_crosses_exactly_the_transparent_budget(use_gpu, sheets):
    """N sheets between the floor and the sun: lit with limit N, black with N-1
    (Cycles). N = 10 also checks the old 8-hop cap no longer leaks light."""
    ref = _floor_value(use_gpu, 0, -1)
    assert ref > 0.3, ref
    blocked = _floor_value(use_gpu, sheets, sheets - 1)
    assert blocked < 0.05 * ref, (sheets, blocked, ref)
    lit = _floor_value(use_gpu, sheets, sheets)
    assert lit == pytest.approx(ref, rel=0.05), (sheets, lit, ref)
    unlimited = _floor_value(use_gpu, sheets, -1)
    assert unlimited == pytest.approx(ref, rel=0.05), (sheets, unlimited, ref)


@pytest.mark.parametrize("use_gpu", BACKENDS)
def test_shadow_budget_is_net_of_the_paths_own_passes(use_gpu):
    """3 wide sheets between camera and wall: the camera path spends 3 passes, the
    shadow ray from the wall crosses the same 3 sheets, so the wall is lit only for
    T >= 6 (Blender 5.2: black for T = 3, 4, 5)."""
    ref = _wall_value(use_gpu, 0)
    assert ref > 0.3, ref
    for t in (4, 5):
        v = _wall_value(use_gpu, 3, transparent=t)
        assert v < 0.05 * ref, (t, v, ref)
    for t in (6, 8, -1):
        v = _wall_value(use_gpu, 3, transparent=t)
        assert v == pytest.approx(ref, rel=0.05), (t, v, ref)


# ---- #1047 item 3: Is Singular / Is Reflection on shadow rays ------------------------
def _lp_probe(use_gpu, output, view):
    """Floor origin lit by a straight-down sun through a sheet Mix(Fac = <output>,
    A = opaque black, B = Transparent). A shadow ray that sees Fac = 1 passes the
    sheet (floor lit); Fac = 0 blocks it. view 'mirror': the floor is seen through a
    horizontal mirror, so the parent path is a singular glossy reflection."""
    import shader_vm_compiler as C
    from base_helpers import setup_camera
    r = _renderer(use_gpu)
    r.set_background_color([0.0, 0.0, 0.0])
    r.add_sun_light_dedicated([0.0, 0.0, -1.0], 0.01, {'mode': 'rgb', 'color': [1.0, 1.0, 1.0]},
                              SUN_W, 0, 0)
    floor = r.create_material("principled", [0.8, 0.8, 0.8],
                              {"roughness": 1.0, "specular_ior_level": 0.0})
    _quad(r, floor, [0, 0, 0], [20.0, 0, 0], [0, 20.0, 0])
    black = r.create_material("principled", [0.0, 0.0, 0.0],
                              {"roughness": 1.0, "specular_ior_level": 0.0})
    clear = r.create_material("principled", [1.0, 1.0, 1.0], {"alpha": 0.0})
    sheet = r.create_light_path_mix(black, clear, C.LIGHT_PATH_OUTPUTS.index(output))
    # Covers the floor origin; off the camera ray (y = -3 at z = 1) and the
    # mirror-reflected ray (y = -1 at z = 1).
    _quad(r, sheet, [0, 0.5, 1.0], [1.0, 0, 0], [0, 1.0, 0])
    if view == "direct":
        setup_camera(r, look_from=[0, -6, 2], look_at=[0, 0, 0], vup=[0, 0, 1], vfov=10,
                     width=32, height=32)
    else:
        mirror = r.create_material("principled", [1.0, 1.0, 1.0],
                                   {"metallic": 1.0, "roughness": 0.0})
        # mirror face down at z = 4; camera (0,-6,2) -> (0,-4,4) -> floor origin
        _quad(r, mirror, [0, -4, 4], [0, 1.0, 0], [1.0, 0, 0])
        setup_camera(r, look_from=[0, -6, 2], look_at=[0, -4, 4], vup=[0, 0, 1], vfov=8,
                     width=32, height=32)
    img = r.render(64, 6, None, False)
    return float(_roi(img, 16, 16, 2).mean())


@pytest.mark.parametrize("use_gpu", BACKENDS)
@pytest.mark.parametrize("view", ["direct", "mirror"])
def test_shadow_ray_reads_neither_is_singular_nor_is_reflection(use_gpu, view):
    """Blender 5.2: Is Singular Ray and Is Reflection Ray are 0 on a shadow ray even
    under a singular mirror parent (floor stays shadowed); Is Shadow Ray is 1."""
    lit = _lp_probe(use_gpu, "Is Shadow Ray", view)
    assert lit > 0.2, lit
    for output in ("Is Singular Ray", "Is Reflection Ray"):
        v = _lp_probe(use_gpu, output, view)
        assert v < 0.25 * lit, (output, view, v, lit)
