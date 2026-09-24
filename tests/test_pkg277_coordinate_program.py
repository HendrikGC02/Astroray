"""pkg277 (#822) — coordinate-side op-VM programs for procedural textures.

`Texture Coordinate -> Separate XYZ -> Math(Sin) -> Combine XYZ -> Checker`
compiles to a coordinate program; the engine's CoordProgramTexture samples the
procedural at p' = svm_eval(prog, {p}) on the CPU, and the GPU bakes that
wrapper through the pkg190 procedural bake (no device code). The GPU
per-pixel gate is noise-floor-corrected; see the PIX_SPP comment below.
Design: .astroray_plan/docs/issue822-coordinate-side-opvm-design.md
"""
import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "blender_addon"))
import shader_vm_compiler as C  # noqa: E402


# --- duck-typed Blender node model (pkg219b / #818 test shape) -------------- #
class Sock:
    def __init__(self, name, default=0.0, link=None, type=None):
        self.name = name
        self.default_value = default
        self._link = link
        if type is not None:
            self.type = type

    @property
    def is_linked(self):
        return self._link is not None

    @property
    def links(self):
        return [self._link] if self._link else []


class Link:
    def __init__(self, from_node, from_socket_name="Vector"):
        self.from_node = from_node
        self.from_socket = type("S", (), {"name": from_socket_name})()


class SockList:
    def __init__(self, socks):
        self._socks = socks
        self._by_name = {s.name: s for s in socks}

    def get(self, name):
        return self._by_name.get(name)

    def __getitem__(self, i):
        return self._by_name[i] if isinstance(i, str) else self._socks[i]

    def __len__(self):
        return len(self._socks)

    def __iter__(self):
        return iter(self._socks)


class Node:
    def __init__(self, type, inputs=None, name="", **kw):
        self.type = type
        self.name = name or type
        self.inputs = SockList(inputs or [])
        for k, v in kw.items():
            setattr(self, k, v)


K_WARP = 12.0       # warp frequency k (design note table: 2..24)
CHK_SCALE = 5.0
C1 = (0.8, 0.8, 0.8)
C2 = (0.2, 0.2, 0.2)


def _warp_vector_socket(k=K_WARP, base_output="Generated", mapping=None):
    """Vector socket fed by TexCoord[.base] [-> Mapping] -> SepXYZ -> x*k -> Sin -> CombXYZ."""
    coord = Node('TEX_COORD', name='Texture Coordinate')
    src_node, src_out = coord, base_output
    if mapping is not None:
        loc, rot, scale = mapping
        src_node = Node('MAPPING', name='Mapping', vector_type='POINT', inputs=[
            Sock('Vector', (0, 0, 0), Link(coord, base_output)),
            Sock('Location', loc), Sock('Rotation', rot), Sock('Scale', scale)])
        src_out = 'Vector'
    sep = Node('SEPXYZ', name='Separate XYZ',
               inputs=[Sock('Vector', (0, 0, 0), Link(src_node, src_out))])
    mul = Node('MATH', name='Multiply', operation='MULTIPLY',
               inputs=[Sock('Value', 0.0, Link(sep, 'X')), Sock('Value_001', k)])
    sin = Node('MATH', name='Sine', operation='SINE',
               inputs=[Sock('Value', 0.0, Link(mul, 'Value')), Sock('Value_001', 0.5)])
    comb = Node('COMBXYZ', name='Combine XYZ', inputs=[
        Sock('X', 0.0, Link(sin, 'Value')), Sock('Y', 0.0, Link(sep, 'Y')),
        Sock('Z', 0.0, Link(sep, 'Z'))])
    return Sock('Vector', (0, 0, 0), Link(comb, 'Vector'))


def _ops(compiled):
    code = compiled['code_flat']
    return [code[i] for i in range(0, len(code), 8)]


# --------------------------------------------------------------------------- #
# Compiler
# --------------------------------------------------------------------------- #
def test_compile_sin_warp_chain():
    compiled = C.compile_coord_chain(_warp_vector_socket())
    assert compiled is not None
    ops = _ops(compiled)
    assert ops.count(C.OP_LOAD_TEX) == 1          # one shared coordinate leaf
    assert ops.count(C.OP_SEP_COLOR) == 3          # X, Y, Z reused, not recompiled
    assert C.OP_VEC_MATH in ops and C.OP_COMBINE_COLOR in ops
    sine = [compiled['code_flat'][i + 7] for i in range(0, len(compiled['code_flat']), 8)
            if compiled['code_flat'][i] == C.OP_VEC_MATH]
    assert sine == [C.VEC_MATH_OPS['SINE']]
    assert len(compiled['coord_sockets']) == 1
    assert compiled['coord_sockets'][0].links[0].from_node.type == 'TEX_COORD'


def test_affine_or_unlinked_chain_not_compiled():
    coord = Node('TEX_COORD')
    assert C.compile_coord_chain(Sock('Vector', (0, 0, 0), Link(coord, 'UV'))) is None
    mapping = Node('MAPPING', inputs=[Sock('Vector', (0, 0, 0), Link(coord, 'UV'))])
    assert C.compile_coord_chain(Sock('Vector', (0, 0, 0), Link(mapping, 'Vector'))) is None
    assert C.compile_coord_chain(Sock('Vector', (0, 0, 0))) is None


def test_texture_driven_coordinate_rejected():
    noise = Node('TEX_NOISE', inputs=[Sock('Vector')])
    sin = Node('MATH', operation='SINE', inputs=[Sock('Value', 0.0, Link(noise, 'Fac'))])
    comb = Node('COMBXYZ', inputs=[Sock('X', 0.0, Link(sin, 'Value')), Sock('Y'), Sock('Z')])
    with pytest.raises(C.VMCompileError):
        C.compile_coord_chain(Sock('Vector', (0, 0, 0), Link(comb, 'Vector')))


def test_unsupported_scalar_op_still_rejected():
    # Spec non-goal: arcsin/sinh/exp/log etc. stay warned + dropped.
    coord = Node('TEX_COORD')
    sep = Node('SEPXYZ', inputs=[Sock('Vector', (0, 0, 0), Link(coord, 'Generated'))])
    asin = Node('MATH', operation='ARCSINE', inputs=[Sock('Value', 0.0, Link(sep, 'X'))])
    comb = Node('COMBXYZ', inputs=[Sock('X', 0.0, Link(asin, 'Value')), Sock('Y'), Sock('Z')])
    with pytest.raises(C.VMCompileError):
        C.compile_coord_chain(Sock('Vector', (0, 0, 0), Link(comb, 'Vector')))


# --------------------------------------------------------------------------- #
# numpy reference: Cycles svm/checker.h (Apache-2.0) on the warped point.
# --------------------------------------------------------------------------- #
def _checker_parity(p, scale=CHK_SCALE):
    sp = (p * scale + 1e-6) * 0.999999
    i = np.abs(np.floor(sp).astype(np.int64)) % 2
    return (i[..., 0] == i[..., 1]) == (i[..., 2] == 1)


def _warp(p, k=K_WARP):
    q = p.copy()
    q[..., 0] = np.sin(k * p[..., 0])
    return q


def _mapping_matrix(loc, rot, scale):
    rx, ry, rz = rot
    cx, sx, cy, sy, cz, sz = (math.cos(rx), math.sin(rx), math.cos(ry),
                              math.sin(ry), math.cos(rz), math.sin(rz))
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    M = np.identity(4)
    M[:3, :3] = Rz @ Ry @ Rx @ np.diag(scale)
    M[:3, 3] = loc
    return M


def _compile_warp(**kw):
    compiled = C.compile_coord_chain(_warp_vector_socket(**kw))
    return compiled['out_slot'], compiled['code_flat'], compiled['consts_flat']


def _need_binding():
    astroray = pytest.importorskip("astroray")
    if not hasattr(astroray.Renderer(), "create_coord_program_texture"):
        pytest.skip("build predates pkg277 create_coord_program_texture")
    return astroray


def test_wrapper_sample_matches_numpy_exactly():
    astroray = _need_binding()
    r = astroray.Renderer()
    r.create_procedural_texture("chk", "checker", list(C1) + list(C2) + [CHK_SCALE])
    out, code, consts = _compile_warp()
    r.create_coord_program_texture("warp", "chk", "UV", out, code, consts)
    n = 64
    u = (np.arange(n) + 0.5) / n
    uu, vv = np.meshgrid(u, u)
    p = np.stack([uu, vv, np.zeros_like(uu)], -1)
    ref = np.where(_checker_parity(_warp(p)), C1[0], C2[0])
    got = np.array([[r.sample_named_texture("warp", float(a), float(b))[0]
                     for a in u] for b in u])
    # float32 sinf vs float64 sin: only points within 1e-4 of a cell edge may flip.
    sp = _warp(p)[..., 0] * CHK_SCALE
    near_edge = np.abs(sp - np.round(sp)) < 1e-3
    assert np.all((got == ref) | near_edge)
    assert (got != ref).mean() < 0.01


# --------------------------------------------------------------------------- #
# Render scene: z=0 quad over [-1,1]^2, Generated bbox = [-1,1]^3, camera
# filling the frame; lambertian under a uniform white world -> radiance = albedo.
# --------------------------------------------------------------------------- #
RES = 96
CAM_Z = 3.0
VFOV = 30.0
BBOX_MIN = [-1.0, -1.0, -1.0]
BBOX_SIZE = [2.0, 2.0, 2.0]
SPP = 256


def _pixel_generated(sub=1):
    """Generated coordinate at `sub`x`sub` sub-pixel points, shape (RES,RES,sub*sub,3)."""
    h = CAM_Z * math.tan(math.radians(VFOV) / 2)
    off = (np.arange(sub) + 0.5) / sub
    # Camera convention (measured): s = (i + jitter) / (W - 1), RTOW-style.
    px = (np.arange(RES)[:, None] + off[None, :]).reshape(-1) / (RES - 1)
    x = (2 * px - 1) * h
    y = (1 - 2 * px) * h
    X, Y = np.meshgrid(x, y)
    g = np.stack([(X + 1) / 2, (Y + 1) / 2, np.full_like(X, 0.5)], -1)
    g = g.reshape(RES, sub, RES, sub, 3).transpose(0, 2, 1, 3, 4).reshape(RES, RES, sub * sub, 3)
    return g


def _reference(field_fn):
    """(albedo_ref, interior_mask): interior excludes a 1-px band at cell edges.
    Pixels are classified against the two cell albedos (|C1-C2| = 0.6), so the
    default tol=0.25 checks the cell exactly while absorbing spectral MC noise."""
    par = field_fn(_pixel_generated(sub=6))
    mixed = ~(par.all(-1) | (~par).all(-1))
    band = mixed.copy()
    band[1:] |= mixed[:-1]
    band[:-1] |= mixed[1:]
    band[:, 1:] |= mixed[:, :-1]
    band[:, :-1] |= mixed[:, 1:]
    center = field_fn(_pixel_generated(sub=1))[..., 0]
    return np.where(center, C1[0], C2[0]), ~band


def _build_scene(r, tex_setup, use_gpu):
    from base_helpers import setup_camera
    r.set_use_gpu(bool(use_gpu))
    r.set_adaptive_sampling(False)  # parity gates: fixed spp (memory: adaptive stop metric)
    r.set_seed(7)
    r.set_background_color([1.0, 1.0, 1.0])
    name = tex_setup(r)
    mat = r.create_material("lambertian", [0.8, 0.8, 0.8], {"texture": name})
    A, B, Cc, D = [-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]
    n = [0, 0, 1]
    r.add_triangle_layers(A, B, Cc, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]}, n, n, n)
    r.add_triangle_layers(A, Cc, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]}, n, n, n)
    setup_camera(r, look_from=[0, 0, CAM_Z], look_at=[0, 0, 0], vup=[0, 1, 0],
                 vfov=VFOV, width=RES, height=RES)


def _checker_setup(warp=True, mapping=None, base="GENERATED", k=K_WARP):
    def setup(r):
        r.create_procedural_texture("chk277", "checker", list(C1) + list(C2) + [CHK_SCALE],
                                    "UV" if warp else base)
        if not warp:
            r.set_texture_generated_bbox("chk277", BBOX_MIN, BBOX_SIZE)
            return "chk277"
        out, code, consts = _compile_warp(k=k)
        r.create_coord_program_texture("warp277", "chk277", base, out, code, consts)
        r.set_texture_generated_bbox("warp277", BBOX_MIN, BBOX_SIZE)
        if mapping is not None:
            M = _mapping_matrix(*mapping)
            r.set_texture_mapping_matrix("warp277", [float(v) for v in M[:3, :].reshape(-1)])
        return "warp277"
    return setup


def _noise_setup(r):
    r.create_procedural_texture("noise277", "noise_perlin",
                                [5.0, 2.0, 0.5, 2.0, 0.0, 1.0, 0.0, 0.0, 1.0])
    out, code, consts = _compile_warp(k=6.0)
    r.create_coord_program_texture("wnoise277", "noise277", "GENERATED", out, code, consts)
    r.set_texture_generated_bbox("wnoise277", BBOX_MIN, BBOX_SIZE)
    return "wnoise277"


def _render(tex_setup, use_gpu, spp=SPP, seed=7):
    import astroray
    from base_helpers import render_image
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    if use_gpu and not (astroray.__features__.get("cuda", False)
                        and getattr(r, "gpu_available", False)):
        pytest.skip("No CUDA GPU — pkg277 GPU leg runs on the RTX box.")
    _build_scene(r, tex_setup, use_gpu)
    r.set_seed(seed)
    return np.asarray(render_image(r, samples=spp, max_depth=2, apply_gamma=False))


def _save(img, name):
    out = os.environ.get("PKG277_EVIDENCE_DIR")
    if out:
        from base_helpers import save_image
        save_image(np.clip(img, 0, 1) ** (1 / 2.2), os.path.join(out, name))


def _field(mapping=None, k=K_WARP):
    def fn(g):
        p = g
        if mapping is not None:
            M = _mapping_matrix(*mapping)
            p = g @ M[:3, :3].T + M[:3, 3]
        return _checker_parity(_warp(p, k))
    return fn


def _assert_matches_reference(img, field_fn, tol=0.25):
    ref, interior = _reference(field_fn)
    assert interior.mean() > 0.3, "fixture has too few interior pixels"
    err = np.abs(img[..., 0] - ref)
    bad = interior & (err > tol)
    assert bad.mean() == 0.0, (
        f"{int(bad.sum())} interior pixels differ from the numpy reference "
        f"(max err {err[interior].max():.4f})")


def test_camera_model_self_check_unwarped_checker_cpu():
    """Validates the numpy pixel->Generated model on the existing (unwarped) path."""
    pytest.importorskip("astroray")
    img = _render(_checker_setup(warp=False), use_gpu=False)
    _assert_matches_reference(img, lambda g: _checker_parity(g))


def test_cpu_warped_checker_matches_numpy():
    _need_binding()
    img = _render(_checker_setup(), use_gpu=False)
    _save(img, "cpu_warped_checker.png")
    _assert_matches_reference(img, _field())


MAPPING = ((0.1, -0.2, 0.0), (0.0, 0.0, 0.4), (1.5, 0.8, 1.0))


def test_cpu_mapping_then_warp_matches_numpy():
    _need_binding()
    img = _render(_checker_setup(mapping=MAPPING), use_gpu=False)
    _save(img, "cpu_mapping_warp.png")
    _assert_matches_reference(img, _field(mapping=MAPPING))


def test_object_base_cpu_exact():
    # Object base (GPU-unbakeable): the wrapper still evaluates exactly on CPU.
    # On this quad object space == world space; the reference is the warp of
    # the raw hit point (no bbox normalisation).
    _need_binding()
    img = _render(_checker_setup(base="OBJECT"), use_gpu=False)

    def fn(g):
        return _checker_parity(_warp(np.stack([2 * g[..., 0] - 1, 2 * g[..., 1] - 1,
                                               np.zeros_like(g[..., 2])], -1)))
    _assert_matches_reference(img, fn)


# Per-pixel gate (lead-approved change from the spec's raw 0.01 fraction). The
# spectral render is noisy: CPU seed-vs-seed |diff| > 0.01 (any channel) on the
# unwarped checker, adaptive off, is 75.1 % @256, 30.6 % @4096, 12.5 % @16384 spp
# (B-dominated; astra_run/batchY/y277/seed_floor_cpu.txt), so the raw fraction
# measures MC noise, not the 64^3 bake. Gate instead:
#   (2) frac(|GPU-CPU| > 0.01) - frac(|CPU-CPU'| > 0.01) <= 26 %  (all cases);
#   (1) checker only: cell-flip fraction frac(|GPU-CPU| > 0.3) <= 26 %, with
#       CPU-vs-CPU at 0.3 ~ 0 % (noise never flips a 0.6-contrast cell).
# 4096 spp keeps the noise floor well below saturation so (2) stays sensitive.
PIX_SPP = 4096
PIX_BUDGET = 0.26   # design note worst case (k = 24, 64^3 bake): 25.6 %
FLIP_THR = 0.3


def _frac_over(a, b, thr=0.01):
    return float((np.abs(a - b) > thr).any(-1).mean())


def _gpu_cpu_gates(tex_setup, name, cells=False):
    _need_binding()
    gpu = _render(tex_setup, use_gpu=True)
    cpu = _render(tex_setup, use_gpu=False)
    gm = np.array([gpu[..., c].mean() for c in range(3)])
    cm = np.array([cpu[..., c].mean() for c in range(3)])
    ratio = gm / np.maximum(cm, 1e-6)
    gpu_hi = _render(tex_setup, use_gpu=True, spp=PIX_SPP)
    cpu_hi = _render(tex_setup, use_gpu=False, spp=PIX_SPP)
    cpu_hi2 = _render(tex_setup, use_gpu=False, spp=PIX_SPP, seed=11)
    _save(gpu_hi, f"gpu_{name}.png")
    _save(cpu_hi, f"cpu_{name}.png")
    diff_frac = _frac_over(gpu_hi, cpu_hi)
    noise_floor = _frac_over(cpu_hi2, cpu_hi)
    flip = _frac_over(gpu_hi, cpu_hi, FLIP_THR)
    flip_floor = _frac_over(cpu_hi2, cpu_hi, FLIP_THR)
    print(f"[pkg277] {name}: 256spp mean ratio {ratio}; {PIX_SPP}spp |GPU-CPU|>0.01 "
          f"{diff_frac:.4f}, CPU-CPU' floor {noise_floor:.4f}, excess "
          f"{diff_frac - noise_floor:.4f}; flip>0.3 {flip:.4f} (floor {flip_floor:.4f})")
    assert np.all(np.abs(ratio - 1) <= 0.03), (ratio, cm, gm)
    assert diff_frac - noise_floor <= PIX_BUDGET, (diff_frac, noise_floor)
    if cells:
        assert flip_floor <= 0.001, flip_floor
        assert flip <= PIX_BUDGET, flip
    return gpu_hi, cpu_hi


def test_gpu_cpu_parity_warped_checker():
    _gpu_cpu_gates(_checker_setup(k=24.0), "warped_checker_k24", cells=True)


def test_gpu_cpu_parity_warped_noise():
    _gpu_cpu_gates(_noise_setup, "warped_noise")


def test_gpu_cpu_parity_mapping_then_warp():
    gpu, _ = _gpu_cpu_gates(_checker_setup(mapping=MAPPING), "mapping_warp", cells=True)
    # GPU applies Mapping before the warp: region mean matches the numpy field.
    ref, _ = _reference(_field(mapping=MAPPING))
    assert abs(gpu[..., 0].mean() - ref.mean()) < 0.02


# --------------------------------------------------------------------------- #
# Addon wiring (bpy stub, #818 test pattern)
# --------------------------------------------------------------------------- #
def _load_addon(monkeypatch):
    sys.path.insert(0, os.path.dirname(__file__))
    from test_issue818_procedural_opvm import _load_addon_stub
    addon = _load_addon_stub(monkeypatch)
    eng = addon.CustomRaytracerRenderEngine.__new__(addon.CustomRaytracerRenderEngine)
    eng._current_material_name = "M"
    eng._generated_textures_by_material = {}
    return eng


class _RecRenderer:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def rec(*a, **k):
            self.calls.append((name, a))
            return 1
        return rec


def _checker_node(vector):
    return Node('TEX_CHECKER', name='Checker', inputs=[
        vector, Sock('Color1', list(C1) + [1.0]), Sock('Color2', list(C2) + [1.0]),
        Sock('Scale', CHK_SCALE)])


def test_addon_wraps_warped_procedural(monkeypatch):
    eng = _load_addon(monkeypatch)
    rr = _RecRenderer()
    vec = _warp_vector_socket()
    name = eng.load_procedural_texture(_checker_node(vec), rr, vector_input=vec)
    created = [a for n, a in rr.calls if n == 'create_coord_program_texture']
    assert len(created) == 1 and created[0][0] == name
    assert created[0][2] == 'GENERATED'
    assert not [a for n, a in rr.calls if n == 'set_texture_mapping_matrix']
    assert not eng._degradation_report().messages()


def test_addon_mapping_applied_before_warp(monkeypatch):
    eng = _load_addon(monkeypatch)
    rr = _RecRenderer()
    vec = _warp_vector_socket(mapping=MAPPING)
    name = eng.load_procedural_texture(_checker_node(vec), rr, vector_input=vec)
    mats = [a for n, a in rr.calls if n == 'set_texture_mapping_matrix']
    assert len(mats) == 1 and mats[0][0] == name
    ref = _mapping_matrix(*MAPPING)[:3, :].reshape(-1)
    assert np.allclose(mats[0][1], ref, atol=1e-9)


def test_addon_object_base_records_degradation(monkeypatch):
    eng = _load_addon(monkeypatch)
    rr = _RecRenderer()
    vec = _warp_vector_socket(base_output="Object")
    eng.load_procedural_texture(_checker_node(vec), rr, vector_input=vec)
    created = [a for n, a in rr.calls if n == 'create_coord_program_texture']
    assert created and created[0][2] == 'OBJECT'
    msgs = " ".join(str(m) for m in eng._degradation_report().messages())
    assert "coordinate program" in msgs and "OBJECT" in msgs


def test_addon_affine_chain_keeps_legacy_path(monkeypatch):
    eng = _load_addon(monkeypatch)
    rr = _RecRenderer()
    coord = Node('TEX_COORD')
    vec = Sock('Vector', (0, 0, 0), Link(coord, 'UV'))
    eng.load_procedural_texture(_checker_node(vec), rr, vector_input=vec)
    assert not [a for n, a in rr.calls if n == 'create_coord_program_texture']


def test_addon_program_input_warped_child(monkeypatch):
    # Warped Checker -> Math(Multiply) -> Base Color: the ProgramTexture takes
    # the warped child's base coordinate and 3-D Mapping.
    eng = _load_addon(monkeypatch)
    rr = _RecRenderer()
    vec = _warp_vector_socket(mapping=MAPPING)
    chk = _checker_node(vec)
    mul = Node('MATH', operation='MULTIPLY',
               inputs=[Sock('A', 0.0, Link(chk, 'Color')), Sock('B', 1.0)])
    base = Sock('Base Color', [0.5, 0.5, 0.5], Link(mul, 'Color'))
    prog = eng._maybe_build_program_texture(base, Node('BSDF_PRINCIPLED', inputs=[base]),
                                            'Base Color', rr)
    assert prog is not None
    wrapper = [a for n, a in rr.calls if n == 'create_coord_program_texture'][0][0]
    inputs = [a for n, a in rr.calls if n == 'program_texture_add_input']
    assert inputs == [(prog, wrapper)]
    mats = {a[0]: a[1] for n, a in rr.calls if n == 'set_texture_mapping_matrix'}
    assert prog in mats and np.allclose(mats[prog], mats[wrapper])
