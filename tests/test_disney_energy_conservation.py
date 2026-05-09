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
