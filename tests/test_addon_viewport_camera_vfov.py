"""pkg101 — Blender addon viewport camera vfov extraction rotation-invariance.

The addon must extract vfov from `rv3d.window_matrix[1][1]` (projection-only),
not `rv3d.perspective_matrix[1][1]` (projection @ view). The latter couples
view rotation into the vfov extraction, causing the rendered object to shrink/
grow/flip as the user orbits the camera.

This test constructs several synthetic `RegionView3D` states with **different
rotations** but the **same projection matrix** and asserts the addon's vfov
extractor returns the same vfov for all of them (rotation-invariant).
"""

import importlib.util
import math
import sys
import types
from pathlib import Path


# ---------------------------------------------------------------------------
# Shared loader helper (from test_blender_viewport_session.py pattern)
# ---------------------------------------------------------------------------

def _load_blender_addon(monkeypatch):
    bpy_module = types.ModuleType("bpy")
    bpy_types_module = types.ModuleType("bpy.types")
    bpy_props_module = types.ModuleType("bpy.props")

    class _Base:
        pass

    class _RenderEngineBase:
        def report(self, *_a, **_k): return None
        def update_progress(self, *_a, **_k): return None
        def update_stats(self, *_a, **_k): return None
        def test_break(self): return False

    bpy_types_module.Panel = _Base
    bpy_types_module.Operator = _Base
    bpy_types_module.AddonPreferences = _Base
    bpy_types_module.PropertyGroup = _Base
    bpy_types_module.RenderEngine = _RenderEngineBase
    bpy_module.types = bpy_types_module

    for name in ("BoolProperty", "IntProperty", "FloatProperty", "StringProperty",
                 "PointerProperty", "FloatVectorProperty", "EnumProperty"):
        setattr(bpy_props_module, name, lambda **_kwargs: None)
    bpy_module.props = bpy_props_module
    bpy_module.path = types.SimpleNamespace(abspath=lambda p: p)

    shader_blending_module = types.ModuleType("shader_blending")
    shader_blending_module.blend_shader_specs = {}
    shader_blending_module.add_shader_specs = {}

    mathutils_module = types.ModuleType("mathutils")
    mathutils_module.Vector = lambda values: values

    astroray_module = types.ModuleType("astroray")
    astroray_module.__version__ = "test"
    astroray_module.__features__ = {"cuda": False, "spectral": True}
    astroray_module.__file__ = "/fake/astroray.pyd"
    astroray_module.integrator_registry_names = lambda: ["path_tracer"]
    astroray_module.material_registry_names = lambda: ["lambertian"]
    astroray_module.pass_registry_names = lambda: []

    monkeypatch.setitem(sys.modules, "bpy", bpy_module)
    monkeypatch.setitem(sys.modules, "bpy.types", bpy_types_module)
    monkeypatch.setitem(sys.modules, "bpy.props", bpy_props_module)
    monkeypatch.setitem(sys.modules, "shader_blending", shader_blending_module)
    monkeypatch.setitem(sys.modules, "mathutils", mathutils_module)
    monkeypatch.setitem(sys.modules, "astroray", astroray_module)

    module_path = Path(__file__).parent.parent / "blender_addon" / "__init__.py"
    spec = importlib.util.spec_from_file_location("astroray_blender_addon_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Matrix stubs
# ---------------------------------------------------------------------------

class _Vec3:
    """Minimal 3D vector for matrix decomposition."""
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _Matrix3:
    """Minimal 3x3 matrix for rotation."""
    def __init__(self, rows):
        self.rows = [list(r) for r in rows]

    def __matmul__(self, vec):
        # Simple 3x3 @ vec3 multiply for camera direction extraction.
        return _Vec3(
            self.rows[0][0] * vec[0] + self.rows[0][1] * vec[1] + self.rows[0][2] * vec[2],
            self.rows[1][0] * vec[0] + self.rows[1][1] * vec[1] + self.rows[1][2] * vec[2],
            self.rows[2][0] * vec[0] + self.rows[2][1] * vec[1] + self.rows[2][2] * vec[2],
        )


class _Matrix4:
    """Minimal 4x4 matrix that supports `mat[i][j]`, .translation, .to_3x3()."""
    def __init__(self, rows):
        self.rows = [list(r) for r in rows]

    def __getitem__(self, i):
        return self.rows[i]

    @property
    def translation(self):
        """Extract translation from the last column."""
        return _Vec3(self.rows[0][3], self.rows[1][3], self.rows[2][3])

    def to_3x3(self):
        """Extract upper-left 3x3 rotation submatrix."""
        return _Matrix3([
            [self.rows[0][0], self.rows[0][1], self.rows[0][2]],
            [self.rows[1][0], self.rows[1][1], self.rows[1][2]],
            [self.rows[2][0], self.rows[2][1], self.rows[2][2]],
        ])

    def inverted(self):
        # For a pure rotation/translation matrix (no scale), the inverse is:
        # [ R^T  | -R^T * t ]
        # [  0   |    1     ]
        # For simplicity, return an identity-ish inverse.
        return _Matrix4([[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)])


def _make_projection_matrix(vfov_deg, aspect):
    """Construct a perspective projection matrix for a given vfov (degrees)
    and aspect ratio. OpenGL convention: [1][1] = 1 / tan(vfov/2)."""
    vfov_rad = math.radians(vfov_deg)
    f = 1.0 / math.tan(vfov_rad / 2.0)
    # Symmetric frustum, near=0.1, far=100.
    return _Matrix4([
        [f / aspect, 0, 0, 0],
        [0, f, 0, 0],
        [0, 0, -1.001, -0.2001],
        [0, 0, -1, 0],
    ])


def _make_view_matrix(pitch_deg):
    """Construct a camera view matrix with a pitch rotation.
    This represents the camera-to-world inverse."""
    pitch_rad = math.radians(pitch_deg)
    c = math.cos(pitch_rad)
    s = math.sin(pitch_rad)
    # Pitch rotation around X-axis.
    return _Matrix4([
        [1, 0, 0, 0],
        [0, c, -s, 0],
        [0, s, c, -5.0],  # camera at z=-5
        [0, 0, 0, 1],
    ])


def _make_perspective_matrix(projection, view):
    """Multiply projection @ view to create perspective_matrix."""
    result = [[0.0]*4 for _ in range(4)]
    for i in range(4):
        for j in range(4):
            result[i][j] = sum(projection.rows[i][k] * view.rows[k][j] for k in range(4))
    return _Matrix4(result)


# ---------------------------------------------------------------------------
# Stub renderer
# ---------------------------------------------------------------------------

class _RecordingRenderer:
    """Minimal renderer stub that records setup_camera calls."""
    def __init__(self):
        self.setup_camera_calls = []

    def set_adaptive_sampling(self, *_): pass
    def set_clamp_direct(self, *_): pass
    def set_clamp_indirect(self, *_): pass
    def set_filter_glossy(self, *_): pass
    def set_use_reflective_caustics(self, *_): pass
    def set_use_refractive_caustics(self, *_): pass
    def set_wavelength_range(self, *_): pass
    def set_output_mode(self, *_): pass
    def set_integrator(self, *_): pass
    def set_use_gpu(self, *_): pass

    @property
    def gpu_available(self):
        return False

    def setup_camera(self, *args, **_kw):
        self.setup_camera_calls.append(args)


# ---------------------------------------------------------------------------
# Test: vfov extraction is rotation-invariant
# ---------------------------------------------------------------------------

def test_vfov_extraction_is_rotation_invariant(monkeypatch):
    """The addon must extract vfov from `rv3d.window_matrix[1][1]`, not
    `rv3d.perspective_matrix[1][1]`. The former is rotation-invariant; the
    latter couples view rotation into element [1][1], causing the extracted
    vfov to vary with camera pitch/yaw/roll.

    This test constructs three synthetic `RegionView3D` states with **different
    pitch angles** (0°, 30°, -45°) but the **same projection matrix**
    (vfov=60°, aspect=4/3). The addon's vfov extractor must return ~60° for
    all three.

    On current HEAD (before fix): the test will FAIL because the addon reads
    `perspective_matrix[1][1]`, which varies with pitch.

    After fix: the test will PASS because the addon reads `window_matrix[1][1]`,
    which is rotation-invariant.
    """
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()

    # Ground truth: vfov=60°, aspect=4/3 (320x240).
    expected_vfov = 60.0
    aspect = 320.0 / 240.0
    projection = _make_projection_matrix(expected_vfov, aspect)

    # Three camera poses with different pitch rotations.
    pitches = [0.0, 30.0, -45.0]
    extracted_vfovs = []

    for pitch in pitches:
        view = _make_view_matrix(pitch)
        perspective = _make_perspective_matrix(projection, view)

        # Construct a stub rv3d with both window_matrix (projection-only)
        # and perspective_matrix (projection @ view).
        rv3d = types.SimpleNamespace(
            window_matrix=projection,
            perspective_matrix=perspective,
            view_matrix=view,
            view_perspective='PERSP',
            view_camera_zoom=0.0,
            view_camera_offset=(0.0, 0.0),
        )
        region = types.SimpleNamespace(width=320, height=240)
        space = types.SimpleNamespace(lens=50.0)
        scene = types.SimpleNamespace(
            camera=None,
            custom_raytracer=types.SimpleNamespace(
                use_adaptive_sampling=False,
                clamp_direct=0.0, clamp_indirect=0.0, filter_glossy=0.0,
                use_reflective_caustics=True, use_refractive_caustics=True,
                device_mode='cpu',
                preview_samples=1, max_bounces=4,
                diffuse_bounces=2, glossy_bounces=2, transmission_bounces=2,
                volume_bounces=0, transparent_bounces=2,
                wavelength_preset='visible',
                wavelength_min=380.0, wavelength_max=780.0,
                colourmap='grayscale',
                integrator_type='path_tracer',
                viewport_display_pass='combined',
                viewport_oidn=False,
            )
        )
        context = types.SimpleNamespace(
            region=region,
            region_data=rv3d,
            space_data=space,
            scene=scene,
        )

        # Call _setup_viewport_camera, which internally extracts vfov.
        engine._setup_viewport_camera(renderer, context, 320, 240)

        # Extract the vfov from the setup_camera call.
        # setup_camera signature: (look_from, look_at, vup, vfov, aspect, ...)
        args = renderer.setup_camera_calls[-1]
        extracted_vfov = args[3]
        extracted_vfovs.append(extracted_vfov)

    # All three extracted vfovs must be equal (rotation-invariant).
    for i, pitch in enumerate(pitches):
        assert abs(extracted_vfovs[i] - expected_vfov) < 1.0, (
            f"At pitch={pitch}°: expected vfov≈{expected_vfov}°, "
            f"got {extracted_vfovs[i]:.2f}°. "
            f"Vfov extraction is NOT rotation-invariant — likely reading "
            f"`perspective_matrix[1][1]` instead of `window_matrix[1][1]`."
        )

    # Sanity: all three must be within 0.5° of each other.
    min_vfov = min(extracted_vfovs)
    max_vfov = max(extracted_vfovs)
    assert abs(max_vfov - min_vfov) < 0.5, (
        f"Vfov extraction varies with rotation: "
        f"{extracted_vfovs} across pitches {pitches}. "
        f"Expected rotation-invariance."
    )


# ---------------------------------------------------------------------------
# Full frustum parity for the F12 camera-datablock path
# (_apply_camera / _compute_vfov_degrees).
#
# pkg101 covered viewport vfov *rotation-invariance*. It did NOT cover the
# remaining frustum parameters that decide whether the F12 render lines up
# with Blender's camera: sensor_fit (which sensor axis is used), film shift,
# and aspect ratio. These tests lock that parity so a future edit to the
# bridge can't silently re-break alignment (closes the Q1 "no parity gate" gap).
# ---------------------------------------------------------------------------


class _Quat:
    """Identity rotation quaternion stub. `rot @ vec` returns the vector
    unchanged as a _Vec3. Camera direction is not under test here (vfov / shift
    / aspect are), so an identity rotation is sufficient."""
    def __matmul__(self, vec):
        return _Vec3(vec[0], vec[1], vec[2])


class _CamMatrix4:
    """4x4 camera world-matrix stub supporting `.decompose()` and `.translation`."""
    def __init__(self, loc=(0.0, 0.0, 0.0)):
        self._loc = loc

    @property
    def translation(self):
        return _Vec3(*self._loc)

    def decompose(self):
        return _Vec3(*self._loc), _Quat(), _Vec3(1.0, 1.0, 1.0)


def _make_camera_obj(lens=50.0, sensor_fit='AUTO', sensor_width=36.0,
                     sensor_height=24.0, shift_x=0.0, shift_y=0.0,
                     cam_type='PERSP'):
    dof = types.SimpleNamespace(use_dof=False, aperture_fstop=0.0,
                                focus_object=None, focus_distance=10.0)
    camera = types.SimpleNamespace(
        type=cam_type, lens=lens, sensor_fit=sensor_fit,
        sensor_width=sensor_width, sensor_height=sensor_height,
        shift_x=shift_x, shift_y=shift_y, dof=dof,
    )
    return types.SimpleNamespace(data=camera, matrix_world=_CamMatrix4())


def _apply_camera_args(monkeypatch, width=160, height=90, **cam_kwargs):
    """Run the F12 path (_apply_camera with rv3d=None) and return the
    positional args of the resulting setup_camera call:
      (look_from, look_at, vup, vfov, aspect, aperture, focus, w, h, shift_x, shift_y)
    """
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()
    cam_obj = _make_camera_obj(**cam_kwargs)
    engine._apply_camera(renderer, cam_obj, width, height)  # rv3d=None → F12 datablock path
    return renderer.setup_camera_calls[-1]


def test_apply_camera_sensor_fit_horizontal_vs_vertical(monkeypatch):
    """sensor_fit must pick the sensor axis. On a non-square image, HORIZONTAL
    and VERTICAL fits must yield different vfov, each matching the Cycles/Eevee
    formula independently recomputed here."""
    w, h = 160, 90
    aspect = w / h
    h_args = _apply_camera_args(monkeypatch, width=w, height=h,
                                sensor_fit='HORIZONTAL',
                                sensor_width=36.0, sensor_height=24.0, lens=50.0)
    v_args = _apply_camera_args(monkeypatch, width=w, height=h,
                                sensor_fit='VERTICAL',
                                sensor_width=36.0, sensor_height=24.0, lens=50.0)
    # HORIZONTAL: hfov from sensor_width, then convert to vfov via aspect.
    exp_h = math.degrees(2.0 * math.atan((36.0 / (2 * 50.0)) / aspect))
    # VERTICAL: vfov directly from sensor_height.
    exp_v = math.degrees(2.0 * math.atan(24.0 / (2 * 50.0)))
    assert abs(h_args[3] - exp_h) < 0.05
    assert abs(v_args[3] - exp_v) < 0.05
    assert abs(h_args[3] - v_args[3]) > 1.0, "sensor_fit branch had no effect on vfov"


def test_apply_camera_auto_fit_landscape_matches_horizontal(monkeypatch):
    """AUTO on a landscape image (width >= height) must equal HORIZONTAL fit."""
    auto = _apply_camera_args(monkeypatch, width=160, height=90, sensor_fit='AUTO')
    horiz = _apply_camera_args(monkeypatch, width=160, height=90, sensor_fit='HORIZONTAL')
    assert abs(auto[3] - horiz[3]) < 1e-6


def test_apply_camera_auto_fit_portrait_matches_vertical(monkeypatch):
    """AUTO on a portrait image (height > width) must equal VERTICAL fit."""
    auto = _apply_camera_args(monkeypatch, width=90, height=160, sensor_fit='AUTO')
    vert = _apply_camera_args(monkeypatch, width=90, height=160, sensor_fit='VERTICAL')
    assert abs(auto[3] - vert[3]) < 1e-6


def test_apply_camera_shift_film_fit_scaled(monkeypatch):
    """camera.shift_x / shift_y (film offset) must reach setup_camera scaled by
    Blender's film-fit factor viewfac/win, NOT passed through raw.

    pkg193: the pre-existing test asserted raw passthrough (shift_y unchanged),
    but that produced a measured 20 px F12-vs-Blender offset for non-square
    cameras. Blender's viewplane (Cycles blender_camera_viewplane, Apache-2.0)
    offsets by dx = shift_x*viewfac, dy = shift_y*viewfac with viewfac = winx for
    a HORIZONTAL fit else winy. On a 160x90 AUTO (→HORIZONTAL) image: viewfac=160,
    so shift_x is unchanged (160/160) and shift_y scales by 160/90. Verified 0.00
    px vs Blender 5.1 world_to_camera_view over 8 conditions.
    """
    w, h = 160, 90  # AUTO → HORIZONTAL (landscape) → viewfac = w
    args = _apply_camera_args(monkeypatch, width=w, height=h,
                              shift_x=0.125, shift_y=-0.0625)
    assert abs(args[9] - 0.125 * (w / w)) < 1e-9, "shift_x film-fit scaling wrong"
    assert abs(args[10] - (-0.0625) * (w / h)) < 1e-9, "shift_y film-fit scaling wrong"


def test_apply_camera_aspect_ratio(monkeypatch):
    """The aspect ratio passed to setup_camera must equal width / height."""
    args = _apply_camera_args(monkeypatch, width=320, height=200)
    assert abs(args[4] - (320.0 / 200.0)) < 1e-9


def test_apply_camera_known_square_vfov(monkeypatch):
    """Hardcoded ground truth: 50 mm lens, 36 mm sensor, square image → vfov ≈ 39.6°.
    Independent of the addon's formula; locks against unit / parameter drift."""
    args = _apply_camera_args(monkeypatch, width=100, height=100,
                              sensor_fit='HORIZONTAL', sensor_width=36.0, lens=50.0)
    assert abs(args[3] - 39.598) < 0.1, f"expected ~39.6deg, got {args[3]:.3f}"
