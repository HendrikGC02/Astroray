#!/usr/bin/env python
"""#904 regression — light_tracer_caustic must not crash across fresh processes.

The MinGW build crashed ~60% of processes with an access violation in the
photon kd-tree build (an aligned AVX spill to a 16-byte-aligned Win64 stack,
GCC bug 54412). Stack alignment varies per process, so one in-process render
can pass by luck; this renders a small glass-sphere caustic in N fresh
subprocesses and requires every one to exit cleanly.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray  # noqa: F401
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

_TESTS = os.path.dirname(os.path.abspath(__file__))
_RUNS = 8

_CHILD = r"""
import sys
sys.path.insert(0, sys.argv[1])
from runtime_setup import configure_test_imports
configure_test_imports()
import astroray
r = astroray.Renderer()
r.set_background_color([0.0, 0.0, 0.0])
glass = r.create_material("dielectric", [1.0, 1.0, 1.0], {"ior": 1.5})
i = r.scene_object_count()
r.add_sphere([0.0, 0.0, 0.0], 0.6, glass)
r.set_object_caustic_caster(i, True)
r.add_sun_light_dedicated([0.41, -0.91, 0.0], 0.01, {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 1.0)
floor = r.create_material("lambertian", [0.85, 0.85, 0.85], {})
a, b, c, d = [-3, -0.82, -3], [4, -0.82, -3], [4, -0.82, 3], [-3, -0.82, 3]
r.add_triangle(a, b, c, floor)
r.add_triangle(a, c, d, floor)
r.set_integrator("light_tracer_caustic")
r.set_integrator_param("photon_count", 3000000)  # <1M never tripped the crash
r.setup_camera([0.7, 1.1, 3.2], [0.37, -0.82, 0.0], [0.0, 1.0, 0.0],
               42.0, 1.0, 0.0, 3.6, 32, 32)
r.set_seed(17)
r.render(1, 8, None, True)
s = r.get_integrator_stats()
assert s.get("lt_grid_ready") == 1.0, s  # photon map was built (the crash site)
print("OK")
"""


def test_light_tracer_caustic_repeated_processes_do_not_crash():
    if not hasattr(astroray.Renderer(), "add_sun_light_dedicated"):
        pytest.skip("build lacks add_sun_light_dedicated")
    failures = []
    for k in range(_RUNS):
        p = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _CHILD, _TESTS],
                           capture_output=True, text=True, timeout=300)
        if p.returncode != 0 or "OK" not in p.stdout:
            failures.append(f"run {k}: rc={p.returncode} {p.stderr.strip()[:300]}")
    assert not failures, f"{len(failures)}/{_RUNS} processes failed:\n" + "\n".join(failures)
