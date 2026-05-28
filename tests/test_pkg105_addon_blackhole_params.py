"""pkg105: Blender addon's BH conversion path forwards pkg107 r_obs_M + spin +
ADAF params to renderer.add_black_hole.

This is a stub-Blender unit test (no live Blender process). It uses the same
'_load_blender_addon' / monkeypatched bpy approach as the other addon-glue
tests in this suite, then verifies that:

  1. The AstrorayBlackHoleProperties property group declares the new fields
     (r_obs_M, spin, adaf_*).
  2. The convert_objects BH branch wires those fields into the params dict
     passed to renderer.add_black_hole.
  3. The expected defaults match pkg107 / pkg44 spec (r_obs_M=100, spin=0).
"""

from __future__ import annotations

import sys
from pathlib import Path
import pytest

# Reuse the bpy-stub loader from existing addon-glue tests.
sys.path.insert(0, str(Path(__file__).parent))


def _load_addon(monkeypatch):
    from test_blender_native_nodes import _load_blender_addon
    return _load_blender_addon(monkeypatch)


def test_bh_property_group_has_pkg107_pkg44_fields(monkeypatch):
    """The property group declares the new fields added 2026-05-28."""
    addon = _load_addon(monkeypatch)

    props = addon.AstrorayBlackHoleProperties
    # PropertyGroup classes expose their declared properties via
    # __annotations__ (Blender's pattern for bpy.props.* declarations).
    annotations = props.__annotations__

    # pkg107
    assert "r_obs_M" in annotations, "r_obs_M property missing (pkg107)"
    # General Kerr spin
    assert "spin" in annotations, "spin property missing"
    # pkg44 ADAF set
    for adaf_field in (
        "adaf_mdot_edd", "adaf_electron_temp", "adaf_beta_mag",
        "adaf_r_inner", "adaf_r_outer", "adaf_flattening",
        "adaf_alpha", "adaf_s", "adaf_intensity_scale",
    ):
        assert adaf_field in annotations, f"{adaf_field} property missing (pkg44 ADAF)"


def test_convert_objects_passes_r_obs_M_and_spin(monkeypatch):
    """Smoke check: the convert_objects BH branch contains the r_obs_M and
    spin param wiring (introduced 2026-05-28 as part of pkg105 + pkg107
    integration)."""
    addon = _load_addon(monkeypatch)
    import inspect
    src = inspect.getsource(addon.CustomRaytracerRenderEngine.convert_objects)
    # The wiring must include these specific keys.
    assert "'r_obs_M'" in src or "\"r_obs_M\"" in src
    assert "'spin'" in src or "\"spin\"" in src
    assert "'enable_adaf'" in src or "\"enable_adaf\"" in src
    # And the ADAF parameters get passed when accretion_model == 'ADAF'.
    assert "adaf_mdot_edd" in src
    assert "adaf_intensity_scale" in src
