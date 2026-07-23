"""pkg60 Disney energy-compensation regression tests.

The Cycles reference pass in
``.astroray_plan/docs/disney-energy-compensation-research.md`` found GGX E as
32x32, Eavg as 32, and sheen LTC albedo as the third 32x32 plane. Astroray uses
those tables and integrates the Disney BRDF on a deterministic Halton grid.
Although the package brief says "60-point" while listing 90 combinations, this
test covers all listed roughness/metallic/sheen/clearcoat values at three
outgoing cosines. Measured post-compensation worst case is recorded in the pkg60
commit message and PR body.
"""

import pytest
import numpy as np


ROUGHNESSES = (0.1, 0.3, 0.5, 0.7, 0.9)
METALLICS = (0.0, 1.0)
SHEENS = (0.0, 0.5, 1.0)
CLEARCOATS = (0.0, 0.5, 1.0)
COS_THETA_O = (0.1, 0.5, 0.9)
SAMPLES = 4096


def _create_disney(astroray, roughness, metallic, sheen, clearcoat):
    renderer = astroray.Renderer()
    material_id = renderer.create_material(
        "disney",
        [1.0, 1.0, 1.0],
        {
            "roughness": roughness,
            "metallic": metallic,
            "sheen": sheen,
            "clearcoat": clearcoat,
            "clearcoat_gloss": 0.25,
        },
    )
    return renderer, material_id


# pkg123 quarantined a 15-config grazing-incidence dielectric set here
# (roughness in {0.1, 0.3}, metallic=0, cos_theta_o=0.1) pending the pkg145
# refit; see pkg121-disney-pdf-finding.md "Round 5b" for the pre-fix
# measurements (worst 1.2048 at roughness=0.1, sheen=0, clearcoat=0). pkg145
# (this package) fixed the root cause — Disney 2012's diffuse+specular sum is
# otherwise uncoupled; the diffuse-under-specular layering added to
# `plugins/materials/disney.cpp::eval()` (Cycles `closure_layering_weight` /
# OpenPBR glossy-diffuse albedo scaling) brings the whole 90-config x 3-angle
# grid to <= 1.0 measured at N=65536 (worst 0.999072, roughness=0.3,
# metallic=1.0, cos_theta_o=0.5) — the quarantine is retired and every config
# is back on the single tight 1.02/1.05 gate below.


@pytest.mark.parametrize("roughness", ROUGHNESSES)
@pytest.mark.parametrize("metallic", METALLICS)
@pytest.mark.parametrize("sheen", SHEENS)
@pytest.mark.parametrize("clearcoat", CLEARCOATS)
@pytest.mark.parametrize("cos_theta_o", COS_THETA_O)
def test_disney_directional_hemispherical_reflectance_is_conserved(
    astroray_module, roughness, metallic, sheen, clearcoat, cos_theta_o
):
    renderer, material_id = _create_disney(
        astroray_module, roughness, metallic, sheen, clearcoat
    )
    rgb = renderer.integrate_material_reflectance(material_id, cos_theta_o, SAMPLES)
    worst = max(rgb)

    assert worst <= 1.05, (
        "Disney BRDF reflectance exceeded the loose bug threshold "
        f"({worst:.6f}) for roughness={roughness}, metallic={metallic}, "
        f"sheen={sheen}, clearcoat={clearcoat}, cos_theta_o={cos_theta_o}, "
        f"rgb={rgb}"
    )
    assert worst <= 1.02, (
        "Disney BRDF reflectance exceeded the pkg60 hard gate "
        f"({worst:.6f}) for roughness={roughness}, metallic={metallic}, "
        f"sheen={sheen}, clearcoat={clearcoat}, cos_theta_o={cos_theta_o}, "
        f"rgb={rgb}"
    )


def test_disney_mixed_metallic_sampler_does_not_glow_in_gray_furnace(
    astroray_module,
):
    """Regression for the mixed-lobe sampler PDF.

    A metallic=0.7, roughness=0.05 Disney sphere previously rendered nearly
    white in a 0.45 gray furnace because sample() returned the selected lobe
    PDF while f contained the full Disney eval. The combined PDF keeps the
    sampled path estimator consistent with eval().
    """
    width = height = 64
    renderer = astroray_module.Renderer()
    renderer.set_integrator("path_tracer")
    renderer.set_seed(77)
    renderer.set_background_color([0.45, 0.45, 0.45])
    renderer.setup_camera(
        look_from=[0.0, 0.0, 4.0],
        look_at=[0.0, 0.0, 0.0],
        vup=[0.0, 1.0, 0.0],
        vfov=34.0,
        aspect_ratio=1.0,
        aperture=0.0,
        focus_dist=4.0,
        width=width,
        height=height,
    )
    material_id = renderer.create_material(
        "disney",
        [0.8, 0.6, 0.4],
        {"metallic": 0.7, "roughness": 0.05},
    )
    renderer.add_sphere([0.0, 0.0, 0.0], 0.85, material_id)

    pixels = np.asarray(renderer.render(256, 16, None, False), dtype=np.float32)
    y_coords, x_coords = np.mgrid[0:height, 0:width]
    radius = 19.0
    sphere = (
        (x_coords - (width - 1) * 0.5) ** 2
        + (y_coords - (height - 1) * 0.5) ** 2
    ) <= radius * radius
    luminance = (
        0.2126 * pixels[..., 0]
        + 0.7152 * pixels[..., 1]
        + 0.0722 * pixels[..., 2]
    )

    assert float(np.mean(luminance[sphere])) <= 0.40
    assert float(np.percentile(luminance[sphere], 99.0)) <= 0.40
