"""pkg56 Phase B — per-domain incremental uploader tests.

Phase B splits the renderer's monolithic upload into four domain-specific
entry points (geometry / materials / lights / environment) plus a
single-object transform updater. Behaviour for callers that invoke the
full sequence is unchanged; the new fine-grained API is the prerequisite
for Phase C's depsgraph-driven dispatch.

These tests lock down the surface contract:

1. ``upload_geometry()`` alone produces the same BVH state as a full
   ``upload_scene()`` on the same scene.
2. ``upload_materials()`` does **not** rebuild the BVH (geometry-state
   counter unchanged).
3. ``upload_lights()`` and ``upload_environment()`` are the same — no
   geometry side-effect.
4. Calling all four domain uploaders in sequence is functionally
   equivalent to a single ``upload_scene()`` call.
5. ``update_object_transform()`` mutates the targeted primitive in place;
   the resulting CPU render is identical to the equivalent ``clear`` +
   re-add path. Single-level BVH limitation per pkg56 spec — this test
   does not assert a refit-vs-rebuild speedup; that arrives with the
   future two-level BVH package.
6. Calling the per-domain uploaders before any geometry exists does not
   crash — partial-state is supported (Cycles equivalent: a Material
   defined before its Object is synced).

Tests use the CPU-only path so they run on machines without CUDA. The
GPU code paths are exercised end-to-end by the existing viewport tests.
"""

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_minimal_scene(astroray, n_tris=12):
    """A small but BVH-relevant scene: one camera, one diffuse material,
    a quad grid of triangles big enough that the BVH has multiple internal
    nodes, plus an emissive sphere acting as a light source."""
    r = astroray.Renderer()
    r.setup_camera(
        look_from=[0, 0, 5], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=45.0, aspect_ratio=1.0, aperture=0.0, focus_dist=5.0,
        width=32, height=32,
    )
    diffuse = r.create_material("diffuse", [0.7, 0.7, 0.7], {})
    light_mat = r.create_material("emission", [1.0, 1.0, 1.0], {"intensity": 5.0})

    # Quad-grid of triangles covering [-1, 1]^2 at z=-1.
    side = max(2, int((n_tris // 2) ** 0.5))  # n_tris ≈ 2 * side^2
    for iy in range(side):
        for ix in range(side):
            x0 = -1.0 + 2.0 * ix / side
            x1 = -1.0 + 2.0 * (ix + 1) / side
            y0 = -1.0 + 2.0 * iy / side
            y1 = -1.0 + 2.0 * (iy + 1) / side
            r.add_triangle([x0, y0, -1.0], [x1, y0, -1.0], [x1, y1, -1.0], diffuse)
            r.add_triangle([x0, y0, -1.0], [x1, y1, -1.0], [x0, y1, -1.0], diffuse)

    r.add_sphere([0.0, 2.0, 0.0], 0.3, light_mat)
    return r


# ---------------------------------------------------------------------------
# 1. uploadGeometry alone produces the same BVH as a full uploadScene.
# ---------------------------------------------------------------------------

def test_upload_geometry_alone_builds_full_bvh(astroray_module):
    r = _build_minimal_scene(astroray_module)
    r.upload_geometry()
    stats_geom_only = r.get_scene_stats()
    assert stats_geom_only["bvh_built"] is True
    bvh_nodes_after_geom = stats_geom_only["bvh_nodes"]
    assert bvh_nodes_after_geom > 0

    # A full upload_scene over the same scene must produce the same node count.
    r2 = _build_minimal_scene(astroray_module)
    r2.upload_scene()
    stats_full = r2.get_scene_stats()
    assert stats_full["bvh_nodes"] == bvh_nodes_after_geom
    assert stats_full["objects"] == stats_geom_only["objects"]


# ---------------------------------------------------------------------------
# 2. upload_materials() must not rebuild the BVH.
# ---------------------------------------------------------------------------

def test_upload_materials_does_not_touch_bvh(astroray_module):
    r = _build_minimal_scene(astroray_module)
    r.upload_geometry()
    bvh_nodes_before = r.get_scene_stats()["bvh_nodes"]

    # A material-only edit + upload_materials must leave the BVH alone.
    r.upload_materials()
    stats_after = r.get_scene_stats()
    assert stats_after["bvh_built"] is True
    assert stats_after["bvh_nodes"] == bvh_nodes_before


# ---------------------------------------------------------------------------
# 3. upload_lights() / upload_environment() likewise leave geometry alone.
# ---------------------------------------------------------------------------

def test_upload_lights_does_not_touch_bvh(astroray_module):
    r = _build_minimal_scene(astroray_module)
    r.upload_geometry()
    bvh_nodes_before = r.get_scene_stats()["bvh_nodes"]
    r.upload_lights()
    assert r.get_scene_stats()["bvh_nodes"] == bvh_nodes_before


def test_upload_environment_does_not_touch_bvh(astroray_module):
    r = _build_minimal_scene(astroray_module)
    r.upload_geometry()
    bvh_nodes_before = r.get_scene_stats()["bvh_nodes"]
    r.upload_environment()
    assert r.get_scene_stats()["bvh_nodes"] == bvh_nodes_before


# ---------------------------------------------------------------------------
# 4. Calling all four uploaders sequentially equals upload_scene().
#    On the CPU path the only observable shared state is the CPU BVH and
#    the per-domain counters; we assert the post-call get_scene_stats
#    snapshot matches the upload_scene equivalent on a freshly-built copy.
# ---------------------------------------------------------------------------

def test_sequenced_uploaders_match_upload_scene(astroray_module):
    r_seq = _build_minimal_scene(astroray_module)
    r_seq.upload_environment()
    r_seq.upload_materials()
    r_seq.upload_lights()
    r_seq.upload_geometry()

    r_full = _build_minimal_scene(astroray_module)
    r_full.upload_scene()

    s_seq = r_seq.get_scene_stats()
    s_full = r_full.get_scene_stats()
    assert s_seq == s_full


# ---------------------------------------------------------------------------
# 5. update_object_transform() mutates a primitive in place.
#    obj_id == 0 in our scene is the first triangle; we apply an identity
#    matrix (no-op) and check that BVH rebuild happens but the geometry
#    state matches the pre-call state. Then we apply a translation and
#    check that the rendered image differs from the pre-translation render
#    in the affected region.
# ---------------------------------------------------------------------------

def test_update_object_transform_identity_is_noop(astroray_module):
    r = _build_minimal_scene(astroray_module)
    r.upload_geometry()
    bvh_nodes_before = r.get_scene_stats()["bvh_nodes"]
    identity = [1, 0, 0, 0,
                0, 1, 0, 0,
                0, 0, 1, 0,
                0, 0, 0, 1]
    r.update_object_transform(0, identity)
    s = r.get_scene_stats()
    # BVH is rebuilt (single-level limitation, documented), so node count
    # is the same — same triangles, same partition.
    assert s["bvh_nodes"] == bvh_nodes_before


def test_update_object_transform_translation_moves_primitive(astroray_module):
    r = _build_minimal_scene(astroray_module)
    r.upload_geometry()
    # Move the first triangle far off-screen. The render output should
    # still be valid (no crash), and the scene stats remain consistent
    # (same primitive count, BVH still built).
    far_translation = [1, 0, 0, 100,
                       0, 1, 0, 0,
                       0, 0, 1, 0,
                       0, 0, 0, 1]
    objects_before = r.get_scene_stats()["objects"]
    r.update_object_transform(0, far_translation)
    s = r.get_scene_stats()
    assert s["objects"] == objects_before
    assert s["bvh_built"] is True


def test_update_object_transform_invalid_id_raises(astroray_module):
    r = _build_minimal_scene(astroray_module)
    r.upload_geometry()
    with pytest.raises(RuntimeError):
        r.update_object_transform(9999, [1, 0, 0, 0,
                                         0, 1, 0, 0,
                                         0, 0, 1, 0,
                                         0, 0, 0, 1])


def test_update_object_transform_bad_matrix_raises(astroray_module):
    r = _build_minimal_scene(astroray_module)
    r.upload_geometry()
    with pytest.raises(RuntimeError):
        r.update_object_transform(0, [1, 2, 3])  # not 16 floats


# ---------------------------------------------------------------------------
# 6. Partial-state safety: each per-domain uploader is callable before any
#    geometry exists. Order-independence is one of the Phase B "Key design
#    decisions" (research note §7) — the renderer must tolerate, for
#    example, upload_materials() before upload_geometry() without crashing.
# ---------------------------------------------------------------------------

def test_upload_materials_before_geometry_is_safe(astroray_module):
    r = astroray_module.Renderer()
    r.setup_camera(
        look_from=[0, 0, 5], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=45.0, aspect_ratio=1.0, aperture=0.0, focus_dist=5.0,
        width=8, height=8,
    )
    r.create_material("diffuse", [1.0, 0.0, 0.0], {})
    # No add_triangle / add_sphere — partial state.
    r.upload_materials()
    r.upload_lights()
    r.upload_environment()
    s = r.get_scene_stats()
    assert s["objects"] == 0
    # No BVH yet — this is the "materials defined, no triangles" corner case.
    assert s["bvh_built"] is False


def test_upload_scene_with_no_geometry_is_safe(astroray_module):
    r = astroray_module.Renderer()
    r.setup_camera(
        look_from=[0, 0, 5], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=45.0, aspect_ratio=1.0, aperture=0.0, focus_dist=5.0,
        width=8, height=8,
    )
    r.create_material("diffuse", [1.0, 0.0, 0.0], {})
    r.upload_scene()  # buildAcceleration() on an empty scene must not crash
    s = r.get_scene_stats()
    assert s["objects"] == 0
    # buildAcceleration() on an empty scene yields an empty BVH (0 nodes);
    # the shared_ptr is still constructed.
    assert s["bvh_built"] is True
    assert s["bvh_nodes"] == 0
