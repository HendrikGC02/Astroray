"""pkg27b: NRC validation stats and visualization smoke tests."""

from pathlib import Path
import sys

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from benchmark_light_transport import run_benchmark  # noqa: E402
from scenes.neural_cache_indirect import add_indirect_scene, make_renderer  # noqa: E402


def test_neural_cache_indirect_scene_default_is_finite_nonblack():
    r = make_renderer(astroray, width=16, height=16)
    add_indirect_scene(r)
    pixels = np.asarray(r.render(1, 4, None, False), dtype=np.float32)
    stats = r.get_integrator_stats()
    assert np.isfinite(pixels).all()
    assert pixels.max() > 0.0
    assert stats.get("buffered_training") == 1.0


def test_light_transport_benchmark_writes_stats_and_graphs(tmp_path):
    rows = run_benchmark(
        tmp_path,
        width=8,
        height=8,
        samples=1,
        reference_samples=1,
        max_depth=3,
        frames=1,
        make_plots=True,
    )
    configs = {row["config"] for row in rows}
    assert {"path_tracer", "auto_default", "neural_cache_fallback", "neural_cache_backend"} <= configs
    assert (tmp_path / "light_transport_stats.json").exists()
    assert (tmp_path / "light_transport_stats.csv").exists()
    assert (tmp_path / "light_transport_time.png").exists()
    assert (tmp_path / "light_transport_mse.png").exists()
    assert (tmp_path / "light_transport_speedup.png").exists()
    assert (tmp_path / "light_transport_nrc_training.png").exists()
    assert all(row["finite"] for row in rows)
