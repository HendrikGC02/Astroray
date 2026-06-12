"""
pkg115 Stage 2 parity tests: procedural textures match Blender/Cycles formulas.

Per the audit (.astroray_plan/docs/blender-procedural-parity-research.md),
each fixed evaluator is tested against hand-computed values from the cited
Cycles svm kernel functions (Apache-2.0).

Scope: items 1-4 only (Coordinate/Mapping wiring, Checker, Gradient, Magic).
"""
import pytest
import math

def test_checker_floor_parity():
    """Checker uses floor-parity, not sine-product.

    Cycles intern/cycles/kernel/svm/checker.h::svm_checker (Apache-2.0):
      p = (p + 0.000001) * 0.999999;
      xi = abs((int)floor(p.x)); yi = …; zi = …;
      return ((xi % 2 == yi % 2) == (zi % 2)) ? 1 : 0;

    Applied to co * scale. Default scale 5.0.
    """
    import astroray
    r = astroray.Renderer()

    # C++ semantics of the Cycles formula (bool promotes to int 0/1):
    #   parity(xi,yi,zi) = ((xi%2 == yi%2) == zi%2);  parity-true -> Color1.
    # Truth table at scale=1 (cells 1 unit wide):
    #   (0.5,0.5,0.5) -> floors (0,0,0): (0==0)=1, zi%2=0 -> 1==0 FALSE -> Color2
    #   (0.5,0.5,1.5) -> floors (0,0,1): (0==0)=1, zi%2=1 -> 1==1 TRUE  -> Color1
    #   (1.5,0.5,0.5) -> floors (1,0,0): (1==0)=0, zi%2=0 -> 0==0 TRUE  -> Color1
    params = {"color1": [0.8, 0.8, 0.8], "color2": [0.2, 0.2, 0.2], "scale": 1.0}

    v = r.eval_texture_at_3d("checker", params, 0.5, 0.5, 0.5)
    assert abs(v[0] - 0.2) < 0.01, f"(0,0,0) cell must be Color2 (0.2), got {v[0]}"

    v = r.eval_texture_at_3d("checker", params, 0.5, 0.5, 1.5)
    assert abs(v[0] - 0.8) < 0.01, f"(0,0,1) cell must be Color1 (0.8), got {v[0]}"

    v = r.eval_texture_at_3d("checker", params, 1.5, 0.5, 0.5)
    assert abs(v[0] - 0.8) < 0.01, f"(1,0,0) cell must be Color1 (0.8), got {v[0]}"


def test_gradient_quadratic_clamp():
    """Gradient quadratic: max(x,0)², then saturate.

    Cycles intern/cycles/kernel/svm/gradient.h (Apache-2.0): r = max(x,0); return r*r;
    then saturate. At x=-1 (negative), Blender gives 0; old engine gave 1.
    """
    import astroray
    r = astroray.Renderer()

    # Gradient type 1 (quadratic), scale=1. At x=-1, Blender: max(-1,0)=0 → 0² → 0 (c1).
    # Old engine: clamp(x²,0,1) = clamp(1,0,1) = 1 (c2).
    val = r.eval_texture_at_3d("gradient", {
        "grad_type": 1,  # quadratic
        "color1": [0.0, 0.0, 0.0],
        "color2": [1.0, 1.0, 1.0],
        "scale": 1.0
    }, -1.0, 0.0, 0.0)
    assert val[0] < 0.1, f"Gradient quadratic at x=-1 should be ~0, got {val[0]}"


def test_gradient_spherical_inverted():
    """Gradient spherical: max(0.999999 - len, 0) — decreases outward.

    Cycles svm/gradient.h (Apache-2.0): r = max(0.999999 − √(x²+y²+z²), 0).
    Old engine: t = clamp(len, 0, 1) — increased outward. At origin, Blender=1; at len=1, Blender=0.
    """
    import astroray
    r = astroray.Renderer()

    # Gradient type 4 (spherical), scale=1. At origin (0,0,0), len=0 → 0.999999−0 ≈ 1.0 (c2).
    val_origin = r.eval_texture_at_3d("gradient", {
        "grad_type": 4,
        "color1": [0.0, 0.0, 0.0],
        "color2": [1.0, 1.0, 1.0],
        "scale": 1.0
    }, 0.0, 0.0, 0.0)
    assert val_origin[0] > 0.9, f"Spherical at origin should be ~1, got {val_origin[0]}"

    # At (1,0,0): len=1 → 0.999999−1 = −0.000001 → max(−0.000001,0)=0 (c1).
    val_edge = r.eval_texture_at_3d("gradient", {
        "grad_type": 4,
        "color1": [0.0, 0.0, 0.0],
        "color2": [1.0, 1.0, 1.0],
        "scale": 1.0
    }, 1.0, 0.0, 0.0)
    assert val_edge[0] < 0.1, f"Spherical at len=1 should be ~0, got {val_edge[0]}"


def test_gradient_quadratic_sphere():
    """Gradient quadratic sphere: (1−len)², not 1−len².

    Cycles svm/gradient.h: r = max(0.999999 − len, 0); return r². Old engine: 1 − clamp(r², 0, 1).
    At len=0.5, Blender: (1−0.5)² = 0.25. Old engine: 1−0.25 = 0.75.
    """
    import astroray
    r = astroray.Renderer()

    val = r.eval_texture_at_3d("gradient", {
        "grad_type": 5,  # quadratic sphere
        "color1": [0.0, 0.0, 0.0],
        "color2": [1.0, 1.0, 1.0],
        "scale": 1.0
    }, 0.5, 0.0, 0.0)
    # len=0.5 → r=0.999999−0.5≈0.5 → r²=0.25 → lerp(c1,c2,0.25) → 0.25.
    assert 0.2 < val[0] < 0.3, f"Quadratic sphere at len=0.5 should be ~0.25, got {val[0]}"


def test_gradient_radial_phase():
    """Gradient radial: atan2(y,x)/2π + 0.5, not +1.0 then fmod.

    Cycles svm/gradient.h (Apache-2.0): atan2(y,x)/2π + 0.5. Old engine: fmod(...+1.0, 1.0) — half-turn offset.
    At (1,0), atan2(0,1)=0 → 0/2π+0.5 = 0.5.
    """
    import astroray
    r = astroray.Renderer()

    val = r.eval_texture_at_3d("gradient", {
        "grad_type": 6,  # radial
        "color1": [0.0, 0.0, 0.0],
        "color2": [1.0, 1.0, 1.0],
        "scale": 1.0
    }, 1.0, 0.0, 0.0)
    # atan2(0,1)=0 → 0+0.5 = 0.5 → lerp(c1,c2,0.5) → 0.5.
    assert 0.45 < val[0] < 0.55, f"Radial at (1,0) should be ~0.5, got {val[0]}"


def test_magic_depth_10():
    """Magic supports depth ≤ 10, uses fmod(p·scale, 2π) then ·5.

    Cycles intern/cycles/kernel/svm/magic.h::svm_magic (Apache-2.0). Old engine capped depth at 5,
    used scale·π directly. New: verbatim port, depth ≤ 10, true RGB output (0.5−x, 0.5−y, 0.5−z).
    Test that depth=10 runs without error and produces a different pattern than depth=2.
    """
    import astroray
    r = astroray.Renderer()

    val_d2 = r.eval_texture_at_3d("magic", {
        "turb_depth": 2,
        "scale": 5.0,
        "distortion": 1.0,
        "color1": [0.0, 0.0, 0.0],
        "color2": [1.0, 1.0, 1.0]
    }, 0.3, 0.4, 0.5)

    val_d10 = r.eval_texture_at_3d("magic", {
        "turb_depth": 10,
        "scale": 5.0,
        "distortion": 1.0,
        "color1": [0.0, 0.0, 0.0],
        "color2": [1.0, 1.0, 1.0]
    }, 0.3, 0.4, 0.5)

    # Should differ (more cascading trig at depth 10).
    assert abs(val_d2[0] - val_d10[0]) > 0.01, \
        "Magic depth=2 and depth=10 should produce different values"


def test_magic_rgb_output():
    """Magic outputs true RGB (0.5−x, 0.5−y, 0.5−z) per channel, not a scalar lerp.

    Cycles svm_node_tex_magic (svm/magic.h, Apache-2.0): the Color socket
    carries the raw float3 from svm_magic; Fac is average(color). With the
    addon's identity tint (color1=black, color2=white) the engine must
    reproduce the float3 — the pkg115 residual collapsed it to the average,
    rendering magic greyscale (every channel = 0.535361 at this probe point).
    """
    import astroray
    r = astroray.Renderer()

    val = r.eval_texture_at_3d("magic", {
        "turb_depth": 2,
        "scale": 5.0,
        "distortion": 1.0,
        "color1": [0.0, 0.0, 0.0],
        "color2": [1.0, 1.0, 1.0]
    }, 0.3, 0.4, 0.5)
    # Hand-computed from svm/magic.h at p=(0.3,0.4,0.5), scale=5, depth=2, dist=1:
    #   px,py,pz = fmod(p*5, 2π) = (1.5, 2.0, 2.5)
    #   x = sin(30) = -0.988032; y = cos(-10) = -0.839072; z = -cos(-5) = -0.283662
    #   depth loop (dist=1): y = -cos(x-y+z) = -0.907873; x = cos(x-y-z) = 0.979354
    #   final /= 2·dist → rgb = (0.5-x, 0.5-y, 0.5-z) = (0.010317, 0.953935, 0.641831)
    expected = (0.010317, 0.953935, 0.641831)
    for ch, (got, want) in enumerate(zip(val, expected)):
        assert abs(got - want) < 1e-4, f"channel {ch}: got {got}, want {want}"


# Coordinate-mode tests (items 1a, 1b, 1c from the audit) require a HitRecord or a full render setup.
# The eval_texture_at_3d helper tests the evaluator formulas directly; coordinate-space behavior
# needs integration tests with a real scene. Mark as TODO for the session lead's build+verify phase.
# For now, the addon change (GENERATED default for procedurals) is testable via a stub-bpy test.

def test_addon_procedural_default_generated(monkeypatch):
    """Procedural texture nodes default to GENERATED when Vector is unconnected.

    Audit §4: Blender's procedural nodes have `SocketType::LINK_TEXTURE_GENERATED` as the
    default for the Vector input. The addon translator must pass coord_mode="GENERATED"
    when the Vector socket is unlinked.
    """
    # Reuse the established stub-bpy loader (handles the full bpy surface the
    # addon imports — the previous minimal stub broke on bpy.types.Panel).
    from test_blender_native_nodes import _load_blender_addon

    addon = _load_blender_addon(monkeypatch)
    resolve = addon.CustomRaytracerRenderEngine._resolve_vector_input  # staticmethod

    # Unlinked Vector socket on a procedural node should default to GENERATED.
    coord_mode, scale, offset, rotation, layer = resolve(
        None, default_coord_mode="GENERATED")
    assert coord_mode == "GENERATED", \
        f"Procedural texture default coord_mode should be GENERATED, got {coord_mode}"

    # Unlinked Vector socket on an Image Texture node should default to UV.
    coord_mode_img, _, _, _, _ = resolve(None)
    assert coord_mode_img == "UV", \
        f"Image Texture default coord_mode should be UV, got {coord_mode_img}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
