"""#874 - viewport world edits.

(a) The world node-tree identity check in MaterialsCache.diff / WorldCache.diff
compared depsgraph update ids to `scene.world.node_tree` with Python `is`, but
both sides are evaluated copies with a fresh wrapper per access -- the compare
always missed real Blender and either fell through to the MATERIALS fallback
(full sync, but for the wrong reason) or never registered ENVIRONMENT at all.
Fixed the same way #849 fixed `_owning_material`: compare `.original`.

(b) `setup_world()` unconditionally adds a dedicated sky-sun lamp (Sky Texture
bake) with no removal step, so an environment-only replay (`Change.ENVIRONMENT`
in `_dispatch_dirty_domains`) added another sun on every world edit while
never touching the previous one. Fixed by tracking the (start, count) range
`_resync_world()` added and removing it before the next setup_world() call
(same pattern as `_reconcile_lights` for `convert_lights`).

Same stub-bpy / stub-engine pattern as test_issue849_inplace_material_light.py.
"""

import importlib.util
import types
from pathlib import Path


class _BpyId:
    def __init__(self, name="x"):
        self.name = name


class World(_BpyId): pass
class NodeTree(_BpyId): pass
class Scene(_BpyId): pass
class Object(_BpyId): pass
class Material(_BpyId): pass
class Light(_BpyId): pass
class Image(_BpyId): pass
class Mesh(_BpyId): pass


class _Upd:
    def __init__(self, id, *, geometry=False, transform=False, shading=False):
        self.id = id
        self.is_updated_geometry = geometry
        self.is_updated_transform = transform
        self.is_updated_shading = shading


def _load_exporter():
    path = Path(__file__).parent.parent / "blender_addon" / "exporter.py"
    spec = importlib.util.spec_from_file_location("astroray_exporter_874", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeRenderer:
    """Models the sky-sun bookkeeping contract: setup_world() appends to
    `dedicated`; remove_dedicated_lights() deletes a slice."""

    def __init__(self):
        self.dedicated = []
        self.calls = []

    def dedicated_light_count(self):
        return len(self.dedicated)

    def remove_dedicated_lights(self, start, count):
        self.calls.append(("remove_dedicated_lights", start, count))
        del self.dedicated[start:start + count]

    def upload_environment(self): self.calls.append(("upload_environment",))
    def upload_materials(self):   self.calls.append(("upload_materials",))
    def upload_lights(self):      self.calls.append(("upload_lights",))
    def upload_geometry(self):    self.calls.append(("upload_geometry",))


def _setup(world_sun_energy=1.0):
    bpy = types.ModuleType("bpy")
    t = types.ModuleType("bpy.types")
    for k in (World, Light, Material, NodeTree, Image, Object, Mesh, Scene):
        setattr(t, k.__name__, k)
    t.ShaderNodeTree = NodeTree
    bpy.types = t

    world = World("World")
    tree = NodeTree("World Nodetree")
    world.node_tree = tree
    scene = Scene("Scene")
    scene.world = world
    bpy.data = types.SimpleNamespace(materials=[])

    class _Engine:
        _renderer_instance_id_map = {}
        _renderer_instancer_eligible = {}
        _renderer_object_id_map = {}
        _volume_material_map = {}
        _generated_textures_by_material = {}

        def convert_lights(self, depsgraph, renderer):
            pass

        def setup_world(self, scene, renderer):
            # Mirrors the real bug: always appends, never removes.
            renderer.dedicated.append(("sky_sun", world_sun_energy))

        def report(self, *_a, **_k):
            pass

    eng = _Engine()
    r = _FakeRenderer()
    exporter = exp.Exporter(eng, bpy, types.SimpleNamespace(Renderer=_FakeRenderer))
    exporter._viewport_renderer = r
    exporter._viewport_full_synced = True
    exporter._viewport_material_ids = {}
    exporter._viewport_light_range = (0, 0)
    exporter._materials_cache.observe([])
    return exporter, r, scene, tree


exp = _load_exporter()


def _dg(updates, scene):
    return types.SimpleNamespace(updates=list(updates), scene=scene)


# --------------------------------------------------------------------------- #
# (a) identity check
# --------------------------------------------------------------------------- #

def test_world_node_tree_update_recognised_via_original():
    """A ShaderNodeTree update whose id is a DIFFERENT wrapper than
    `scene.world.node_tree`, related only via `.original`, must still be
    classified as an ENVIRONMENT change."""
    exporter, r, scene, tree = _setup()
    evaluated_tree = NodeTree("World Nodetree (evaluated)")
    evaluated_tree.original = tree
    status, changes, _flat, _refit = exporter._classify_depsgraph_domains(
        _dg([_Upd(evaluated_tree)], scene), None)
    assert status == 'dispatched'
    assert changes & exp.Change.ENVIRONMENT
    assert not (changes & exp.Change.MATERIALS)


def test_world_node_tree_update_not_misrouted_to_materials_fallback():
    """Regression for the old `is`-only compare: without `.original` handling
    this update resolved to no owning material and returned FALLBACK (a full
    sync) rather than being excluded from MaterialsCache and picked up by
    WorldCache."""
    exporter, r, scene, tree = _setup()
    evaluated_tree = NodeTree("World Nodetree (evaluated)")
    evaluated_tree.original = tree
    status, changes, _flat, _refit = exporter._classify_depsgraph_domains(
        _dg([_Upd(evaluated_tree)], scene), None)
    assert status != 'fallback'


# --------------------------------------------------------------------------- #
# (b) sky-sun accumulation
# --------------------------------------------------------------------------- #

def test_repeated_world_edits_leave_exactly_one_sky_sun():
    exporter, r, scene, tree = _setup()
    for _ in range(5):
        evaluated_tree = NodeTree("World Nodetree (evaluated)")
        evaluated_tree.original = tree
        res = exporter.apply_depsgraph_updates(
            r, _dg([_Upd(evaluated_tree)], scene), None, lambda *_: None, None)
        assert res == 'dispatched'
    assert r.dedicated == [("sky_sun", 1.0)], (
        f"expected exactly one sky-sun lamp after 5 world edits, got: {r.dedicated}"
    )


def test_world_edit_removes_previous_range_before_resync():
    exporter, r, scene, tree = _setup()
    evaluated_tree = NodeTree("World Nodetree (evaluated)")
    evaluated_tree.original = tree
    exporter.apply_depsgraph_updates(
        r, _dg([_Upd(evaluated_tree)], scene), None, lambda *_: None, None)
    exporter.apply_depsgraph_updates(
        r, _dg([_Upd(evaluated_tree)], scene), None, lambda *_: None, None)
    remove_calls = [c for c in r.calls if c[0] == "remove_dedicated_lights"]
    assert remove_calls, "second world edit must remove the first sky-sun's range"
    assert remove_calls[-1] == ("remove_dedicated_lights", 0, 1)
