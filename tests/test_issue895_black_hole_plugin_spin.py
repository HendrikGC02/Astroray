"""#895: the black_hole ShapeRegistry plugin must honour `spin` and `r_obs_M`
exactly like the add_black_hole binding (pkg281 added them to the binding only,
so plugin-built scenes silently stayed Schwarzschild at r_obs_M = 100)."""
import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    AVAILABLE = hasattr(astroray.Renderer, "add_shape")
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray add_shape not available")

N = 96
SPIN = 0.94
PARAMS = {"disk_outer": 18.0, "accretion_rate": 0.0, "inclination": 78.0,
          "enable_adaf": False, "r_obs_M": 20.0}


def _mask(path: str, spin: float) -> np.ndarray:
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_background_color([1.0, 1.0, 1.0])
    r.set_seed(17)
    r.set_adaptive_sampling(False)
    # Equatorial observer, where the Kerr shadow is visibly asymmetric.
    r.setup_camera([0.0, 0.0, 12.0], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                   45.0, 1.0, 0.0, 12.0, N, N)
    params = dict(PARAMS, spin=spin)
    if path == "binding":
        r.add_black_hole([0.0, 0.0, 0.0], 4.0e6, 5.0, params)
    else:
        r.add_shape("black_hole", dict(params, position=[0.0, 0.0, 0.0],
                                       mass=4.0e6, influence_radius=5.0))
    lum = np.asarray(r.render(4, 5, None, False), dtype=np.float32).mean(2)
    return lum < 0.5 * float(np.median(lum))


def test_plugin_shadow_matches_binding_at_a094():
    binding = _mask("binding", SPIN)
    plugin = _mask("plugin", SPIN)
    assert binding.sum() > 100, "binding shadow missing"
    iou = (binding & plugin).sum() / max(1, (binding | plugin).sum())
    assert iou > 0.99, f"plugin shadow differs from binding at a={SPIN}: IoU={iou:.4f}"


def test_plugin_spin_changes_shadow():
    # Guard against a vacuous pass: spin must actually move the plugin shadow.
    a0 = _mask("plugin", 0.0)
    a94 = _mask("plugin", SPIN)
    iou = (a0 & a94).sum() / max(1, (a0 | a94).sum())
    assert iou < 0.97, f"plugin shadow ignores spin: IoU(a=0, a={SPIN}) = {iou:.4f}"
