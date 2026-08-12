#!/usr/bin/env python
"""pkg186 — the __features__ capability dict must be backend-aware.

`module/blender_module.cpp` advertises `__features__` with `textures`, `volumes`,
`adaptive_sampling`, and `gr_black_holes` all `true` unconditionally, though on the
GPU (CUDA/wavefront) render path all four are CPU-only or absent. The addon
Diagnostics/Preferences panels display that dict verbatim, so they told the user
"textures: yes" while the active GPU backend silently dropped them — the pkg171
silent-lie class applied to the feature dict.

The fix (pkg186) adds a companion `__gpu_features__` dict reporting per-capability
truth for the GPU backend; the panels label any capability that is on in
`__features__` but off in `__gpu_features__` as "CPU only".

These legs are CI-runnable (no GPU required — they inspect the static dict the
module publishes at import) and are the CI backstop for the guard. The headless
Blender panel-render verification is recorded in the PR.
"""

import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")

# The capabilities that are advertised in __features__ but are CPU-only on the
# GPU backend today — the whole point of the guard.
GPU_DROPPED = ["textures", "volumes", "adaptive_sampling", "gr_black_holes"]


def test_gpu_features_dict_exists():
    gpu_feats = getattr(astroray, "__gpu_features__", None)
    assert isinstance(gpu_feats, dict), "__gpu_features__ must be a dict"
    assert gpu_feats, "__gpu_features__ must not be empty"


@pytest.mark.parametrize("cap", GPU_DROPPED)
def test_gpu_dropped_capability_is_false(cap):
    """Each CPU-only capability must be advertised true (built) in __features__
    but false (dropped) in __gpu_features__ — the backend-aware truth."""
    feats = astroray.__features__
    gpu_feats = astroray.__gpu_features__
    assert bool(feats.get(cap, False)) is True, (
        f"{cap} should still be advertised as built in __features__"
    )
    assert cap in gpu_feats, f"{cap} must be present in __gpu_features__"
    assert bool(gpu_feats[cap]) is False, (
        f"{cap} is CPU-only on the GPU backend and must be false in __gpu_features__"
    )


def test_panel_labels_dropped_caps_cpu_only():
    """Reproduce the Diagnostics/Preferences panel derivation: a capability on in
    __features__ but off in __gpu_features__ is surfaced as 'CPU only', not 'On'."""
    feats = astroray.__features__
    gpu_feats = getattr(astroray, "__gpu_features__", {})
    cpu_only = [k for k, v in feats.items()
                if v and k in gpu_feats and not gpu_feats[k]]
    active = [k for k, v in feats.items() if v and k not in cpu_only]
    for cap in GPU_DROPPED:
        assert cap in cpu_only, f"{cap} must be labelled CPU only in the panel"
        assert cap not in active, f"{cap} must not be listed under On"


def test_gpu_supported_capabilities_stay_on():
    """Guardrail: capabilities that DO work on GPU (nee/mis/disney_brdf/sah_bvh/
    spectral_gpu_materials) must not be mislabelled CPU-only."""
    gpu_feats = astroray.__gpu_features__
    for cap in ["nee", "mis", "disney_brdf", "sah_bvh", "spectral_gpu_materials"]:
        assert bool(gpu_feats.get(cap, False)) is True, (
            f"{cap} is GPU-supported and must stay true in __gpu_features__"
        )
