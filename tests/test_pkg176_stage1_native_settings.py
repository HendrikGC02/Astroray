"""pkg176 Stage 1 - native-settings resolution (translation layer) unit tests.

Pure Python, no Blender / engine / GPU. Exercises
``blender_addon/native_settings.py`` with a stub ``scene`` mirroring the Blender
datablock shape (``scene.cycles.*`` native props + ``scene.custom_raytracer.*``
deprecated custom duplicates).

Acceptance covered:
  (a) each DIRECT-mapped native prop flows to the resolved setting (correct
      native source + name/unit mapping);
  (b) a set legacy custom prop still wins, with a logged migration note;
  (c) an approximated/dropped setting is NOT read from native (stays custom).
"""

import importlib.util
import pathlib
import sys
import types

import pytest

_ADDON = pathlib.Path(__file__).resolve().parents[1] / "blender_addon"


def _load_native_settings():
    """Load native_settings.py standalone. It does ``from settings_map import
    MAPPING``, so put blender_addon/ on sys.path first (no bpy pulled in)."""
    if str(_ADDON) not in sys.path:
        sys.path.insert(0, str(_ADDON))
    spec = importlib.util.spec_from_file_location(
        "pkg176_native_settings", _ADDON / "native_settings.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ns = _load_native_settings()


# --------------------------------------------------------------------------- #
# stub Blender datablocks
# --------------------------------------------------------------------------- #

class _CustomSettings:
    """Stand-in for scene.custom_raytracer with Blender's is_property_set().
    Only names in ``_set`` count as explicitly authored (a saved-.blend
    override)."""

    def __init__(self, values, explicitly_set=()):
        self.__dict__.update(values)
        object.__setattr__(self, "_set", set(explicitly_set))

    def is_property_set(self, name):
        return name in self._set


def _native_cycles():
    """A cycles datablock carrying every native counterpart, with values
    deliberately distinct from the custom defaults so we can tell them apart."""
    return types.SimpleNamespace(
        samples=64,
        preview_samples=8,
        max_bounces=24,
        diffuse_bounces=5,
        glossy_bounces=6,
        transmission_bounces=7,
        volume_bounces=3,
        transparent_max_bounces=9,       # name mismatch vs custom transparent_bounces
        sample_clamp_direct=2.5,         # name mismatch vs custom clamp_direct
        sample_clamp_indirect=3.5,       # name mismatch vs custom clamp_indirect
        blur_glossy=1.25,                # name mismatch vs custom filter_glossy
        caustics_reflective=False,
        caustics_refractive=False,
        use_denoising=True,
        # native controls that Astroray must NOT read (approximated / dropped):
        use_light_tree=True,
        use_adaptive_sampling=True,
        denoiser='OPTIX',
    )


def _custom_defaults():
    """Custom-duplicate values, all distinct from the native ones above."""
    return {
        "samples": 2, "preview_samples": 1,
        "max_bounces": 10, "diffuse_bounces": 4, "glossy_bounces": 4,
        "transmission_bounces": 12, "volume_bounces": 0, "transparent_bounces": 8,
        "clamp_direct": 0.0, "clamp_indirect": 0.0, "filter_glossy": 0.0,
        "use_reflective_caustics": True, "use_refractive_caustics": True,
        "use_denoising": False,
        # non-direct settings that must stay custom-sourced:
        "light_sampler": 'power',
        "use_adaptive_sampling": False,
        "denoiser_backend": 'auto',
    }


def _scene(cycles, explicitly_set=()):
    settings = _CustomSettings(_custom_defaults(), explicitly_set)
    return types.SimpleNamespace(custom_raytracer=settings, cycles=cycles)


# --------------------------------------------------------------------------- #
# alias table is derived from the Stage-0 contract (source of truth)
# --------------------------------------------------------------------------- #

def test_direct_aliases_match_settings_map():
    """The resolver's alias set must equal exactly the direct-mapped rows in
    settings_map.py that still have a custom_raytracer.* duplicate."""
    import importlib.util as _u
    spec = _u.spec_from_file_location("pkg176_sm", _ADDON / "settings_map.py")
    sm = _u.module_from_spec(spec)
    spec.loader.exec_module(sm)

    expected = {
        (e.cycles_path.split(".")[-1], e.custom_prop.split(".")[-1])
        for e in sm.MAPPING
        if e.status == "direct" and e.custom_prop.startswith("custom_raytracer.")
    }
    assert set(ns.DIRECT_ALIASES) == expected
    assert len(ns.DIRECT_ALIASES) == 14


# --------------------------------------------------------------------------- #
# (a) native props flow to the resolved settings with correct mapping
# --------------------------------------------------------------------------- #

# (native cycles attr, resolved/custom attr, expected native value)
_NATIVE_CASES = [
    ("samples", "samples", 64),
    ("preview_samples", "preview_samples", 8),
    ("max_bounces", "max_bounces", 24),
    ("diffuse_bounces", "diffuse_bounces", 5),
    ("glossy_bounces", "glossy_bounces", 6),
    ("transmission_bounces", "transmission_bounces", 7),
    ("volume_bounces", "volume_bounces", 3),
    ("transparent_max_bounces", "transparent_bounces", 9),
    ("sample_clamp_direct", "clamp_direct", 2.5),
    ("sample_clamp_indirect", "clamp_indirect", 3.5),
    ("blur_glossy", "filter_glossy", 1.25),
    ("caustics_reflective", "use_reflective_caustics", False),
    ("caustics_refractive", "use_refractive_caustics", False),
    ("use_denoising", "use_denoising", True),
]


@pytest.mark.parametrize("native_attr,custom_attr,expected", _NATIVE_CASES)
def test_direct_native_flows_to_resolved(native_attr, custom_attr, expected):
    resolved = ns.resolve_native_settings(_scene(_native_cycles()))
    got = getattr(resolved, custom_attr)
    assert got == expected, (
        f"{custom_attr} should read native scene.cycles.{native_attr}={expected!r}, got {got!r}"
    )


def test_no_migration_note_when_no_legacy_override():
    reports = []
    ns.resolve_native_settings(_scene(_native_cycles()), report=lambda t, m: reports.append(m))
    assert reports == [], "no deprecation note expected when only native props are used"


# --------------------------------------------------------------------------- #
# (b) a set legacy custom prop wins, and logs a migration note
# --------------------------------------------------------------------------- #

def test_legacy_custom_override_wins_and_logs():
    reports = []
    scene = _scene(_native_cycles(), explicitly_set=("max_bounces", "clamp_direct"))
    resolved = ns.resolve_native_settings(scene, report=lambda t, m: reports.append((t, m)))

    # overridden props take the CUSTOM value, not native
    assert resolved.max_bounces == 10
    assert resolved.clamp_direct == 0.0
    # non-overridden direct props still read native
    assert resolved.samples == 64
    assert resolved.glossy_bounces == 6

    # exactly one migration note per overridden alias, tagged WARNING
    assert len(reports) == 2
    joined = " ".join(m for _, m in reports)
    assert "custom_raytracer.max_bounces" in joined
    assert "custom_raytracer.clamp_direct" in joined
    assert all(t == {'WARNING'} for t, _ in reports)


def test_legacy_override_falls_back_to_print_without_report(capsys):
    scene = _scene(_native_cycles(), explicitly_set=("samples",))
    resolved = ns.resolve_native_settings(scene, report=None)
    assert resolved.samples == 2  # custom value wins
    out = capsys.readouterr().out
    assert "custom_raytracer.samples" in out
    assert "deprecated" in out.lower()


# --------------------------------------------------------------------------- #
# (c) approximated / dropped settings are NOT read from native
# --------------------------------------------------------------------------- #

def test_approximated_and_dropped_stay_custom():
    """light_sampler (approximated), use_adaptive_sampling (dropped) and
    denoiser_backend (approximated) must fall through to the custom prop even
    though native counterparts (use_light_tree / use_adaptive_sampling /
    denoiser) exist on scene.cycles."""
    resolved = ns.resolve_native_settings(_scene(_native_cycles()))
    assert resolved.light_sampler == 'power'          # not native use_light_tree
    assert resolved.use_adaptive_sampling is False     # not native True
    assert resolved.denoiser_backend == 'auto'         # not native 'OPTIX'

    # and none of these names are in the resolver's alias set
    aliased_custom = {c for _, c in ns.DIRECT_ALIASES}
    for name in ("light_sampler", "use_adaptive_sampling", "denoiser_backend", "adaptive_threshold"):
        assert name not in aliased_custom


# --------------------------------------------------------------------------- #
# fallback: non-Cycles / stub scene keeps custom values (behaviour unchanged)
# --------------------------------------------------------------------------- #

def test_non_cycles_scene_uses_custom_values_unchanged():
    resolved = ns.resolve_native_settings(_scene(cycles=None))
    assert resolved.samples == 2
    assert resolved.max_bounces == 10
    assert resolved.clamp_direct == 0.0
    assert resolved.light_sampler == 'power'


def test_attribute_write_reaches_underlying_settings():
    scene = _scene(_native_cycles())
    resolved = ns.resolve_native_settings(scene)
    resolved.last_render_stats = "ok"
    assert scene.custom_raytracer.last_render_stats == "ok"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
