"""Typed reads from a parsed .blend → populate an `astroray.Renderer`.

Parity-scope mappings (per pkg76 spec §"Minimum field set" and Cycles parity
reference points). Cycles citations point at files the author read for
*understanding* — we do not mirror code from them; they are GPL-2.0-or-later:
  - intern/cycles/blender/camera.cpp:BlenderSync::sync_camera
  - intern/cycles/blender/light.cpp :BlenderSync::sync_light
  - intern/cycles/blender/shader.cpp:set_principled_*  (Principled BSDF mapping)
  - intern/cycles/blender/object_mesh.cpp (mesh data extraction)

Anything outside the parity-scope subset (volumes, hair, SSS, image textures,
HDRI worlds, panoramic cameras, area-light shape parameters beyond pkg71's
needs) is logged once and skipped. `strict=True` upgrades the log line to a
`BlendImportWarning` raise.
"""

from __future__ import annotations

import math
import struct as _struct
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from .reader import BlendFile, Block
from .sdna import StructDecl


# Blender enum values (public knowledge from RNA / spec — not GPL-fenced).
LA_LOCAL = 0  # point
LA_SUN = 1
LA_SPOT = 2
LA_AREA = 4

CAM_PERSP = 0
CAM_ORTHO = 1
CAM_PANO = 2

OB_MESH = 1
OB_CAMERA = 11
OB_LAMP = 10

# CustomData layer type ids we care about (subset of CustomData_Type from
# DNA_customdata_types.h). Only used as a fallback — primary lookup is by name
# since names are stable across versions.
CD_PROP_INT32 = 11
CD_PROP_FLOAT3 = 47


class BlendImportWarning(Warning):
    """Raised in strict mode when a parity-scope-unsupported feature is hit."""


@dataclass
class _ImportContext:
    blend: BlendFile
    renderer: Any
    strict: bool
    on_warning: Callable[[str], None]
    # Map (block_old, "Material") → mat_id assigned by the renderer. We keep
    # one mat_id per Blender material so per-face material indices route right.
    material_ids: dict[int, int] = None  # filled in build()

    def warn(self, msg: str) -> None:
        if self.strict:
            raise BlendImportWarning(msg)
        self.on_warning(msg)


# ---------------------------------------------------------------------------
# Public entry — see blend_to_astroray.py for the wrapper.

def build_scene(blend: BlendFile, renderer: Any, *, strict: bool = False,
                on_warning: Callable[[str], None] | None = None) -> dict:
    """Populate *renderer* from *blend*. Returns a stats dict with camera intrinsics."""
    on_warning = on_warning or (lambda m: print(f"[blend_import] {m}"))
    ctx = _ImportContext(blend=blend, renderer=renderer, strict=strict,
                         on_warning=on_warning, material_ids={})

    # 1. World — set background colour first so it's there before triangles.
    _import_world(ctx)

    # 2. Materials — pre-create so per-face indices have something to point at.
    _import_all_materials(ctx)

    # 3. Camera — pick the active scene's camera.
    cam_intrinsics = _import_active_camera(ctx)

    # 4. Objects — meshes (triangles) + lights.
    n_obj, n_tri, n_light = _import_objects(ctx)

    return {
        "objects": n_obj,
        "triangles": n_tri,
        "lights": n_light,
        "materials": len(ctx.material_ids),
        "cam_intrinsics": cam_intrinsics,
    }


# ---------------------------------------------------------------------------
# Active scene + camera

def _active_scene_block(blend: BlendFile) -> Block | None:
    """Resolve FileGlobal.curscene → the SC block."""
    glob = blend.by_code.get("GLOB")
    if not glob:
        return None
    fg = blend.sdna.struct_for("FileGlobal")
    if fg is None:
        return None
    ptr = blend.read_pointer(glob[0], fg, "curscene")
    return blend.follow(ptr)


def _import_active_camera(ctx: _ImportContext) -> dict | None:
    """Import active camera, return intrinsics dict or None if no camera."""
    blend = ctx.blend
    scene = _active_scene_block(blend)
    if scene is None:
        ctx.warn("no active scene found (FileGlobal.curscene)")
        return None
    sc_struct = blend.struct_of(scene)
    cam_obj_ptr = blend.read_pointer(scene, sc_struct, "camera")
    cam_obj_blk = blend.follow(cam_obj_ptr)
    if cam_obj_blk is None:
        ctx.warn("scene has no camera object")
        return None
    ob_struct = blend.struct_of(cam_obj_blk)
    cam_data_ptr = blend.read_pointer(cam_obj_blk, ob_struct, "data")
    cam_data_blk = blend.follow(cam_data_ptr)
    if cam_data_blk is None or cam_data_blk.code != "CA":
        ctx.warn("camera object data does not point at a CA block")
        return None
    return _emit_camera(ctx, cam_obj_blk, cam_data_blk)


def _emit_camera(ctx: _ImportContext, ob_blk: Block, cam_blk: Block) -> dict | None:
    """Decode camera intrinsics + extrinsics, return as dict for setup_camera.

    Citation: matches the field set in
    intern/cycles/blender/camera.cpp:BlenderSync::sync_camera (read for
    understanding only — not mirrored).
    """
    blend = ctx.blend
    cam_struct = blend.struct_of(cam_blk)
    cam_type = blend.read_int(cam_blk, cam_struct, "type")
    if cam_type == CAM_PANO:
        ctx.warn("camera is panoramic — falling back to perspective")
    lens = blend.read_float(cam_blk, cam_struct, "lens")[0]
    sensor_x = blend.read_float(cam_blk, cam_struct, "sensor_x")[0]
    sensor_y = blend.read_float(cam_blk, cam_struct, "sensor_y")[0]
    clipsta = blend.read_float(cam_blk, cam_struct, "clipsta")[0]
    clipend = blend.read_float(cam_blk, cam_struct, "clipend")[0]
    sensor_fit = blend.read_int(cam_blk, cam_struct, "sensor_fit")

    # Object → world matrix. We compose from loc/rot/size because Blender 4.0+
    # does not persist obmat[16] in the file — it is computed at runtime from
    # parent + transform.
    eye, target, up = _object_camera_basis(ctx, ob_blk)

    # Vertical FOV in degrees from focal length + sensor (Cycles uses the
    # AUTO sensor_fit rule: aspect chooses which sensor dimension drives FOV).
    sensor = sensor_y if sensor_fit == 2 else sensor_x  # 0=AUTO,1=H,2=V
    if sensor <= 0.0 or lens <= 0.0:
        ctx.warn("camera has invalid lens/sensor — skipping")
        return None
    # Convert to vertical FOV. For sensor_fit=AUTO/HORIZONTAL, sensor_x drives
    # horizontal FOV; we approximate vfov = 2*atan(sensor_y/(2*lens)) using
    # sensor_y for accuracy. The harness will override aspect explicitly.
    vfov_deg = 2.0 * math.degrees(math.atan(sensor_y / (2.0 * lens)))
    aspect = sensor_x / sensor_y if sensor_y > 0 else 1.0

    # Return intrinsics for the caller to pass to setup_camera once resolution
    # is known (signature from scripts/run_parity.py: eye, target, up, fov,
    # aspect, near, far, w, h).
    return {
        "eye": eye, "target": target, "up": up,
        "fov": vfov_deg, "aspect": aspect,
        "near": clipsta, "far": clipend,
    }


def _object_local_matrix(ctx: _ImportContext, ob_blk: Block) -> list[list[float]]:
    """Compose 4×4 world matrix from Object.loc + (rot|quat) + size + parentinv.

    Blender's `rotmode` field (DNA `Object.rotmode`):
      0  = QUATERNION (use quat[4])
      1  = XYZ Euler  (use rot[3])
      2..6 = other Euler orders (XZY, YXZ, YZX, ZXY, ZYX) — parity scope
             still composes from rot[3] but warns; the four target scenes
             (Classroom, Junkshop, BMW27) ship Euler XYZ.
      −1 = AXIS_ANGLE (out of parity scope; warn and use Euler).
    """
    blend = ctx.blend
    ob_struct = blend.struct_of(ob_blk)
    loc = blend.read_float(ob_blk, ob_struct, "loc", count=3)
    size = blend.read_float(ob_blk, ob_struct, "size", count=3)
    rotmode = blend.read_int(ob_blk, ob_struct, "rotmode")
    parentinv = blend.read_float(ob_blk, ob_struct, "parentinv", count=16)

    if rotmode == 0:
        quat = blend.read_float(ob_blk, ob_struct, "quat", count=4)
        M = _compose_trs_quat(loc, quat, size)
    else:
        rot = blend.read_float(ob_blk, ob_struct, "rot", count=3)
        if rotmode != 1:
            ctx.warn(f"object rotmode={rotmode} not XYZ Euler — using XYZ as approximation")
        M = _compose_trs(loc, rot, size)

    # parentinv is stored column-major like all Blender matrices — apply on
    # the left as Cycles does.
    P = _matrix_unflatten(parentinv)
    return _matmul(P, M)


def _object_camera_basis(ctx: _ImportContext,
                         ob_blk: Block) -> tuple[list[float], list[float], list[float]]:
    """Return (eye, target, up) for an object treated as a camera.

    Blender cameras look down their local -Z, with +Y up. The Astroray
    Renderer.setup_camera takes (eye, target, up) so we project a forward
    point along -Z and an up vector along +Y, transformed by the world matrix.
    """
    M = _object_local_matrix(ctx, ob_blk)
    # eye = M * (0,0,0)  → translation column
    eye = [M[0][3], M[1][3], M[2][3]]
    # forward = M * (0,0,-1) − eye → 3rd column negated
    fwd = [-M[0][2], -M[1][2], -M[2][2]]
    target = [eye[i] + fwd[i] for i in range(3)]
    # up = M * (0,1,0) → 2nd column
    up = [M[0][1], M[1][1], M[2][1]]
    return eye, target, up


# ---------------------------------------------------------------------------
# Materials

def _import_all_materials(ctx: _ImportContext) -> None:
    """Walk every MA block, register a renderer material, and remember the id
    keyed by the Material block's old pointer."""
    blend = ctx.blend
    for blk in blend.by_code.get("MA", []):
        rgb = _material_base_color(ctx, blk)
        params = {
            "metallic": _material_scalar(ctx, blk, "metallic", default=0.0),
            "roughness": _material_scalar(ctx, blk, "roughness", default=0.5),
        }
        try:
            mat_id = ctx.renderer.create_material("disney", rgb, params)
        except Exception:
            # Some renderer builds don't have 'disney' — fall back to lambertian.
            mat_id = ctx.renderer.create_material("lambertian", rgb, {})
        ctx.material_ids[blk.old] = mat_id


def _material_scalar(ctx: _ImportContext, mat_blk: Block, name: str,
                     *, default: float) -> float:
    blend = ctx.blend
    s = blend.struct_of(mat_blk)
    fd = s.by_name.get(name)
    if fd is None:
        return default
    return float(blend.read_float(mat_blk, s, name)[0])


def _material_base_color(ctx: _ImportContext, mat_blk: Block) -> list[float]:
    """Resolve a parity-scope base colour for a Material.

    Order matches Cycles' set_principled_bsdf path
    (intern/cycles/blender/shader.cpp:set_principled_*):
      1. If Material.use_nodes and the nodetree has a Principled / Diffuse BSDF,
         take its Base Color / Color socket default value.
      2. Otherwise fall back to the legacy Material.r/g/b.
    """
    blend = ctx.blend
    s = blend.struct_of(mat_blk)
    use_nodes = bool(s.by_name.get("use_nodes")) and blend.read_int(mat_blk, s, "use_nodes")
    if use_nodes:
        nt_ptr = blend.read_pointer(mat_blk, s, "nodetree")
        nt_blk = blend.follow(nt_ptr)
        if nt_blk is not None:
            rgb = _nodetree_principled_or_diffuse_color(ctx, nt_blk)
            if rgb is not None:
                return rgb
            ctx.warn(f"material {mat_blk.old:x} has nodes but no Principled/Diffuse BSDF — "
                     f"falling back to legacy r/g/b")
    return [
        blend.read_float(mat_blk, s, "r")[0],
        blend.read_float(mat_blk, s, "g")[0],
        blend.read_float(mat_blk, s, "b")[0],
    ]


# ---------------------------------------------------------------------------
# Node-tree walk (only deep enough for parity scope — Base Color / Background)

_PRINCIPLED_IDS = ("ShaderNodeBsdfPrincipled",)
_DIFFUSE_IDS = ("ShaderNodeBsdfDiffuse",)
_BACKGROUND_IDS = ("ShaderNodeBackground",)


def _iter_listbase(blend: BlendFile, blk: Block, struct: StructDecl,
                   field: str) -> Iterable[Block]:
    """Walk a ListBase {first,*; last,*;} embedded at *field* of *blk*.

    The ListBase struct's first field is `*first`; the linked entries thread
    through their own first field `*next`.
    """
    fd = struct.by_name[field]
    base = blk.payload_offset + fd.offset
    fmt = blend.header.endian_char + blend.header.ptr_fmt
    (first_ptr,) = _struct.unpack_from(fmt, blend.buf, base)
    yield from blend.walk_listbase(first_ptr)


def _nodetree_principled_or_diffuse_color(ctx: _ImportContext,
                                          nt_blk: Block) -> list[float] | None:
    blend = ctx.blend
    nt_struct = blend.struct_of(nt_blk)
    bnode_struct = blend.sdna.struct_for("bNode")
    if bnode_struct is None:
        return None
    for node_blk in _iter_listbase(blend, nt_blk, nt_struct, "nodes"):
        idname = blend.read_string(node_blk, bnode_struct, "idname")
        if idname in _PRINCIPLED_IDS:
            rgb = _node_socket_default_rgba(ctx, node_blk, "Base Color")
            if rgb is not None:
                return rgb
        elif idname in _DIFFUSE_IDS:
            rgb = _node_socket_default_rgba(ctx, node_blk, "Color")
            if rgb is not None:
                return rgb
    return None


def _node_socket_default_rgba(ctx: _ImportContext, node_blk: Block,
                              socket_name: str) -> list[float] | None:
    """Find the input socket whose name matches and read its default RGBA."""
    blend = ctx.blend
    bnode_struct = blend.struct_of(node_blk)
    sock_struct = blend.sdna.struct_for("bNodeSocket")
    rgba_struct = blend.sdna.struct_for("bNodeSocketValueRGBA")
    if sock_struct is None or rgba_struct is None:
        return None
    for sock_blk in _iter_listbase(blend, node_blk, bnode_struct, "inputs"):
        name = blend.read_string(sock_blk, sock_struct, "name")
        if name != socket_name:
            continue
        dv_ptr = blend.read_pointer(sock_blk, sock_struct, "default_value")
        dv_blk = blend.follow(dv_ptr)
        if dv_blk is None:
            return None
        # bNodeSocketValueRGBA is `float value[4]`. The block payload is
        # exactly 16 bytes (or count×16), and field offset 0.
        rgba = list(_struct.unpack_from(blend.header.endian_char + "ffff",
                                        blend.buf, dv_blk.payload_offset))
        return rgba[:3]
    return None


def _node_socket_default_float(ctx: _ImportContext, node_blk: Block,
                               socket_name: str) -> float | None:
    blend = ctx.blend
    bnode_struct = blend.struct_of(node_blk)
    sock_struct = blend.sdna.struct_for("bNodeSocket")
    if sock_struct is None:
        return None
    for sock_blk in _iter_listbase(blend, node_blk, bnode_struct, "inputs"):
        name = blend.read_string(sock_blk, sock_struct, "name")
        if name != socket_name:
            continue
        dv_ptr = blend.read_pointer(sock_blk, sock_struct, "default_value")
        dv_blk = blend.follow(dv_ptr)
        if dv_blk is None:
            return None
        # bNodeSocketValueFloat: int subtype, float value, ...
        (val,) = _struct.unpack_from(blend.header.endian_char + "f",
                                     blend.buf, dv_blk.payload_offset + 4)
        return val
    return None


# ---------------------------------------------------------------------------
# World

def _import_world(ctx: _ImportContext) -> None:
    blend = ctx.blend
    scene = _active_scene_block(blend)
    if scene is None:
        return
    sc_struct = blend.struct_of(scene)
    world_ptr = blend.read_pointer(scene, sc_struct, "world")
    world_blk = blend.follow(world_ptr)
    if world_blk is None:
        return

    w_struct = blend.struct_of(world_blk)
    use_nodes = blend.read_int(world_blk, w_struct, "use_nodes") if w_struct.by_name.get("use_nodes") else 1
    color = [0.0, 0.0, 0.0]
    strength = 1.0
    if use_nodes:
        nt_ptr = blend.read_pointer(world_blk, w_struct, "nodetree")
        nt_blk = blend.follow(nt_ptr)
        if nt_blk is not None:
            bg = _world_background_node(ctx, nt_blk)
            if bg is not None:
                rgb = _node_socket_default_rgba(ctx, bg, "Color")
                s   = _node_socket_default_float(ctx, bg, "Strength")
                if rgb is not None:
                    color = rgb
                if s is not None:
                    strength = s
            else:
                ctx.warn("world.nodetree has no Background node — using legacy horr/horg/horb")
                color = [
                    blend.read_float(world_blk, w_struct, "horr")[0],
                    blend.read_float(world_blk, w_struct, "horg")[0],
                    blend.read_float(world_blk, w_struct, "horb")[0],
                ]
    else:
        color = [
            blend.read_float(world_blk, w_struct, "horr")[0],
            blend.read_float(world_blk, w_struct, "horg")[0],
            blend.read_float(world_blk, w_struct, "horb")[0],
        ]

    scaled = [c * strength for c in color]
    if hasattr(ctx.renderer, "set_background_color"):
        ctx.renderer.set_background_color(scaled)


def _world_background_node(ctx: _ImportContext, nt_blk: Block) -> Block | None:
    blend = ctx.blend
    nt_struct = blend.struct_of(nt_blk)
    bnode_struct = blend.sdna.struct_for("bNode")
    if bnode_struct is None:
        return None
    for node_blk in _iter_listbase(blend, nt_blk, nt_struct, "nodes"):
        if blend.read_string(node_blk, bnode_struct, "idname") in _BACKGROUND_IDS:
            return node_blk
    return None


# ---------------------------------------------------------------------------
# Object dispatch

def _import_objects(ctx: _ImportContext) -> tuple[int, int, int]:
    """Walk every OB block, dispatch by type. Returns (n_obj, n_tri, n_light)."""
    blend = ctx.blend
    n_obj = n_tri = n_light = 0
    for ob_blk in blend.by_code.get("OB", []):
        ob_struct = blend.struct_of(ob_blk)
        ob_type = blend.read_int(ob_blk, ob_struct, "type")
        data_ptr = blend.read_pointer(ob_blk, ob_struct, "data")
        data_blk = blend.follow(data_ptr)
        n_obj += 1
        if ob_type == OB_MESH and data_blk is not None and data_blk.code == "ME":
            n_tri += _emit_mesh(ctx, ob_blk, data_blk)
        elif ob_type == OB_LAMP and data_blk is not None and data_blk.code == "LA":
            if _emit_lamp(ctx, ob_blk, data_blk):
                n_light += 1
        # Cameras handled in _import_active_camera; everything else ignored.
    return n_obj, n_tri, n_light


# ---------------------------------------------------------------------------
# Lamp (Light)

def _emit_lamp(ctx: _ImportContext, ob_blk: Block, la_blk: Block) -> bool:
    """Emit a parity-scope light to the renderer.

    Citation (read for understanding): Cycles maps Lamp.type → its own light
    primitives in intern/cycles/blender/light.cpp. We map only POINT, SUN,
    SPOT, AREA — anything else logs and skips.
    """
    blend = ctx.blend
    la_struct = blend.struct_of(la_blk)
    la_type = blend.read_int(la_blk, la_struct, "type")
    rgb = [
        blend.read_float(la_blk, la_struct, "r")[0],
        blend.read_float(la_blk, la_struct, "g")[0],
        blend.read_float(la_blk, la_struct, "b")[0],
    ]
    energy = blend.read_float(la_blk, la_struct, "energy")[0]
    M = _object_local_matrix(ctx, ob_blk)
    eye = [M[0][3], M[1][3], M[2][3]]
    fwd = [-M[0][2], -M[1][2], -M[2][2]]

    mat_id = ctx.renderer.create_material("light", rgb, {"intensity": float(energy)})

    if la_type == LA_LOCAL:
        if hasattr(ctx.renderer, "add_sphere"):
            ctx.renderer.add_sphere(eye, 0.1, mat_id, fwd, "", 0, 0)
            return True
    elif la_type == LA_SUN:
        if hasattr(ctx.renderer, "add_sun_light"):
            ctx.renderer.add_sun_light(fwd, 0.0, mat_id, 0, 0)
            return True
    elif la_type == LA_SPOT:
        if hasattr(ctx.renderer, "add_spot_light"):
            spotsize = blend.read_float(la_blk, la_struct, "spotsize")[0]
            spotblend = blend.read_float(la_blk, la_struct, "spotblend")[0]
            ctx.renderer.add_spot_light(eye, fwd, 0.0, mat_id,
                                        spotsize, spotblend, "", 0, 0)
            return True
    elif la_type == LA_AREA:
        if hasattr(ctx.renderer, "add_area_light"):
            size_x = blend.read_float(la_blk, la_struct, "area_size")[0]
            size_y = blend.read_float(la_blk, la_struct, "area_sizey")[0] or size_x
            ux = [M[0][0], M[1][0], M[2][0]]
            uy = [M[0][1], M[1][1], M[2][1]]
            ctx.renderer.add_area_light(eye, ux, uy, size_x, size_y,
                                        "RECTANGLE", mat_id, 1.0, 0, 0)
            return True
    ctx.warn(f"unsupported lamp type={la_type} — skipped")
    return False


# ---------------------------------------------------------------------------
# Mesh — modern attribute-based storage with a legacy MVert fallback.

def _emit_mesh(ctx: _ImportContext, ob_blk: Block, me_blk: Block) -> int:
    """Push the mesh's triangulated faces to the renderer. Returns tri count."""
    blend = ctx.blend
    me_struct = blend.struct_of(me_blk)
    totvert = blend.read_int(me_blk, me_struct, "totvert")
    totpoly = blend.read_int(me_blk, me_struct, "totpoly") if me_struct.by_name.get("totpoly") else 0
    totloop = blend.read_int(me_blk, me_struct, "totloop") if me_struct.by_name.get("totloop") else 0
    if totvert == 0 or totpoly == 0 or totloop == 0:
        ctx.warn(f"mesh {me_blk.old:x} has no geometry (totvert={totvert}, "
                 f"totpoly={totpoly}, totloop={totloop}) — skipped")
        return 0

    positions = _mesh_positions(ctx, me_blk, totvert)
    if positions is None:
        ctx.warn(f"mesh {me_blk.old:x} has no 'position' attribute — skipped")
        return 0
    corner_verts = _mesh_corner_verts(ctx, me_blk, totloop)
    if corner_verts is None:
        ctx.warn(f"mesh {me_blk.old:x} has no '.corner_vert' attribute — skipped")
        return 0
    face_offsets = _mesh_face_offsets(ctx, me_blk, totpoly)
    if face_offsets is None:
        ctx.warn(f"mesh {me_blk.old:x} has no 'poly_offset_indices' — skipped")
        return 0
    material_index = _mesh_material_index(ctx, me_blk, totpoly) or [0] * totpoly

    # Object world matrix and per-slot material map.
    M = _object_local_matrix(ctx, ob_blk)
    slot_to_id = _object_material_slots(ctx, ob_blk)

    def xform(v: tuple[float, float, float]) -> list[float]:
        x, y, z = v
        return [
            M[0][0]*x + M[0][1]*y + M[0][2]*z + M[0][3],
            M[1][0]*x + M[1][1]*y + M[1][2]*z + M[1][3],
            M[2][0]*x + M[2][1]*y + M[2][2]*z + M[2][3],
        ]

    n_tri = 0
    for face_idx in range(totpoly):
        start = face_offsets[face_idx]
        end = face_offsets[face_idx + 1]
        if end - start < 3:
            continue
        mat_slot = material_index[face_idx] if face_idx < len(material_index) else 0
        mat_id = slot_to_id.get(mat_slot, slot_to_id.get(0, 0))
        # Triangle fan: (start, start+i, start+i+1) for i in [1..n-1).
        v0 = xform(positions[corner_verts[start]])
        for i in range(1, end - start - 1):
            v1 = xform(positions[corner_verts[start + i]])
            v2 = xform(positions[corner_verts[start + i + 1]])
            ctx.renderer.add_triangle(v0, v1, v2, mat_id)
            n_tri += 1
    return n_tri


def _object_material_slots(ctx: _ImportContext, ob_blk: Block) -> dict[int, int]:
    """Map per-face material_index → renderer mat_id via the Object.mat array
    (a heap-allocated array of Material*). Length is Object.totcol."""
    blend = ctx.blend
    ob_struct = blend.struct_of(ob_blk)
    totcol = blend.read_int(ob_blk, ob_struct, "totcol") if ob_struct.by_name.get("totcol") else 0
    mat_arr_ptr = blend.read_pointer(ob_blk, ob_struct, "mat") if ob_struct.by_name.get("mat") else 0
    slots: dict[int, int] = {}
    if mat_arr_ptr == 0 or totcol == 0:
        return slots
    arr_blk = blend.follow(mat_arr_ptr)
    if arr_blk is None:
        return slots
    fmt = blend.header.endian_char + blend.header.ptr_fmt
    for i in range(totcol):
        (ptr,) = _struct.unpack_from(fmt, blend.buf,
                                     arr_blk.payload_offset + i * blend.header.pointer_size)
        slots[i] = ctx.material_ids.get(ptr, 0)
    return slots


# ---- mesh attribute readers -------------------------------------------------
#
# Blender 4.0+ stores mesh attributes in two parallel systems:
#
#   1. The new ``Mesh.attribute_storage`` (struct ``AttributeStorage``) — an
#      array of ``Attribute`` records, each pointing at an
#      ``AttributeArray`` block which itself points at the raw values. This
#      is the authoritative store from 4.0 onward.
#   2. The legacy CustomData ``vdata``/``edata``/``pdata``/``ldata`` —
#      kept as compatibility but written empty in 4.0+ files.
#
# We try the new system first, fall back to CustomData, then to the legacy
# pre-3.6 ``mvert``/``mloop``/``mpoly`` arrays as a last resort.

def _attribute_data_block(blend: BlendFile, me_blk: Block,
                          name_match: str) -> Block | None:
    """Find an attribute by name in Mesh.attribute_storage and return the
    DATA block holding its raw values (after the AttributeArray indirection).

    Layout:
      Mesh.attribute_storage = AttributeStorage{*dna_attributes; int num; ...}
      *dna_attributes → DATA block of [num] × Attribute{*name; data_type;
          domain; storage_type; *data}
      Attribute.data → DATA block of AttributeArray{*data; *sharing_info;
          int64 size; int8 is_single}
      AttributeArray.data → DATA block holding raw scalar/vector values.
    """
    me_struct = blend.struct_of(me_blk)
    fd = me_struct.by_name.get("attribute_storage")
    if fd is None:
        return None
    ast = blend.sdna.struct_for("AttributeStorage")
    attr_struct = blend.sdna.struct_for("Attribute")
    arr_struct = blend.sdna.struct_for("AttributeArray")
    if ast is None or attr_struct is None or arr_struct is None:
        return None
    base = me_blk.payload_offset + fd.offset
    fmt_q = blend.header.endian_char + blend.header.ptr_fmt
    end_ = blend.header.endian_char
    (attrs_ptr,) = _struct.unpack_from(fmt_q, blend.buf,
                                       base + ast.by_name["dna_attributes"].offset)
    (n_attrs,) = _struct.unpack_from(end_ + "i", blend.buf,
                                     base + ast.by_name["dna_attributes_num"].offset)
    if attrs_ptr == 0 or n_attrs == 0:
        return None
    attrs_blk = blend.follow(attrs_ptr)
    if attrs_blk is None:
        return None
    name_off = attr_struct.by_name["name"].offset
    data_off = attr_struct.by_name["data"].offset
    arr_data_off = arr_struct.by_name["data"].offset
    for i in range(n_attrs):
        b = attrs_blk.payload_offset + i * attr_struct.size
        (name_ptr,) = _struct.unpack_from(fmt_q, blend.buf, b + name_off)
        name_blk = blend.follow(name_ptr)
        if name_blk is None:
            continue
        nm = bytes(blend.buf[name_blk.payload_offset:
                             name_blk.payload_offset + name_blk.size]
                   ).split(b"\x00", 1)[0].decode("utf-8", errors="replace")
        if nm != name_match:
            continue
        (arr_ptr,) = _struct.unpack_from(fmt_q, blend.buf, b + data_off)
        arr_blk = blend.follow(arr_ptr)
        if arr_blk is None:
            return None
        (raw_ptr,) = _struct.unpack_from(fmt_q, blend.buf,
                                         arr_blk.payload_offset + arr_data_off)
        return blend.follow(raw_ptr)
    return None


def _customdata_layer(blend: BlendFile, me_blk: Block, customdata_field: str,
                      *, name_match: str | None = None,
                      type_match: int | None = None) -> Block | None:
    """Return the DATA block for a legacy CustomData layer matching by name
    (preferred) or type, or None if absent."""
    me_struct = blend.struct_of(me_blk)
    cd_field = me_struct.by_name.get(customdata_field)
    if cd_field is None:
        return None
    cd_struct = blend.sdna.struct_for("CustomData")
    layer_struct = blend.sdna.struct_for("CustomDataLayer")
    if cd_struct is None or layer_struct is None:
        return None
    # CustomData starts at me_blk.payload_offset + cd_field.offset.
    cd_base = me_blk.payload_offset + cd_field.offset
    fmt_q = blend.header.endian_char + blend.header.ptr_fmt
    (layers_ptr,) = _struct.unpack_from(fmt_q, blend.buf, cd_base + cd_struct.by_name["layers"].offset)
    (totlayer,) = _struct.unpack_from(blend.header.endian_char + "i", blend.buf,
                                      cd_base + cd_struct.by_name["totlayer"].offset)
    if layers_ptr == 0 or totlayer == 0:
        return None
    layers_blk = blend.follow(layers_ptr)
    if layers_blk is None:
        return None
    layer_size = layer_struct.size
    name_offset = layer_struct.by_name["name"].offset
    type_offset = layer_struct.by_name["type"].offset
    data_offset = layer_struct.by_name["data"].offset
    for i in range(totlayer):
        base = layers_blk.payload_offset + i * layer_size
        ltype = _struct.unpack_from(blend.header.endian_char + "i", blend.buf, base + type_offset)[0]
        lname = bytes(blend.buf[base + name_offset:base + name_offset + 64]).split(b"\x00", 1)[0].decode("utf-8", errors="replace")
        if name_match is not None and lname != name_match:
            continue
        if type_match is not None and ltype != type_match:
            continue
        (data_ptr,) = _struct.unpack_from(fmt_q, blend.buf, base + data_offset)
        return blend.follow(data_ptr)
    return None


def _mesh_positions(ctx, me_blk: Block, totvert: int) -> list[tuple[float, float, float]] | None:
    blend = ctx.blend
    blk = _attribute_data_block(blend, me_blk, "position")
    if blk is None:
        blk = _customdata_layer(blend, me_blk, "vdata", name_match="position",
                                type_match=CD_PROP_FLOAT3)
    if blk is None:
        # Legacy fallback: MVert array.
        me_struct = blend.struct_of(me_blk)
        if me_struct.by_name.get("mvert") is not None:
            mvert_ptr = blend.read_pointer(me_blk, me_struct, "mvert")
            mvert_blk = blend.follow(mvert_ptr)
            if mvert_blk is not None:
                mvert_struct = blend.sdna.struct_for("MVert")
                if mvert_struct is not None and mvert_struct.by_name.get("co"):
                    co_off = mvert_struct.by_name["co"].offset
                    positions = []
                    for i in range(totvert):
                        base = mvert_blk.payload_offset + i * mvert_struct.size + co_off
                        positions.append(_struct.unpack_from(blend.header.endian_char + "fff",
                                                             blend.buf, base))
                    return positions
        return None
    positions: list[tuple[float, float, float]] = []
    fmt = blend.header.endian_char + "fff"
    for i in range(totvert):
        positions.append(_struct.unpack_from(fmt, blend.buf, blk.payload_offset + i * 12))
    return positions


def _mesh_corner_verts(ctx, me_blk: Block, totloop: int) -> list[int] | None:
    blend = ctx.blend
    blk = _attribute_data_block(blend, me_blk, ".corner_vert")
    if blk is None:
        blk = _customdata_layer(blend, me_blk, "ldata", name_match=".corner_vert",
                                type_match=CD_PROP_INT32)
    if blk is None:
        # Legacy fallback: MLoop.v.
        me_struct = blend.struct_of(me_blk)
        if me_struct.by_name.get("mloop") is not None:
            mloop_ptr = blend.read_pointer(me_blk, me_struct, "mloop")
            mloop_blk = blend.follow(mloop_ptr)
            if mloop_blk is not None:
                mloop_struct = blend.sdna.struct_for("MLoop")
                if mloop_struct is not None and mloop_struct.by_name.get("v"):
                    v_off = mloop_struct.by_name["v"].offset
                    cv = []
                    for i in range(totloop):
                        base = mloop_blk.payload_offset + i * mloop_struct.size + v_off
                        cv.append(_struct.unpack_from(blend.header.endian_char + "I",
                                                      blend.buf, base)[0])
                    return cv
        return None
    cv: list[int] = []
    fmt = blend.header.endian_char + "i"
    for i in range(totloop):
        cv.append(_struct.unpack_from(fmt, blend.buf, blk.payload_offset + i * 4)[0])
    return cv


def _mesh_face_offsets(ctx, me_blk: Block, totpoly: int) -> list[int] | None:
    blend = ctx.blend
    me_struct = blend.struct_of(me_blk)
    if me_struct.by_name.get("poly_offset_indices") is None:
        return None
    ptr = blend.read_pointer(me_blk, me_struct, "poly_offset_indices")
    blk = blend.follow(ptr)
    if blk is None:
        # Legacy fallback: MPoly.loopstart + MPoly.totloop synthesized to offsets.
        if me_struct.by_name.get("mpoly") is not None:
            mp_ptr = blend.read_pointer(me_blk, me_struct, "mpoly")
            mp_blk = blend.follow(mp_ptr)
            if mp_blk is not None:
                mp_struct = blend.sdna.struct_for("MPoly")
                if mp_struct is not None and mp_struct.by_name.get("loopstart"):
                    ls_off = mp_struct.by_name["loopstart"].offset
                    tl_off = mp_struct.by_name["totloop"].offset
                    offsets = []
                    last_end = 0
                    for i in range(totpoly):
                        base = mp_blk.payload_offset + i * mp_struct.size
                        ls = _struct.unpack_from(blend.header.endian_char + "i", blend.buf, base + ls_off)[0]
                        tl = _struct.unpack_from(blend.header.endian_char + "i", blend.buf, base + tl_off)[0]
                        offsets.append(ls)
                        last_end = ls + tl
                    offsets.append(last_end)
                    return offsets
        return None
    offsets = list(_struct.unpack_from(blend.header.endian_char + "i" * (totpoly + 1),
                                       blend.buf, blk.payload_offset))
    return offsets


def _mesh_material_index(ctx, me_blk: Block, totpoly: int) -> list[int] | None:
    blend = ctx.blend
    blk = _attribute_data_block(blend, me_blk, "material_index")
    if blk is None:
        blk = _customdata_layer(blend, me_blk, "pdata", name_match="material_index",
                                type_match=CD_PROP_INT32)
    if blk is None:
        return None
    return list(_struct.unpack_from(blend.header.endian_char + "i" * totpoly,
                                    blend.buf, blk.payload_offset))


# ---------------------------------------------------------------------------
# Tiny matrix helpers — Blender stores 4×4 column-major as float[16].

def _matrix_unflatten(flat: list[float]) -> list[list[float]]:
    """Convert column-major 16-float to row-major 4×4 list-of-lists."""
    return [
        [flat[0], flat[4], flat[8],  flat[12]],
        [flat[1], flat[5], flat[9],  flat[13]],
        [flat[2], flat[6], flat[10], flat[14]],
        [flat[3], flat[7], flat[11], flat[15]],
    ]


def _matmul(A: list[list[float]], B: list[list[float]]) -> list[list[float]]:
    return [[sum(A[i][k] * B[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def _compose_trs(loc: list[float], rot_xyz: list[float],
                 size: list[float]) -> list[list[float]]:
    """Build a 4×4 from location + Euler XYZ rotation + per-axis scale.

    Order is T·Rz·Ry·Rx·S (Blender's `EULER_ORDER_XYZ`). This matches
    intern/cycles/util/transform.h:transform_euler — read for understanding,
    not mirrored.
    """
    cx, cy, cz = math.cos(rot_xyz[0]), math.cos(rot_xyz[1]), math.cos(rot_xyz[2])
    sx, sy, sz = math.sin(rot_xyz[0]), math.sin(rot_xyz[1]), math.sin(rot_xyz[2])
    # XYZ Euler: R = Rz * Ry * Rx
    R = [
        [cy * cz, sx * sy * cz - cx * sz, cx * sy * cz + sx * sz, 0.0],
        [cy * sz, sx * sy * sz + cx * cz, cx * sy * sz - sx * cz, 0.0],
        [-sy,     sx * cy,                cx * cy,                0.0],
        [0.0,     0.0,                    0.0,                    1.0],
    ]
    # Apply scale on the right.
    for i in range(3):
        R[i][0] *= size[0]
        R[i][1] *= size[1]
        R[i][2] *= size[2]
    # Translation in the last column.
    R[0][3] = loc[0]
    R[1][3] = loc[1]
    R[2][3] = loc[2]
    return R


def _compose_trs_quat(loc: list[float], quat: list[float],
                      size: list[float]) -> list[list[float]]:
    """Build a 4×4 from location + quaternion (w, x, y, z) + per-axis scale.

    Standard quat→matrix conversion (e.g. Shoemake 1985). Cycles uses the
    same formulation in intern/cycles/util/transform.h:transform_quaternion.
    """
    w, x, y, z = quat
    n = w * w + x * x + y * y + z * z
    s = 2.0 / n if n > 1e-12 else 0.0
    xs, ys, zs = x * s, y * s, z * s
    wx, wy, wz = w * xs, w * ys, w * zs
    xx, xy, xz = x * xs, x * ys, x * zs
    yy, yz, zz = y * ys, y * zs, z * zs
    R = [
        [1.0 - (yy + zz), xy - wz,         xz + wy,         0.0],
        [xy + wz,         1.0 - (xx + zz), yz - wx,         0.0],
        [xz - wy,         yz + wx,         1.0 - (xx + yy), 0.0],
        [0.0,             0.0,             0.0,             1.0],
    ]
    for i in range(3):
        R[i][0] *= size[0]
        R[i][1] *= size[1]
        R[i][2] *= size[2]
    R[0][3] = loc[0]
    R[1][3] = loc[1]
    R[2][3] = loc[2]
    return R


__all__ = ["build_scene", "BlendImportWarning"]
