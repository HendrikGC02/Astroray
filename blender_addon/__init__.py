# NOTE: Blender 5.2+ uses blender_manifest.toml (see sibling file). bl_info is kept
# as a fallback for Blender 4.x — Blender prefers the manifest when both exist.
bl_info = {
    "name": "Astroray Renderer",
    "author": "Hendrik Combrinck",
    "version": (4, 0, 0),
    "blender": (5, 0, 0),
    "location": "Render Properties > Render Engine > Astroray",
    "description": "PBR path tracer with Disney BRDF, NEE, MIS, GR black holes",
    "category": "Render",
}

import bpy
from bpy.types import Panel, Operator, AddonPreferences, PropertyGroup, RenderEngine
from bpy.props import BoolProperty, IntProperty, FloatProperty, StringProperty, PointerProperty, FloatVectorProperty, EnumProperty
import mathutils, math, numpy as np, traceback, sys, os, time, inspect
from pathlib import Path

# pkg112: gate the batched geometry-upload path. Default on; a parity/benchmark
# harness can set this False to force the legacy per-triangle loop for A/B compare.
BULK_GEOMETRY_UPLOAD = True

addon_dir = os.path.dirname(__file__)
if addon_dir not in sys.path: sys.path.insert(0, addon_dir)

from shader_blending import blend_shader_specs, add_shader_specs
# pkg176 Stage 1: read Blender's native render/sampling settings (deprecated
# custom aliases). Pure-data translator (no bpy/engine deps); see settings_map.py.
from native_settings import resolve_native_settings, report_unsupported_native_controls
# pkg119 Phase C: single graceful-degradation policy the shader-fallback,
# native-drop and dropped-silent-dispatch warning sources funnel through.
from degradation import DegradationReport
from _bulk_geometry import mesh_to_bulk_arrays  # pkg112 batched geometry upload
from _bulk_geometry import mesh_world_positions  # pkg88-B object motion blur bake


def _matrices_differ(m1, m2, eps=1e-6):
    """True if two 4x4 mathutils.Matrix (or any [row][col]-indexable 4x4)
    differ by more than `eps` in any element. Used by pkg88-B to decide
    whether an object actually moved between the current frame and shutter
    close -- genuinely static objects must keep using the pre-pkg88-B
    add_triangles_bulk path unchanged (no motion upload, no behaviour
    change)."""
    for r in range(4):
        for c in range(4):
            if abs(m1[r][c] - m2[r][c]) > eps:
                return True
    return False

# pkg116: scene exporter and per-domain caches. Defensive import handles both
# package-relative (Blender loads us as bl_ext.user_default.astroray) and
# standalone (test harnesses load __init__.py directly).
def _import_exporter():
    try:
        from . import exporter as exp
        return exp
    except ImportError:
        import importlib.util as _u
        exporter_path = os.path.join(addon_dir, "exporter.py")
        if not os.path.isfile(exporter_path):
            return None
        spec = _u.spec_from_file_location("astroray_exporter", exporter_path)
        if spec is None or spec.loader is None:
            return None
        mod = _u.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

exporter_module = _import_exporter()

# pkg57: native Astroray shader nodes (Spectral Profile, Sellmeier Glass,
# IR/UV Response, NRC Hint, Output). Imported defensively so a partial install
# (missing nodes/ directory) does not break the rest of the addon.
def _import_astroray_nodes():
    """Load the `nodes/` subpackage. Tries package-relative import first
    (the normal case when Blender loads us as `bl_ext.user_default.astroray`),
    then falls back to a direct file load (test harnesses load this file
    standalone without the package wrapper)."""
    try:
        from . import nodes as _nodes  # type: ignore
        return _nodes
    except Exception:
        # Includes AttributeError when loaded under a stub `bpy` (test
        # harnesses) that doesn't define ShaderNode / NodeSocket / Menu —
        # unit tests never need the node classes; we fall through silently.
        pass
    try:
        import importlib.util as _u
        nodes_init = os.path.join(addon_dir, "nodes", "__init__.py")
        if not os.path.isfile(nodes_init):
            return None
        spec = _u.spec_from_file_location("astroray_blender_nodes", nodes_init)
        if spec is None or spec.loader is None:
            return None
        mod = _u.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception as exc:  # pragma: no cover - defensive
        print(f"Astroray native shader nodes unavailable: {exc}")
        return None


astroray_nodes = _import_astroray_nodes()
_ASTRORAY_NODES_AVAILABLE = astroray_nodes is not None

# On Windows the compiled .pyd ships with bundled MinGW runtime DLLs
# (libgomp-1.dll, etc.). Python 3.8+ no longer searches PATH for module
# dependencies, so we have to explicitly add the addon directory to the
# DLL search list before importing.
if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
    _ASTRORAY_DLL_DIRECTORY_HANDLES = []
    _dll_dirs = [
        addon_dir,
        # OIDN DLLs bundled alongside the addon (placed here by build_blender_addon.py)
        os.path.join(addon_dir, "oidn"),
        # OIDN installed system-wide at common locations.
        r"C:\oidn\bin",
        r"C:\Program Files\Intel\oidn\bin",
        r"C:\Program Files\Intel\OpenImageDenoise\bin",
    ]
    for _env_var in ("OIDN_ROOT", "ASTRORAY_OIDN_DIR"):
        if _env_var in os.environ:
            _dll_dirs.append(os.path.join(os.environ[_env_var], "bin"))
    for _d in _dll_dirs:
        if os.path.isdir(_d):
            try:
                _ASTRORAY_DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(_d))
            except (FileNotFoundError, OSError):
                pass

try:
    import astroray
    RAYTRACER_AVAILABLE = True
    print(f"Custom Raytracer {astroray.__version__} loaded")
except ImportError as e:
    RAYTRACER_AVAILABLE = False
    print(f"Failed to load raytracer module: {e}")

def _try_load_spectral_profiles() -> None:
    """Load profiles.bin if present so the UI dropdown can populate."""
    if not RAYTRACER_AVAILABLE or not hasattr(astroray, "load_spectral_profiles"):
        return
    candidates = [
        os.path.join(addon_dir, "data", "spectral_profiles", "profiles.bin"),
        os.path.join(os.path.dirname(addon_dir), "data", "spectral_profiles", "profiles.bin"),
    ]
    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            astroray.load_spectral_profiles(path)
            return
        except Exception:
            pass


_try_load_spectral_profiles()


# pkg56 Phase A: viewport-sync per-stage timing helpers. These call into
# the C++ ring buffer (astroray.record_viewport_stage /
# viewport_perf_frame_complete). Both helpers are no-ops if the binding
# isn't present — keeps older astroray.pyd builds working with this addon.
def _viewport_perf_record(stage, t0):
    """Push (now - t0) milliseconds into the in-flight frame's stage bucket."""
    if not RAYTRACER_AVAILABLE:
        return
    rec = getattr(astroray, "record_viewport_stage", None)
    if rec is None:
        return
    try:
        rec(stage, (time.perf_counter() - t0) * 1000.0)
    except Exception:
        pass


def _viewport_perf_frame_complete():
    """Close the current frame and roll the ring buffer."""
    if not RAYTRACER_AVAILABLE:
        return
    fn = getattr(astroray, "viewport_perf_frame_complete", None)
    if fn is None:
        return
    try:
        fn()
    except Exception:
        pass


def _integrator_type_items(self, context):
    if RAYTRACER_AVAILABLE:
        items = [('auto', 'Auto (Best Available)', 'Use accelerated integrators when available, otherwise fall back')]
        items.extend((n, n.replace('_', ' ').title(), '') for n in astroray.integrator_registry_names())
        return items
    return [('auto', 'Auto (Best Available)', '')]

_VIEWPORT_DISPLAY_PASS_ITEMS = [
    ("combined", "Combined", "Full shaded result"),
    ("albedo", "Albedo", "First-hit albedo"),
    ("normal", "Normal", "First-hit normal (mapped to 0-1)"),
    ("depth", "Depth", "Depth (normalized)"),
    ("diffuse_direct", "Diffuse Direct", "Diffuse direct lighting"),
    ("glossy_direct", "Glossy Direct", "Glossy direct lighting"),
    ("diffuse_indirect", "Diffuse Indirect", "Diffuse indirect lighting"),
    ("glossy_indirect", "Glossy Indirect", "Glossy indirect lighting"),
    ("emission", "Emission", "Emissive contribution"),
    ("environment", "Environment", "Environment contribution"),
    ("ao", "Ambient Occlusion", "Ambient occlusion"),
    ("shadow", "Shadow", "Shadow contribution"),
]

class CustomRaytracerRenderSettings(PropertyGroup):
    # pkg176 Stage 4: the DIRECT-mapped custom duplicates (samples,
    # preview_samples, the light-path depths, clamp direct/indirect, filter
    # glossy, reflective/refractive caustics, use_denoising) were RETIRED here.
    # Their one-release back-compat window (Stage 1) is closed: the exporter now
    # reads the native Blender/Cycles value for every `direct` row via
    # native_settings.resolve_native_settings (see blender_addon/settings_map.py).
    # An old .blend that saved one of the removed props degrades gracefully -
    # Blender drops the unknown member on load and the native value is used.
    # Only genuinely engine-unique / semantically-mismatched controls remain
    # below (spectral band, device tri-state, integrator, denoiser backend, the
    # not-yet-plumbed adaptive-sampling / light-sampler controls).
    viewport_display_pass: EnumProperty(
        name="Viewport Pass",
        description="Render pass shown in the rendered-shading viewport",
        items=_VIEWPORT_DISPLAY_PASS_ITEMS,
        default="combined",
    )
    viewport_oidn: BoolProperty(
        name="Viewport Denoise",
        default=False,
        description="Apply AI denoiser to the viewport buffer (visible wavelengths only). "
                    "Backend selected by 'Denoiser' setting below.",
    )
    # pkg70 — denoiser backend chooser. AUTO prefers OptiX when both OptiX
    # and OIDN are compiled in AND a CUDA device is visible at runtime;
    # falls back to OIDN otherwise. Used for both viewport_oidn and
    # use_denoising final-render denoise.
    denoiser_backend: EnumProperty(
        name="Denoiser",
        description="Which AI denoiser to use when denoising is enabled",
        items=[
            ('auto',  'Auto',  'OptiX when available on NVIDIA GPUs, OIDN otherwise'),
            ('optix', 'OptiX', 'NVIDIA OptiX (NVIDIA GPU + OptiX SDK build only)'),
            ('oidn',  'OIDN',  'Intel Open Image Denoise (CPU and CUDA)'),
        ],
        default='auto',
    )
    use_adaptive_sampling: BoolProperty(name="Adaptive Sampling", default=True,
        description="Stop sampling pixels that have already converged")
    adaptive_threshold: FloatProperty(name="Noise Threshold", min=0.001, max=1.0, default=0.01)
    light_sampler: EnumProperty(
        name="Light Sampler",
        description="Strategy for sampling lights in Next Event Estimation (Conty et al. 2018 Light Tree)",
        items=[
            ('uniform', "Uniform", "Sample all lights uniformly (unbiased baseline, lowest variance for few lights)"),
            ('power', "Power", "Sample lights by total emitted power (default, good for moderate light counts)"),
            ('light_tree', "Light Tree", "Importance sampling via hierarchical tree (best for many lights, pkg86/pkg86-B)"),
        ],
        default='power',
    )
    device_mode: EnumProperty(
        name="Device",
        description="Rendering device — Auto picks GPU when available and safe",
        items=[
            ('auto', 'Auto',  'Use GPU when available, fall back to CPU silently'),
            ('gpu',  'GPU',   'Force GPU (warns if CUDA unavailable)'),
            ('cpu',  'CPU',   'Always use CPU'),
        ],
        default='auto',
    )
    integrator_type: EnumProperty(
        name="Integrator",
        description="Light transport integrator (from plugin registry)",
        items=_integrator_type_items,
    )
    # pkg178 Stage 5: route Blender's Principled BSDF to Astroray's NATIVE
    # 'principled' material (faithful Cycles port: coat/sheen/anisotropy/alpha/
    # emission driven directly) instead of the Disney approximation. The Disney
    # path stays as the fallback when this is off.
    # RATIFIED to production default ON (2026-08-11): the owner-authorized
    # auto-flip gate (spec pkg178 D3 / memory pkg178-repin-and-stage5-autonomy)
    # is satisfied — the Cycles-5.2 parity matrix is green: BSDF_PRINCIPLED PASSES
    # the pkg119-B differential gate (SSIM 0.972, dE 1.88) and thin-film
    # dielectric+conductor land in-band across the 100-1000 nm x film-IOR sweep
    # (see .astroray_plan/docs/pkg178-thinfilm-parity-findings.md). No longer
    # experimental; do NOT hard-code OFF here.
    use_native_principled: BoolProperty(
        name="Native Principled BSDF",
        default=True,
        description="Route Blender's Principled BSDF to Astroray's native "
                    "'principled' material (coat, sheen, anisotropy, alpha and "
                    "emission driven directly) instead of the Disney "
                    "approximation. Disney remains the fallback when off",
    )
    # pkg39: wavelength / multi-spectral settings
    wavelength_preset: EnumProperty(
        name="Preset",
        description="Wavelength rendering preset",
        items=[
            ('visible',  'Visible',  'Standard 380-780 nm sRGB rendering'),
            ('near_ir',  'Near IR',  '700-1000 nm near-infrared rendering'),
            ('uv',       'UV',       '300-400 nm ultraviolet rendering'),
            ('custom',   'Custom',   'User-defined wavelength range'),
        ],
        default='visible',
    )
    wavelength_min: FloatProperty(name="Min (nm)", min=100.0, max=2500.0, default=380.0,
        description="Minimum wavelength for custom band")
    wavelength_max: FloatProperty(name="Max (nm)", min=100.0, max=2500.0, default=780.0,
        description="Maximum wavelength for custom band")
    colourmap: EnumProperty(
        name="Colourmap",
        description="Output colourmap for non-visible renders",
        items=[
            ('grayscale',       'Grayscale',       'Linear grey'),
            ('hot',             'Hot',             'Black-red-yellow-white (thermal)'),
            ('inferno',         'Inferno',         'Perceptually uniform dark-to-bright'),
            ('viridis',         'Viridis',         'Perceptually uniform blue-to-yellow'),
            ('ir_false_colour', 'IR False Colour', 'Kodak Aerochrome-style IR palette'),
        ],
        default='grayscale',
    )

    # pkg87c: Cryptomatte depth (number of ID/weight pairs per pixel)
    cryptomatte_depth: EnumProperty(
        name="Cryptomatte Depth",
        description="Number of ID/weight pairs per pixel (more = more accurate multi-object pixels)",
        items=[
            ('2',  '2',  '1 EXR layer'),
            ('4',  '4',  '2 EXR layers'),
            ('6',  '6',  '3 EXR layers (default)'),
            ('8',  '8',  '4 EXR layers'),
            ('16', '16', '8 EXR layers'),
        ],
        default='6',
    )

    last_render_stats: StringProperty(
        name="Last Render Stats",
        default="",
        options={'HIDDEN'},
        description="Integrator stats from the most recent render (auto-populated)",
    )


# pkg70 — backend availability cache. Probing OptiX init constructs a
# CUDARenderer to check device visibility, which we don't want to do per
# frame. Cache first answer.
_DENOISER_BACKEND_CACHE = {}


def _optix_runtime_available() -> bool:
    if "optix" in _DENOISER_BACKEND_CACHE:
        return _DENOISER_BACKEND_CACHE["optix"]
    available = False
    if RAYTRACER_AVAILABLE and astroray.__features__.get("optix_denoiser", False):
        try:
            available = bool(astroray.gpu_optix_available())
        except Exception:
            available = False
    _DENOISER_BACKEND_CACHE["optix"] = available
    return available


def _oidn_compiled_in() -> bool:
    return RAYTRACER_AVAILABLE and bool(astroray.__features__.get("oidn_denoiser", False))


def _resolve_denoiser_pass(settings) -> str | None:
    """Pick the denoiser pass name to register, or None if neither backend
    is available. Mirrors Cycles' "OptiX preferred when both present" choice.
    """
    choice = getattr(settings, "denoiser_backend", "auto")
    optix_ok = _optix_runtime_available()
    oidn_ok  = _oidn_compiled_in()
    if choice == "optix":
        return "optix_denoiser" if optix_ok else None
    if choice == "oidn":
        return "oidn_denoiser" if oidn_ok else None
    # auto — OptiX preferred on NVIDIA, OIDN fallback.
    if optix_ok:
        return "optix_denoiser"
    if oidn_ok:
        return "oidn_denoiser"
    return None


def _report_backend(reporter, level, message):
    if reporter is None:
        return
    try:
        reporter({level}, message)
    except Exception:
        pass


def _wavelength_range_from_settings(settings):
    preset = getattr(settings, "wavelength_preset", "visible")
    if preset == 'near_ir':
        return 700.0, 1000.0
    if preset == 'uv':
        return 300.0, 400.0
    if preset == 'custom':
        return settings.wavelength_min, settings.wavelength_max
    return 380.0, 780.0


# Hardcoded preference order for the 'auto' integrator dropdown. The addon
# owns this UX policy so the engine doesn't need to know about it; the actual
# names must come from astroray.integrator_registry_names() at runtime
# (registry is the source of truth). Pattern mirrored from Cycles'
# intern/cycles/blender/properties.py device-type auto-resolution.
_AUTO_INTEGRATOR_PREFERENCE = ("path_tracer", "multiwavelength_path_tracer")


def _resolve_auto_integrator(settings):
    """Resolve the UI sentinel 'auto' to a concrete registered plugin.

    Policy (pkg80):
      - Query astroray.integrator_registry_names().
      - Walk a hardcoded preference list first, then any remaining names in
        registry order.
      - When device_mode='gpu', skip plugins whose capabilities report
        gpu_supported=False.
      - Raise RuntimeError if no registered plugin satisfies the request.
    """
    try:
        names = list(astroray.integrator_registry_names())
    except Exception as exc:
        raise RuntimeError(
            f"Astroray: integrator 'auto' could not be resolved — "
            f"registry query failed ({exc})"
        ) from exc

    require_gpu = getattr(settings, "device_mode", "auto") == "gpu"

    ordered = [n for n in _AUTO_INTEGRATOR_PREFERENCE if n in names]
    ordered.extend(n for n in names if n not in ordered)

    for name in ordered:
        if not require_gpu:
            return name
        caps = _integrator_capabilities(name)
        if bool(caps.get("gpuSupported", False)):
            return name

    if require_gpu:
        raise RuntimeError(
            "Astroray: integrator 'auto' could not be resolved to a "
            "registered plugin for device_mode='gpu' — no registered "
            "integrator reports GPU support. Set the integrator dropdown "
            "to a specific integrator."
        )
    raise RuntimeError(
        "Astroray: integrator 'auto' could not be resolved — no "
        "integrators are registered."
    )


def _effective_integrator_name(settings):
    lmin, lmax = _wavelength_range_from_settings(settings)
    if lmax > 780.0 or lmin < 380.0:
        return "multiwavelength_path_tracer"
    name = getattr(settings, "integrator_type", "path_tracer")
    if name != "auto":
        return name
    return _resolve_auto_integrator(settings)


def _route_replace_to_mw(has_replace_profile, is_outside_visible, active_device,
                         integrator_name):
    """pkg195 Stage C: decide whether to override the integrator to the
    multiwavelength path tracer so a Replace-mode authored spectrum (Drawn /
    Spectrum Preset / Spectral Profile source node) is consulted per-λ in the
    visible band. Only the MW integrator calls evalSpectralExt; the default
    path_tracer never does, so without this the authored reflectance is a visible
    no-op (the pkg57 failure Stage C fixes).

    Restricted to CPU: Replace is CPU-exact, and the GPU MW leg is the
    light-sampling-blind naive oracle (enableNEE contract, blender_module.cpp:1822)
    that would only render darker — GPU keeps its integrator and the degradation
    report notes the approximation. Returns True when the caller should switch to
    'multiwavelength_path_tracer'."""
    return (bool(has_replace_profile)
            and not is_outside_visible
            and active_device == "cpu"
            and integrator_name != "multiwavelength_path_tracer")


def _integrator_capabilities(name):
    try:
        return astroray.integrator_capabilities(name)
    except Exception as exc:
        return {
            "gpuSupported": False,
            "gpuFallbackReason": f"capability query failed: {exc}",
        }


def _check_gpu_limitations_and_report(renderer, settings, reporter=None, has_passes=False, has_denoise=False):
    """pkg96 P5 guard: detect GPU mode + CPU-only features (AOV/denoise/world-only)
    and show an explicit notice. Does NOT auto-route to CPU.

    Returns True if a limitation was detected and reported, False otherwise.
    """
    # Only check if GPU is active
    try:
        is_gpu = bool(getattr(renderer, '_use_gpu', False))
    except Exception:
        is_gpu = False

    if not is_gpu:
        return False

    # Check for CPU-only features
    limitations = []
    if has_passes:
        limitations.append("AOV passes")
    if has_denoise:
        limitations.append("denoise")

    # TODO: world-only check would require scene analysis (no geometry + world diffuse)
    # That's expensive and the spec says "cheap guard" — defer to later if needed.

    if limitations:
        feature_list = " / ".join(limitations)
        message = (
            f"Astroray GPU limitation: {feature_list} are CPU-only "
            "pending the pkg55-B' wavefront pass pipeline. "
            "Switch device_mode to CPU to get this output."
        )
        if reporter:
            reporter('WARNING', message)
        else:
            print(f"[pkg96-P5-guard] {message}")
        return True

    return False


def configure_backend(renderer, settings, reporter=None, integrator_name=None) -> str:
    """Apply device_mode to renderer. Returns 'gpu' or 'cpu'.

    Shared by final render and viewport render so both paths behave identically.
    """
    mode = getattr(settings, "device_mode", "auto")
    if mode == "cpu":
        # pkg147: an OpenMP-enabled .pyd deadlocks CPU renders >16px; refuse
        # right at the point CPU mode is actually selected (not at register()
        # time, which would also block legitimate GPU-only use of the same
        # ad-hoc build).
        _check_openmp_disabled()
        return "cpu"

    selected_integrator = integrator_name or _effective_integrator_name(settings)
    caps = _integrator_capabilities(selected_integrator)
    if not bool(caps.get("gpuSupported", False)):
        reason = caps.get("gpuFallbackReason", "no GPU kernel implemented")
        message = (
            f"Astroray: integrator '{selected_integrator}' does not support GPU"
            f" ({reason})"
        )
        if mode == "gpu":
            _report_backend(reporter, 'ERROR', message)
            raise RuntimeError(message)
        _report_backend(reporter, 'INFO', message + "; using CPU")
        _check_openmp_disabled()  # pkg147
        return "cpu"

    try:
        gpu_ok = renderer.gpu_available
    except Exception:
        gpu_ok = False

    if mode == "gpu" and not gpu_ok:
        message = "Astroray: GPU requested but no CUDA GPU is available"
        _report_backend(reporter, 'ERROR', message)
        raise RuntimeError(message)

    if (mode == "auto" and gpu_ok) or mode == "gpu":
        try:
            renderer.set_use_gpu(True)
            return "gpu"
        except Exception as exc:
            if mode == "gpu":
                message = f"Astroray: GPU requested but CUDA initialization failed ({exc})"
                _report_backend(reporter, 'ERROR', message)
                raise RuntimeError(message) from exc
            _report_backend(reporter, 'INFO', f"Astroray: GPU initialization failed ({exc}); using CPU")
    _check_openmp_disabled()  # pkg147
    return "cpu"


def _configure_backend_for_context(renderer, settings, reporter=None, integrator_name=None) -> str:
    """Call configure_backend with diagnostics context when the hook supports it."""
    try:
        signature = inspect.signature(configure_backend)
    except (TypeError, ValueError):
        return configure_backend(renderer, settings, reporter, integrator_name)

    positional_count = sum(
        1 for param in signature.parameters.values()
        if param.kind in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD)
    )
    has_varargs = any(
        param.kind == param.VAR_POSITIONAL
        for param in signature.parameters.values()
    )
    if has_varargs or positional_count >= 4:
        return configure_backend(renderer, settings, reporter, integrator_name)
    return configure_backend(renderer, settings)


def _material_type_items(self, context):
    if RAYTRACER_AVAILABLE:
        return [(n, n.replace('_', ' ').title(), '') for n in astroray.material_registry_names()]
    return [('disney', 'Disney', ''), ('lambertian', 'Lambertian', '')]

def _spectral_profile_items(self, context):
    if not RAYTRACER_AVAILABLE or not hasattr(astroray, "spectral_profile_names"):
        return [('__none__', '<None>', '')]
    names = []
    try:
        names = list(astroray.spectral_profile_names())
    except Exception:
        names = []
    items = [('__none__', '<None>', 'No spectral profile (renders black outside visible)')]
    items.extend((n, n, '') for n in names)
    return items

# pkg195 Stage B: emission-category (category 7) lamp SPDs shipped in
# profiles.bin (design doc §1.1). The DB does not expose category in-memory, so
# the preset dropdown filters the loaded names against this known set (order
# preserved). Provenance for each is recorded in data/spectral_profiles/sources.md.
_EMISSION_PROFILE_NAMES = (
    'sodium_vapor', 'mercury_vapor',
    'cie_f2', 'cie_f3',
    'led_3000k', 'led_5000k', 'led_6500k',
)


def _light_emission_preset_items(self, context):
    if not RAYTRACER_AVAILABLE or not hasattr(astroray, "spectral_profile_names"):
        return [('sodium_vapor', 'Sodium Vapor', '')]
    try:
        available = set(astroray.spectral_profile_names())
    except Exception:
        available = set()
    items = [(n, n.replace('_', ' ').title(), '')
             for n in _EMISSION_PROFILE_NAMES if n in available]
    if not items:
        # DB not loaded / missing emission SPDs: keep the enum non-empty so the
        # PropertyGroup still registers.
        items = [('sodium_vapor', 'Sodium Vapor', '')]
    return items


def _profile_range_label(profile_name):
    """pkg195 Stage B: '300-2500 nm @ 5 nm' style label for a named profile."""
    if (not RAYTRACER_AVAILABLE or not hasattr(astroray, "spectral_profile_range")
            or not profile_name or profile_name == "__none__"):
        return ""
    try:
        lmin, lmax, step = astroray.spectral_profile_range(profile_name)
    except Exception:
        return ""
    if lmax <= lmin:
        return ""
    return f"{lmin:.0f}-{lmax:.0f} nm @ {step:.0f} nm"


def _active_wavelength_band(settings):
    preset = getattr(settings, "wavelength_preset", "visible")
    if preset == "near_ir":
        return 700.0, 1000.0
    if preset == "uv":
        return 300.0, 400.0
    if preset == "custom":
        return float(getattr(settings, "wavelength_min", 380.0)), float(getattr(settings, "wavelength_max", 780.0))
    return 380.0, 780.0


def _spectral_profile_curve_samples(profile_name: str, lmin: float, lmax: float, n: int = 32):
    if (not RAYTRACER_AVAILABLE or
            not hasattr(astroray, "spectral_profile_reflectance") or
            not profile_name or profile_name == "__none__" or
            n <= 1):
        return []
    lmin = float(lmin)
    lmax = float(lmax)
    if lmax < lmin:
        lmin, lmax = lmax, lmin
    step = (lmax - lmin) / float(n - 1)
    samples = []
    for i in range(n):
        wl = lmin + step * float(i)
        try:
            r = float(astroray.spectral_profile_reflectance(profile_name, float(wl)))
        except Exception:
            r = 0.0
        samples.append((wl, max(0.0, min(1.0, r))))
    return samples


def _update_spectral_preview_image(samples, width: int = 256, height: int = 96):
    """Draw a tiny reflectance curve into a Blender Image datablock."""
    if not samples or not hasattr(bpy, "data") or not hasattr(bpy.data, "images"):
        return None
    name = "AstroraySpectralProfilePreview"
    img = bpy.data.images.get(name)
    if img is None:
        try:
            img = bpy.data.images.new(name=name, width=width, height=height, alpha=True, float_buffer=True)
        except Exception:
            return None
    try:
        if img.size[0] != width or img.size[1] != height:
            img.scale(width, height)
    except Exception:
        pass

    pixels = np.zeros((height, width, 4), dtype=np.float32)
    pixels[:, :, 3] = 1.0

    xs = np.linspace(0, width - 1, num=len(samples), dtype=np.float32)
    ys = np.array([s[1] for s in samples], dtype=np.float32)
    ys = np.clip(ys, 0.0, 1.0)
    ypix = (height - 2) - ys * (height - 3)

    col = np.array([0.2, 0.9, 0.2, 1.0], dtype=np.float32)
    for i in range(len(xs) - 1):
        x0, y0 = int(xs[i]), int(ypix[i])
        x1, y1 = int(xs[i + 1]), int(ypix[i + 1])
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        x, y = x0, y0
        while True:
            if 0 <= x < width and 0 <= y < height:
                pixels[y, x, :] = col
                if y + 1 < height:
                    pixels[y + 1, x, :] = col
            if x == x1 and y == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x += sx
            if e2 < dx:
                err += dx
                y += sy

    try:
        img.pixels.foreach_set(pixels.reshape(-1))
        img.update()
    except Exception:
        return None
    return img


class CustomRaytracerMaterialSettings(PropertyGroup):
    material_type: EnumProperty(
        name="Material Type",
        description="Material type from the plugin registry",
        items=_material_type_items,
    )
    use_disney: BoolProperty(name="Use Disney BRDF", default=True)
    metallic: FloatProperty(name="Metallic", min=0, max=1, default=0)
    roughness: FloatProperty(name="Roughness", min=0, max=1, default=0.5)
    transmission: FloatProperty(name="Transmission", min=0, max=1, default=0)
    ior: FloatProperty(name="IOR", min=1, max=3, default=1.45)
    clearcoat: FloatProperty(name="Clearcoat", min=0, max=1, default=0)
    clearcoat_gloss: FloatProperty(name="Clearcoat Gloss", min=0, max=1, default=1)
    # pkg39: spectral profile for outside-visible rendering
    spectral_profile: EnumProperty(
        name="Spectral Profile",
        description="Spectral reflectance profile for outside-visible (IR/UV) rendering.",
        items=_spectral_profile_items,
        default=0,
    )
    live_preview_resolution: EnumProperty(
        name="Resolution",
        description="Resolution for the one-sphere material preview",
        items=[
            ("64", "64 x 64", ""),
            ("128", "128 x 128", ""),
            ("256", "256 x 256", ""),
        ],
        default="64",
    )
    live_preview_samples: IntProperty(
        name="Samples",
        description="Samples per pixel for the one-sphere material preview",
        min=1,
        max=64,
        default=8,
    )


class CustomRaytracerLightSettings(PropertyGroup):
    # pkg195 Stage B: spectral emission mode for dedicated lights. `native`
    # reproduces exactly today's blackbody/RGB behaviour (light.use_temperature
    # + light.color). `preset` / `custom_profile` route the emission through a
    # MeasuredSPD (sodium_vapor etc.), with the light colour kept as a gel tint
    # via the engine's Composite EmissionSpectrum mode.
    spectrum_mode: EnumProperty(
        name="Spectrum",
        description="How this light's emission spectrum is authored",
        items=[
            ('native', 'Native',
             "Blackbody (from light temperature) or RGB upsample — today's behaviour"),
            ('preset', 'Lamp Preset',
             "A measured lamp SPD from the profile database (sodium, mercury, "
             "fluorescent, LED)"),
            ('custom_profile', 'Custom Profile',
             "Any spectral profile by name (e.g. a drawn/imported emission profile)"),
        ],
        default='native',
    )
    preset_profile: EnumProperty(
        name="Lamp",
        description="Measured lamp emission spectrum",
        items=_light_emission_preset_items,
    )
    custom_profile: EnumProperty(
        name="Profile",
        description="Spectral profile used as this light's emission SPD",
        items=_spectral_profile_items,
        default=0,
    )


def _light_spectrum_profile(light):
    """pkg195 Stage B: resolved profile name for preset/custom spectrum modes,
    or '' when the light is in native mode / unresolved."""
    settings = getattr(light, 'custom_raytracer', None)
    if settings is None:
        return ""
    mode = getattr(settings, 'spectrum_mode', 'native')
    if mode == 'preset':
        return getattr(settings, 'preset_profile', "") or ""
    if mode == 'custom_profile':
        name = getattr(settings, 'custom_profile', "") or ""
        return "" if name == "__none__" else name
    return ""


def _preview_helpers():
    try:
        from _preview_helpers import render_material_preview, save_preview_png
        return render_material_preview, save_preview_png
    except ImportError:
        helper_dir = Path(addon_dir).parent / "scripts" / "diagnostics"
        if helper_dir.is_dir() and str(helper_dir) not in sys.path:
            sys.path.insert(0, str(helper_dir))
        from _preview_helpers import render_material_preview, save_preview_png
        return render_material_preview, save_preview_png


def _safe_preview_name(name: str) -> str:
    safe = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in str(name))
    return safe.strip("_") or "material"


def _find_preview_hdri() -> str | None:
    scenes_dir = Path(addon_dir) / "scenes"
    if not scenes_dir.is_dir():
        return None
    for suffix in ("*.hdr", "*.exr", "*.hdri"):
        match = next(scenes_dir.glob(suffix), None)
        if match is not None:
            return str(match)
    return None


def _save_preview_image(pixels, path: Path, resolution: int):
    _, save_preview_png = _preview_helpers()
    try:
        return save_preview_png(pixels, path)
    except Exception:
        img = bpy.data.images.new("Astroray Material Preview", resolution, resolution, alpha=True, float_buffer=False)
        rgba = np.ones((resolution, resolution, 4), dtype=np.float32)
        rgba[..., :3] = np.clip(np.asarray(pixels, dtype=np.float32)[..., :3], 0.0, 1.0)
        img.pixels.foreach_set(rgba.reshape(-1))
        img.filepath_raw = str(path)
        img.file_format = 'PNG'
        img.save()
        return path


def _load_preview_image(path: str):
    if not path or not os.path.exists(path):
        return None
    try:
        return bpy.data.images.load(path, check_existing=True)
    except Exception:
        return None


def _create_live_preview_material(renderer, mat):
    """P3-a fix (BUG-15): Convert a Blender material for the live preview without
    constructing a RenderEngine (which Blender forbids).

    Uses _convert_node_material_standalone, a module-level wrapper that provides
    the same conversion logic as CustomRaytracerRenderEngine.convert_node_material
    but without requiring a RenderEngine instance.
    """
    if getattr(mat, "use_nodes", False) and getattr(mat, "node_tree", None):
        return _convert_node_material_standalone(mat, renderer)

    color = list(getattr(mat, "diffuse_color", [0.8, 0.8, 0.8])[:3])
    mat_settings = getattr(mat, "custom_raytracer", None)
    if mat_settings is None:
        return renderer.create_material("disney", color, {})
    if not getattr(mat_settings, "use_disney", True):
        mat_type = getattr(mat_settings, "material_type", "lambertian") or "lambertian"
        return renderer.create_material(mat_type, color, {})
    params = {
        "metallic": float(getattr(mat_settings, "metallic", 0.0)),
        "roughness": float(getattr(mat_settings, "roughness", 0.5)),
        "transmission": float(getattr(mat_settings, "transmission", 0.0)),
        "ior": float(getattr(mat_settings, "ior", 1.45)),
        "clearcoat": float(getattr(mat_settings, "clearcoat", 0.0)),
        "clearcoat_gloss": float(getattr(mat_settings, "clearcoat_gloss", 1.0)),
    }
    return renderer.create_material("disney", color, params)

class CustomRaytracerRenderEngine(RenderEngine):
    bl_idname = "CUSTOM_RAYTRACER"
    bl_label = "Astroray"
    bl_use_preview = True
    bl_use_postprocess = True
    bl_use_shading_nodes_custom = False
    bl_use_eevee_viewport = True  # fall back to Eevee for Material/Solid shading
    bl_use_gpu_context = False

    # RenderEngine is a C-backed class; we deliberately do NOT override
    # __init__ (Blender has caveats around RenderEngine constructor overrides,
    # see `bpy.types.RenderEngine` docs). Viewport state is lazily created
    # inside view_update / view_draw instead.
    # pkg116: Exporter owns viewport session state. Properties below proxy to
    # exporter for backward compatibility with tests that read/write these attrs.
    _exporter = None

    # Proxy properties for viewport session state (owned by Exporter)
    @property
    def _viewport_renderer(self):
        exp = getattr(self, '_exporter', None)
        return exp._viewport_renderer if exp else None

    @_viewport_renderer.setter
    def _viewport_renderer(self, value):
        exp = self._get_exporter()
        exp._viewport_renderer = value

    @property
    def _viewport_texture(self):
        exp = getattr(self, '_exporter', None)
        return exp._viewport_texture if exp else None

    @_viewport_texture.setter
    def _viewport_texture(self, value):
        exp = self._get_exporter()
        exp._viewport_texture = value

    @property
    def _viewport_width(self):
        exp = getattr(self, '_exporter', None)
        return exp._viewport_width if exp else 0

    @_viewport_width.setter
    def _viewport_width(self, value):
        exp = self._get_exporter()
        exp._viewport_width = value

    @property
    def _viewport_height(self):
        exp = getattr(self, '_exporter', None)
        return exp._viewport_height if exp else 0

    @_viewport_height.setter
    def _viewport_height(self, value):
        exp = self._get_exporter()
        exp._viewport_height = value

    @property
    def _viewport_full_synced(self):
        exp = getattr(self, '_exporter', None)
        return exp._viewport_full_synced if exp else False

    @_viewport_full_synced.setter
    def _viewport_full_synced(self, value):
        exp = self._get_exporter()
        exp._viewport_full_synced = value

    @property
    def _viewport_camera_hash(self):
        exp = getattr(self, '_exporter', None)
        return exp._viewport_camera_hash if exp else None

    @_viewport_camera_hash.setter
    def _viewport_camera_hash(self, value):
        exp = self._get_exporter()
        exp._viewport_camera_hash = value

    @property
    def _viewport_camera_substantive_hash(self):
        exp = getattr(self, '_exporter', None)
        return exp._viewport_camera_substantive_hash if exp else None

    @_viewport_camera_substantive_hash.setter
    def _viewport_camera_substantive_hash(self, value):
        exp = self._get_exporter()
        exp._viewport_camera_substantive_hash = value

    @property
    def _viewport_accum_pixels(self):
        exp = getattr(self, '_exporter', None)
        return exp._viewport_accum_pixels if exp else None

    @_viewport_accum_pixels.setter
    def _viewport_accum_pixels(self, value):
        exp = self._get_exporter()
        exp._viewport_accum_pixels = value

    @property
    def _viewport_current_spp(self):
        exp = getattr(self, '_exporter', None)
        return exp._viewport_current_spp if exp else 0

    @_viewport_current_spp.setter
    def _viewport_current_spp(self, value):
        exp = self._get_exporter()
        exp._viewport_current_spp = value

    @property
    def _viewport_target_spp(self):
        exp = getattr(self, '_exporter', None)
        return exp._viewport_target_spp if exp else 0

    @_viewport_target_spp.setter
    def _viewport_target_spp(self, value):
        exp = self._get_exporter()
        exp._viewport_target_spp = value

    @property
    def _viewport_accum_key(self):
        exp = getattr(self, '_exporter', None)
        return exp._viewport_accum_key if exp else None

    @_viewport_accum_key.setter
    def _viewport_accum_key(self, value):
        exp = self._get_exporter()
        exp._viewport_accum_key = value

    @property
    def _viewport_prewarmed_for_mode(self):
        exp = getattr(self, '_exporter', None)
        return exp._viewport_prewarmed_for_mode if exp else None

    @_viewport_prewarmed_for_mode.setter
    def _viewport_prewarmed_for_mode(self, value):
        exp = self._get_exporter()
        exp._viewport_prewarmed_for_mode = value
    _PASS_SPECS = [
        ("Diffuse Direct", "diffuse_direct", "use_pass_diffuse_direct"),
        ("Diffuse Indirect", "diffuse_indirect", "use_pass_diffuse_indirect"),
        ("Diffuse Color", "diffuse_color", "use_pass_diffuse_color"),
        ("Glossy Direct", "glossy_direct", "use_pass_glossy_direct"),
        ("Glossy Indirect", "glossy_indirect", "use_pass_glossy_indirect"),
        ("Glossy Color", "glossy_color", "use_pass_glossy_color"),
        ("Transmission Direct", "transmission_direct", "use_pass_transmission_direct"),
        ("Transmission Indirect", "transmission_indirect", "use_pass_transmission_indirect"),
        ("Transmission Color", "transmission_color", "use_pass_transmission_color"),
        ("Volume Direct", "volume_direct", "use_pass_volume_direct"),
        ("Volume Indirect", "volume_indirect", "use_pass_volume_indirect"),
        ("Emission", "emission", "use_pass_emit"),
        ("Environment", "environment", "use_pass_environment"),
        ("Ambient Occlusion", "ao", "use_pass_ambient_occlusion"),
        ("Shadow", "shadow", "use_pass_shadow"),
    ]
    _DATA_PASS_SPECS = [
        # Cycles registers its DENOISING_PASS_* / PASS_DENOISING_* guide
        # passes together in intern/cycles/blender/sync.cpp lines 740-745
        # (Apache-2.0): Albedo and Normal are the compositor Denoise node's
        # RGB guide inputs when Denoising Data is enabled.
        ("Albedo", "albedo", 3, "RGB", "use_pass_denoising_data"),
        ("Normal", "normal", 3, "RGB", "use_pass_denoising_data"),
        ("Depth", "depth", 4, "RGBA", "use_pass_z"),
        ("Mist", "mist", 4, "RGBA", "use_pass_mist"),
        ("Position", "position", 4, "RGBA", "use_pass_position"),
        ("Normal", "normal", 4, "RGBA", "use_pass_normal"),
        ("UV", "uv", 4, "RGBA", "use_pass_uv"),
        ("IndexOB", "object_index", 4, "RGBA", "use_pass_object_index"),
        ("IndexMA", "material_index", 4, "RGBA", "use_pass_material_index"),
    ]
    # pkg87c: Cryptomatte passes are generated dynamically based on depth setting
    @classmethod
    def _cryptomatte_pass_specs(cls, scene):
        """Generate Cryptomatte pass specs based on scene.astroray.cryptomatte_depth."""
        settings = getattr(scene, "astroray", None)
        depth = int(getattr(settings, "cryptomatte_depth", "6")) if settings else 6
        numLayers = (depth + 1) // 2  # depth 6 → 3 layers
        specs = []
        for layer in range(numLayers):
            specs.append((f"CryptoObject{layer:02d}", "cryptomatte_object", "use_pass_cryptomatte_object"))
            specs.append((f"CryptoMaterial{layer:02d}", "cryptomatte_material", "use_pass_cryptomatte_material"))
        return specs

    def update_render_passes(self, scene, renderlayer):
        for display_name, _, toggle_name in self._PASS_SPECS:
            if getattr(renderlayer, toggle_name, False):
                self.register_pass(scene, renderlayer, display_name, 4, "RGBA", "COLOR")
        registered_data_passes = set()
        for display_name, _, channels, channel_id, toggle_name in self._DATA_PASS_SPECS:
            if getattr(renderlayer, toggle_name, False):
                if display_name in registered_data_passes:
                    continue
                registered_data_passes.add(display_name)
                self.register_pass(scene, renderlayer, display_name, channels, channel_id, "COLOR")
        # pkg87c: Register Cryptomatte passes dynamically based on depth
        for display_name, _, toggle_name in self._cryptomatte_pass_specs(scene):
            if getattr(renderlayer, toggle_name, False):
                self.register_pass(scene, renderlayer, display_name, 4, "RGBA", "COLOR")

    @classmethod
    def _enabled_pass_specs(cls, view_layer):
        enabled = []
        for display_name, key, toggle_name in cls._PASS_SPECS:
            if getattr(view_layer, toggle_name, False):
                enabled.append((display_name, key))
        return enabled

    @classmethod
    def _enabled_data_pass_specs(cls, view_layer):
        enabled = []
        seen = set()
        for display_name, key, _, _, toggle_name in cls._DATA_PASS_SPECS:
            if getattr(view_layer, toggle_name, False):
                if display_name in seen:
                    continue
                seen.add(display_name)
                enabled.append((display_name, key))
        return enabled

    @classmethod
    def _enabled_cryptomatte_pass_specs(cls, view_layer):
        """Get enabled Cryptomatte passes based on view_layer scene's depth setting."""
        enabled = []
        scene = getattr(view_layer, "id_data", None)  # view_layer.id_data is the parent scene
        for display_name, key, toggle_name in cls._cryptomatte_pass_specs(scene):
            if getattr(view_layer, toggle_name, False):
                enabled.append((display_name, key))
        return enabled

    def render(self, depsgraph):
        if not RAYTRACER_AVAILABLE:
            self.report({'ERROR'}, "Raytracer module not available")
            return
        scene = depsgraph.scene
        view_layer = getattr(depsgraph, "view_layer", None)
        if view_layer is not None and not bool(getattr(view_layer, "use", True)):
            print(f"Skipping view layer '{view_layer.name}' (Use for Rendering disabled)")
            return
        scale = scene.render.resolution_percentage / 100.0
        width = int(scene.render.resolution_x * scale)
        height = int(scene.render.resolution_y * scale)
        # pkg176 Stage 1: read native Blender/Cycles settings for the
        # DIRECT-mapped controls (deprecated custom aliases honoured for one
        # release). `settings` is a transparent view: direct settings resolve to
        # native, everything else falls through to scene.custom_raytracer.
        settings = resolve_native_settings(scene, self.report)
        # pkg119 Phase C: one consolidated degradation report per render. Reset it
        # here (a final render gets a fresh accumulator); the shader-fallback and
        # dropped-silent-dispatch sources record into it during convert_scene, and
        # it is emitted once at the end of the render below.
        self._degradation = DegradationReport()
        # pkg176 Stage 3: never silently drop world/light/camera native controls
        # the engine can't honour yet. pkg119 Phase C folds those drops into the
        # single policy (emit=False -> collect only, no second parallel warning).
        self._degradation.ignore_messages(
            report_unsupported_native_controls(scene, report=None, emit=False)
        )

        print(f"Rendering {width}x{height}, {settings.samples} samples")
        renderer = None
        try:
            renderer = astroray.Renderer()
            renderer.set_adaptive_sampling(settings.use_adaptive_sampling)
            self.convert_scene(depsgraph, renderer, width, height, resolved=settings)

            integrator_name = _effective_integrator_name(settings)
            try:
                active_device = _configure_backend_for_context(renderer, settings, self.report, integrator_name)
            except RuntimeError as exc:
                self.report({'ERROR'}, str(exc))
                return
            if active_device == "gpu":
                try:
                    print(f"GPU rendering: {renderer.gpu_device_name}")
                except Exception:
                    pass

            def progress_callback(value):
                if self.test_break(): return False
                self.update_progress(value)
                return True

            start_time = time.time()
            # pkg39: wavelength range
            lmin, lmax = _wavelength_range_from_settings(settings)
            renderer.set_wavelength_range(lmin, lmax)
            is_outside_visible = (lmax > 780.0 or lmin < 380.0)
            if is_outside_visible:
                renderer.set_output_mode("luminance")
            # pkg195 Stage C: a Replace-mode authored spectrum (Drawn / Spectrum
            # Preset / Spectral Profile source node wired to a Surface) is only
            # consulted per-λ by the multiwavelength integrator. In the visible band
            # the default path_tracer never calls evalSpectralExt, so the authored
            # reflectance would be a no-op (the pkg57 failure this stage fixes).
            # Route visible-band CPU renders to the MW integrator when such a
            # material is present. GPU keeps its integrator: Replace is CPU-exact
            # (the degradation report notes the GPU approximation), and the GPU MW
            # leg is the light-sampling-blind naive oracle (enableNEE contract,
            # blender_module.cpp:1822) which would only render darker.
            if _route_replace_to_mw(
                    getattr(self, "_has_replace_profile", False),
                    is_outside_visible, active_device, integrator_name):
                integrator_name = "multiwavelength_path_tracer"
                self._degradation_report().approximate(
                    "Spectral Replace material",
                    "routed to multiwavelength integrator for per-λ reflectance")
            renderer.set_integrator(integrator_name)
            has_denoise_pass = False
            if settings.use_denoising and not is_outside_visible:
                denoise_pass = _resolve_denoiser_pass(settings)
                if denoise_pass is not None:
                    renderer.add_pass(denoise_pass)
                    has_denoise_pass = True
            if is_outside_visible and settings.colourmap != 'grayscale':
                renderer.add_pass("colourmap_output")

            # pkg87c — Cryptomatte pass (when either toggle is enabled)
            if (getattr(view_layer, "use_pass_cryptomatte_object", False) or
                    getattr(view_layer, "use_pass_cryptomatte_material", False)):
                depth = int(getattr(settings, "cryptomatte_depth", "6"))
                if hasattr(renderer, "set_cryptomatte_depth"):
                    renderer.set_cryptomatte_depth(depth)
                if hasattr(renderer, "set_cryptomatte_enabled"):
                    renderer.set_cryptomatte_enabled(True)
                renderer.add_pass("cryptomatte")

            # pkg96 P5 guard: detect GPU + CPU-only features
            # (Final render doesn't have AOV selector, but denoise applies)
            _check_gpu_limitations_and_report(
                renderer, settings, self.report,
                has_passes=False,  # Final render AOVs are handled separately
                has_denoise=has_denoise_pass
            )

            pixels = renderer.render(
                settings.samples, settings.max_bounces, progress_callback, False,
                settings.diffuse_bounces, settings.glossy_bounces,
                settings.transmission_bounces, settings.volume_bounces,
                settings.transparent_bounces
            )
            elapsed = time.time() - start_time
            print(f"Render completed in {elapsed:.2f}s")
            try:
                stats = renderer.get_integrator_stats()
                settings.last_render_stats = str(stats) if stats else ""
            except Exception:
                settings.last_render_stats = ""

            if pixels is not None:
                alpha = None
                try:
                    alpha = renderer.get_alpha_buffer()
                except Exception:
                    alpha = None
                layer_name = view_layer.name if view_layer is not None else None
                self.write_pixels(pixels, width, height, alpha, renderer, view_layer, scene, layer_name=layer_name)
        except Exception as e:
            print(f"RENDER ERROR: {e}")
            traceback.print_exc()
        finally:
            # pkg119 Phase C: surface the consolidated "N approximated / M ignored"
            # degradation report ONCE, after convert_scene populated it. Emitted in
            # finally so it lands even if the render itself raised.
            degradation = getattr(self, "_degradation", None)
            if degradation is not None:
                degradation.emit(self.report)
            if renderer:
                try: renderer.clear()
                except: pass
            del renderer

    # ------------------------------------------------------------------ #
    # Viewport preview (rendered shading mode in 3D View)
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    # pkg52: persistent viewport session (pkg116: delegated to Exporter)
    # ------------------------------------------------------------------ #

    def _get_exporter(self):
        """Lazy-init the Exporter. Reused across view_update and view_draw."""
        # Access the real _exporter attribute (not the property)
        if not hasattr(self, '__dict__') or '_exporter' not in self.__dict__ or self.__dict__['_exporter'] is None:
            if exporter_module is None:
                raise RuntimeError("Astroray exporter module not available")
            # Import astroray from module globals. Try sys.modules first (test stubs),
            # then fall back to the module-level astroray import (real Blender).
            import sys
            astroray_mod = sys.modules.get('astroray', None)
            if astroray_mod is None:
                # Fall back to module-level import
                try:
                    import astroray as astroray_mod
                except ImportError:
                    # Create a minimal stub for tests that don't provide astroray
                    import types
                    astroray_mod = types.ModuleType('astroray')
                    astroray_mod.Renderer = lambda: None
            self.__dict__['_exporter'] = exporter_module.Exporter(self, bpy, astroray_mod)
        return self.__dict__['_exporter']

    def _get_viewport_renderer(self):
        """Delegate to Exporter. Kept on RenderEngine for backward compat."""
        return self._get_exporter()._get_viewport_renderer()

    def _reset_viewport_accumulation(self):
        """Delegate to Exporter. Kept on RenderEngine for backward compat."""
        self._get_exporter()._reset_viewport_accumulation()

    @staticmethod
    def _viewport_target_samples(settings):
        return max(1, int(getattr(settings, "preview_samples", 1)))

    @staticmethod
    def _viewport_chunk_samples(settings, current_spp):
        target = CustomRaytracerRenderEngine._viewport_target_samples(settings)
        remaining = max(0, target - int(current_spp))
        chunk = max(1, int(getattr(settings, "viewport_chunk_spp", 1)))
        return min(chunk, remaining)

    def _viewport_render_key(self, context, settings, region):
        lmin, lmax = _wavelength_range_from_settings(settings)
        depth = max(2, settings.max_bounces // 2)
        return (
            self._camera_state_hash(context, region),
            getattr(settings, "viewport_display_pass", "combined"),
            bool(getattr(settings, "viewport_oidn", False)),
            getattr(settings, "denoiser_backend", "auto"),
            round(float(lmin), 3), round(float(lmax), 3),
            getattr(settings, "colourmap", "grayscale"),
            _effective_integrator_name(settings),
            depth,
            min(settings.diffuse_bounces, depth),
            min(settings.glossy_bounces, depth),
            min(settings.transmission_bounces, depth),
            min(settings.volume_bounces, depth),
            min(settings.transparent_bounces, depth),
        )

    def _request_viewport_redraw(self):
        try:
            self.tag_redraw()
        except AttributeError:
            pass

    def _update_viewport_status(self, current_spp, target_spp):
        try:
            self.update_stats(
                "Astroray",
                f"Viewport {current_spp}/{target_spp} spp"
            )
        except AttributeError:
            pass

    @staticmethod
    def _camera_state_hash(context, region):
        """Hash the camera state that would change the rendered image.
        Blender does not emit a "camera moved" event in the viewport, so we
        detect changes by comparing this hash across view_draw calls.

        Includes:
        - 4x4 view matrix (catches orbit/pan/zoom in PERSP/ORTHO views)
        - region width/height
        - space_data.lens (focal length in free perspective)
        - view_camera_zoom and view_camera_offset (CAMERA view zoom/pan)
        - view_perspective ('CAMERA' / 'PERSP' / 'ORTHO')
        """
        rv3d = getattr(context, 'region_data', None)
        space = getattr(context, 'space_data', None)
        if rv3d is None:
            return None
        try:
            mat = rv3d.view_matrix
            # mat[i][j] indexing works for both mathutils.Matrix and our
            # test stubs that wrap a list-of-lists.
            mat_tuple = tuple(round(float(mat[i][j]), 5)
                              for i in range(4) for j in range(4))
        except (AttributeError, IndexError, TypeError):
            return None
        return (
            mat_tuple,
            int(region.width),
            int(region.height),
            round(float(getattr(space, 'lens', 50.0)), 4),
            round(float(getattr(rv3d, 'view_camera_zoom', 0.0)), 4),
            tuple(round(float(o), 5)
                  for o in getattr(rv3d, 'view_camera_offset', (0.0, 0.0))),
            getattr(rv3d, 'view_perspective', 'PERSP'),
        )

    @staticmethod
    def _camera_substantive_state_hash(context, region):
        """Hash the "substantive" camera properties that invalidate prior
        samples and require a full accumulator reset.

        Mirrors Cycles' `BlenderSession::reset` policy
        (intern/cycles/blender/session.cpp, Apache-2.0): progressive samples
        continue across pure camera-transform changes (pan/orbit/dolly), but
        reset when the camera's optical properties change in a way that makes
        prior samples no longer representative.

        Substantive properties (must reset accumulator):
        - focal length / sensor dimensions (changes FOV)
        - lens shift (changes image-plane offset)
        - DoF toggle / aperture fstop (changes bokeh)
        - viewport zoom/offset in CAMERA view (changes effective FOV)
        - region width/height (changes aspect + pixel count)
        - free-view focal length (space_data.lens)

        Not substantive (pure transform, keep accumulating):
        - view_matrix (pan / orbit / dolly in PERSP/ORTHO)
        - camera object world matrix (camera moved but optical unchanged)
        """
        rv3d = getattr(context, 'region_data', None)
        space = getattr(context, 'space_data', None)
        scene = getattr(context, 'scene', None)
        if rv3d is None:
            return None

        # Region dimensions — aspect or pixel count change invalidates samples.
        w = int(region.width)
        h = int(region.height)

        # Free-view (PERSP/ORTHO) uses space_data.lens as the effective focal
        # length. CAMERA view uses the scene camera's lens.
        view_perspective = getattr(rv3d, 'view_perspective', 'PERSP')
        if view_perspective == 'CAMERA' and scene and scene.camera:
            cam_data = scene.camera.data
            focal_length = round(float(getattr(cam_data, 'lens', 50.0)), 4)
            sensor_width = round(float(getattr(cam_data, 'sensor_width', 36.0)), 4)
            sensor_height = round(float(getattr(cam_data, 'sensor_height', 24.0)), 4)
            sensor_fit = str(getattr(cam_data, 'sensor_fit', 'AUTO'))
            shift_x = round(float(getattr(cam_data, 'shift_x', 0.0)), 5)
            shift_y = round(float(getattr(cam_data, 'shift_y', 0.0)), 5)
            dof_enabled = bool(getattr(cam_data.dof, 'use_dof', False))
            aperture_fstop = round(float(getattr(cam_data.dof, 'aperture_fstop', 5.6)), 4) if dof_enabled else 0.0
            # Viewport zoom/offset in CAMERA view changes the effective FOV.
            camera_zoom = round(float(getattr(rv3d, 'view_camera_zoom', 0.0)), 4)
            camera_offset = tuple(round(float(o), 5)
                                  for o in getattr(rv3d, 'view_camera_offset', (0.0, 0.0)))
        else:
            # Free-view: space_data.lens is the focal length; no camera object.
            focal_length = round(float(getattr(space, 'lens', 50.0)), 4)
            sensor_width = 36.0
            sensor_height = 24.0
            sensor_fit = 'AUTO'
            shift_x = 0.0
            shift_y = 0.0
            dof_enabled = False
            aperture_fstop = 0.0
            camera_zoom = 0.0
            camera_offset = (0.0, 0.0)

        return (
            w, h,
            focal_length,
            sensor_width, sensor_height, sensor_fit,
            shift_x, shift_y,
            dof_enabled, aperture_fstop,
            camera_zoom, camera_offset,
            view_perspective,
        )

    # ------------------------------------------------------------------ #
    # pkg56 Phase C — depsgraph-driven dispatch (pkg116: moved to Exporter)
    # ------------------------------------------------------------------ #
    # The implementation lives in exporter.py. These methods are kept on
    # RenderEngine as thin delegators for backward compatibility with tests
    # that call eng._apply_depsgraph_updates() directly.
    # The first frame, an unrecognised update id, or an absent .updates
    # iterator all fall back to `_sync_viewport_scene` — the same
    # has_updates_=true safety net Cycles uses for its first call.

    # Domain → matching bpy.types.ID subclass name. We match by class
    # __name__ (after walking the mro) so the dispatcher works under the
    # stub bpy used in tests as well as real Blender.
    _DEPSGRAPH_ID_TYPE_NAMES = (
        'World', 'Light', 'Material', 'NodeTree', 'ShaderNodeTree',
        'Image', 'Object', 'Scene',
    )

    @classmethod
    def _depsgraph_id_type_name(cls, upd_id):
        """Return the bpy.types.ID subclass name for `upd_id`, or None
        if we can't classify it. Walks the mro so our stub-bpy tests
        (where Object/Light/etc. are plain Python classes) work the
        same way Blender's C-defined types do."""
        if upd_id is None:
            return None
        types_mod = getattr(bpy, 'types', None)
        if types_mod is not None:
            for name in cls._DEPSGRAPH_ID_TYPE_NAMES:
                t = getattr(types_mod, name, None)
                if isinstance(t, type) and isinstance(upd_id, t):
                    return name
        for klass in type(upd_id).__mro__:
            if klass.__name__ in cls._DEPSGRAPH_ID_TYPE_NAMES:
                return klass.__name__
        return None

    @classmethod
    def _classify_depsgraph_update(cls, upd):
        """Map one DepsgraphUpdate into a {domain: True, ...} dict.
        Returns None for an unrecognised id type — caller uses that as
        the signal to fall back to `_sync_viewport_scene` (Cycles' same
        defensive default; sync.cpp's `has_updates_` flag).

        Note: `is_updated_geometry` subsumes `is_updated_transform` —
        rebuilding geometry already covers a moved object. Only
        transform-only edits route to the transform path.
        """
        upd_id = getattr(upd, 'id', None)
        type_name = cls._depsgraph_id_type_name(upd_id)
        if type_name is None:
            return None
        if type_name == 'World':
            return {'environment': True}
        if type_name == 'Light':
            return {'lights': True}
        if type_name in ('Material', 'NodeTree', 'ShaderNodeTree'):
            return {'materials': True}
        if type_name == 'Image':
            return {'materials': True}
        if type_name == 'Scene':
            # pkg96: Scene edits may affect backend config (device_mode) or
            # just accumulation (frame change). Give backend-affecting props
            # a real domain that routes to _configure_backend_for_context,
            # not just accumulation_only (BUG-05).
            return {'backend_config': True, 'accumulation_only': True}
        if type_name == 'Object':
            out = {}
            is_geom = bool(getattr(upd, 'is_updated_geometry', False))
            is_xform = bool(getattr(upd, 'is_updated_transform', False))
            is_shading = bool(getattr(upd, 'is_updated_shading', False))
            if is_geom:
                out['geometry'] = True
            if is_shading:
                out['materials'] = True
            if is_xform and not is_geom:
                out['transform_only'] = True
            return out  # may be empty (selection-only Object update — ignore)
        return None

    def _apply_depsgraph_updates(self, renderer, depsgraph, settings):
        """Delegate to Exporter.apply_depsgraph_updates. Kept on RenderEngine
        for backward compatibility with tests that call this directly."""
        exporter = self._get_exporter()
        report_fn = getattr(self, 'report', None)
        return exporter.apply_depsgraph_updates(
            renderer, depsgraph, settings,
            _configure_backend_for_context, report_fn)

    def _renderer_object_id_for(self, blender_id):
        """Resolve a Blender Object → renderer primitive insertion id.
        Returns None if we have no mapping cached. Phase C ships without
        a per-object id tracker (would require touching `convert_objects`
        which is Phase B's surface, out of scope per CLAUDE.md §3); the
        dispatcher promotes to a geometry rebuild in that case. The hook
        is here so a follow-up package can populate `_renderer_object_id_map`
        in `convert_objects` without re-touching dispatch."""
        m = getattr(self, '_renderer_object_id_map', None)
        if not m:
            return None
        try:
            return m.get(blender_id.name)
        except AttributeError:
            return None

    def _sync_viewport_scene(self, renderer, depsgraph, settings):
        """Delegate to Exporter.sync_viewport_scene. Kept on RenderEngine for
        backward compatibility."""
        exporter = self._get_exporter()
        exporter.sync_viewport_scene(renderer, depsgraph, settings,
                                    _configure_backend_for_context,
                                    _viewport_perf_record,
                                    _effective_integrator_name)

    def _render_viewport_frame(self, renderer, context, settings, region,
                               reset_accumulation=False):
        """Delegate to Exporter.render_viewport_frame. Kept on RenderEngine for
        backward compatibility."""
        exporter = self._get_exporter()
        engine_methods = {
            'viewport_render_key': self._viewport_render_key,
            'viewport_target_samples': self._viewport_target_samples,
            'viewport_chunk_samples': self._viewport_chunk_samples,
            'setup_viewport_camera': self._setup_viewport_camera,
            'wavelength_range_from_settings': _wavelength_range_from_settings,
            'effective_integrator_name': _effective_integrator_name,
            'resolve_denoiser_pass': _resolve_denoiser_pass,
            'check_gpu_limitations_and_report': _check_gpu_limitations_and_report,
            'update_viewport_texture': self._update_viewport_texture,
            'update_viewport_status': self._update_viewport_status,
            # pkg176 Stage 1: native-settings resolver (bpy-facing translator)
            # injected so exporter.py stays import-clean / standalone-loadable.
            'resolve_settings': resolve_native_settings,
        }
        return exporter.render_viewport_frame(renderer, context, settings, region,
                                             reset_accumulation, engine_methods)

    def view_update(self, context, depsgraph):
        """Called when the scene or viewport changes. Re-syncs the scene into
        the persistent viewport renderer and renders one frame.

        Camera-only changes (pan/zoom/orbit) are NOT routed through here by
        Blender — they don't fire a depsgraph update. view_draw owns those.

        pkg116: delegates to Exporter.view_update.
        """
        exporter = self._get_exporter()
        engine_methods = {
            'viewport_render_key': self._viewport_render_key,
            'viewport_target_samples': self._viewport_target_samples,
            'viewport_chunk_samples': self._viewport_chunk_samples,
            'setup_viewport_camera': self._setup_viewport_camera,
            'wavelength_range_from_settings': _wavelength_range_from_settings,
            'effective_integrator_name': _effective_integrator_name,
            'resolve_denoiser_pass': _resolve_denoiser_pass,
            'check_gpu_limitations_and_report': _check_gpu_limitations_and_report,
            'update_viewport_texture': self._update_viewport_texture,
            'update_viewport_status': self._update_viewport_status,
            # pkg176 Stage 1: native-settings resolver (bpy-facing translator)
            # injected so exporter.py stays import-clean / standalone-loadable.
            'resolve_settings': resolve_native_settings,
        }
        exporter.view_update(
            context, depsgraph, RAYTRACER_AVAILABLE,
            _configure_backend_for_context,
            _viewport_perf_record,
            _viewport_perf_frame_complete,
            _effective_integrator_name,
            self._camera_state_hash,
            self._camera_substantive_state_hash,
            self._request_viewport_redraw,
            engine_methods
        )

    def view_draw(self, context, depsgraph):
        """Called every frame inside rendered-shading mode. Detects camera
        changes (pan/zoom/orbit, including CAMERA-view zoom and offset) and
        re-renders without touching scene state. Otherwise just blits the
        cached texture.

        pkg116: delegates to Exporter.view_draw.
        """
        exporter = self._get_exporter()
        engine_methods = {
            'viewport_render_key': self._viewport_render_key,
            'viewport_target_samples': self._viewport_target_samples,
            'viewport_chunk_samples': self._viewport_chunk_samples,
            'setup_viewport_camera': self._setup_viewport_camera,
            'wavelength_range_from_settings': _wavelength_range_from_settings,
            'effective_integrator_name': _effective_integrator_name,
            'resolve_denoiser_pass': _resolve_denoiser_pass,
            'check_gpu_limitations_and_report': _check_gpu_limitations_and_report,
            'update_viewport_texture': self._update_viewport_texture,
            'update_viewport_status': self._update_viewport_status,
            # pkg176 Stage 1: native-settings resolver (bpy-facing translator)
            # injected so exporter.py stays import-clean / standalone-loadable.
            'resolve_settings': resolve_native_settings,
        }
        exporter.view_draw(
            context, depsgraph, RAYTRACER_AVAILABLE,
            _configure_backend_for_context,
            _viewport_perf_record,
            _viewport_perf_frame_complete,
            _effective_integrator_name,
            self._camera_state_hash,
            self._camera_substantive_state_hash,
            self._request_viewport_redraw,
            engine_methods,
        )

    @staticmethod
    def _camera_view_zoom_scale(view_camera_zoom):
        """Cycles formula (intern/cycles/blender/blender_camera.cpp):
        `scale = 2.0 / (1.41421 + zoom/50)^2`. At zoom=0 → 1.0 (no change).
        Smaller scale → narrower FOV (zoom in). Used to make CAMERA-view
        wheel-zoom actually change the rendered image, instead of staying
        locked at the camera's natural framing."""
        denom = 1.41421 + float(view_camera_zoom) / 50.0
        if abs(denom) < 1e-6:
            return 1.0
        return 2.0 / (denom * denom)

    def _setup_viewport_camera(self, renderer, context, width, height):
        """Build a lookFrom/lookAt from the 3D View's RegionView3D state.

        P4 fix (BUG-08): derives vfov from Blender's window_matrix (when available)
        instead of re-deriving from a hardcoded sensor_width guess, so the rendered
        framing matches Blender's viewport overlay by construction.

        - In CAMERA view (numpad 0): use the scene camera, then apply the
          viewport-only `view_camera_zoom` and `view_camera_offset` so
          wheel-zoom and pan actually change the rendered framing.
        - In PERSP / ORTHO view: derive position + direction from
          `rv3d.view_matrix.inverted()` and vfov from `rv3d.window_matrix`.
        """
        rv3d = context.region_data
        space = context.space_data

        if rv3d is not None and rv3d.view_perspective == 'CAMERA' and context.scene.camera:
            zoom_scale = self._camera_view_zoom_scale(getattr(rv3d, 'view_camera_zoom', 0.0))
            offset = getattr(rv3d, 'view_camera_offset', (0.0, 0.0))
            # P4 fix (BUG-08): pass rv3d so _apply_camera can use window_matrix
            self._apply_camera(renderer, context.scene.camera, width, height,
                               vfov_scale=zoom_scale,
                               viewport_shift=(float(offset[0]), float(offset[1])),
                               rv3d=rv3d)
            return

        view_inv = rv3d.view_matrix.inverted()
        loc = view_inv.translation
        rot = view_inv.to_3x3()
        forward = rot @ mathutils.Vector((0.0, 0.0, -1.0))
        up      = rot @ mathutils.Vector((0.0, 1.0,  0.0))

        look_from = [loc.x, loc.y, loc.z]
        look_at   = [loc.x + forward.x, loc.y + forward.y, loc.z + forward.z]
        vup       = [up.x, up.y, up.z]

        # P4 fix (BUG-08): extract vfov from Blender's window_matrix (projection-only)
        # instead of re-deriving from a hardcoded 32mm sensor. This ensures the
        # rendered framing equals Blender's viewport overlay.
        # window_matrix[1][1] = 1 / tan(vfov/2) for a symmetric frustum (OpenGL convention).
        aspect = width / max(1, height)
        if hasattr(rv3d, 'window_matrix'):
            # window_matrix is the pure projection; perspective_matrix = window_matrix @ view_matrix
            # couples view rotation into [1][1], causing vfov to vary with camera orbit.
            proj = rv3d.window_matrix
            if abs(proj[1][1]) > 1e-6:
                vfov = math.degrees(2.0 * math.atan(1.0 / proj[1][1]))
            else:
                # Fallback: derive from space_data.lens (rare edge case).
                # BUG-08 fix 2026-05-27: was 32.0, mismatching the 36mm
                # default used by `_apply_camera`'s `_compute_vfov_degrees`
                # path. Changed to 36.0 so the fallback agrees with the
                # camera-datablock path when both fire on the same camera.
                lens = getattr(space, 'lens', 50.0)
                sensor_width = 36.0
                hfov = 2.0 * math.atan(sensor_width / (2.0 * lens))
                vfov = math.degrees(2.0 * math.atan(math.tan(hfov / 2.0) / aspect))
        else:
            # Pre-2.80 fallback (window_matrix may not exist). Same BUG-08
            # consistency fix as the inner fallback above.
            lens = getattr(space, 'lens', 50.0)
            sensor_width = 36.0
            hfov = 2.0 * math.atan(sensor_width / (2.0 * lens))
            vfov = math.degrees(2.0 * math.atan(math.tan(hfov / 2.0) / aspect))

        renderer.setup_camera(look_from, look_at, vup, vfov, aspect,
                              0.0, 10.0, width, height)

    def _update_viewport_texture(self, pixels, width, height):
        import gpu
        # Flip vertically — Blender's GPU draw expects row 0 = bottom.
        rgba = np.ones((height, width, 4), dtype=np.float32)
        rgba[:, :, :3] = pixels
        rgba = np.ascontiguousarray(rgba[::-1])
        flat = rgba.reshape(-1)
        buf = gpu.types.Buffer('FLOAT', flat.shape[0], flat.tolist())
        # Update via properties (which proxy to exporter)
        self._viewport_texture = gpu.types.GPUTexture(
            (width, height), format='RGBA16F', data=buf)
        self._viewport_width = width
        self._viewport_height = height

    def convert_scene(self, depsgraph, renderer, width, height, resolved=None):
        scene = depsgraph.scene
        renderer.clear()
        # pkg176 Stage 1: `resolved` is the native-settings view built by
        # render(); resolve here (silently) when called directly (tests/scripts).
        settings = resolved if resolved is not None else resolve_native_settings(scene)
        renderer.set_clamp_direct(settings.clamp_direct)
        renderer.set_clamp_indirect(settings.clamp_indirect)
        renderer.set_filter_glossy(settings.filter_glossy)
        renderer.set_use_reflective_caustics(settings.use_reflective_caustics)
        renderer.set_use_refractive_caustics(settings.use_refractive_caustics)
        renderer.set_light_sampler(settings.light_sampler)
        cycles = getattr(scene, 'cycles', None)
        render_settings = getattr(scene, 'render', None)
        exposure = float(getattr(cycles, 'film_exposure', 1.0)) if cycles else 1.0
        renderer.set_film_exposure(exposure)
        use_transparent_film = bool(getattr(render_settings, 'film_transparent', False)) if render_settings else False
        transparent_glass = bool(getattr(cycles, 'film_transparent_glass', False)) if cycles else False
        renderer.set_use_transparent_film(use_transparent_film)
        renderer.set_transparent_glass(transparent_glass)

        # ORDER IS LOAD-BEARING (fixed in PR #525) — setup_camera MUST run before
        # the motion-blur block below, and must NOT be moved back after it:
        #   1. `renderer.clear()` above does `camera.reset()`, so without this the
        #      very next `set_camera_motion_blur` raises "Camera not set up" and
        #      the render dies the moment a user ticks Motion Blur on.
        #   2. `Renderer::setupCamera` CONSTRUCTS A NEW Camera, carrying over only
        #      pkg72's prev-frame snapshot -- NOT the shutter fields. So a
        #      setup_camera placed AFTER set_camera_motion_blur would silently
        #      reset shutter to its 0.0f default (= blur off) rather than crash,
        #      which is strictly worse than the crash.
        # Nothing between here and the old call site touches camera state
        # (set_seed / set_pixel_filter / clamps / exposure all live on Renderer),
        # so hoisting it is side-effect-free.
        self.setup_camera(scene, renderer, width, height)

        # pkg103b: Camera motion blur wiring (requires pkg88-A renderer support)
        # Cycles reference: intern/cycles/blender/camera.cpp::BlenderSync::sync_camera_motion (Apache-2.0)
        # pkg88-B (object motion blur, addon-only bake) hangs off the SAME
        # shutter/shutter_position resolution below so object and camera blur
        # agree, per the pkg88 spec's Phase-B requirement.
        motion_start_matrices = {}
        motion_end_matrices = {}
        if render_settings and getattr(render_settings, 'use_motion_blur', False):
            shutter = float(getattr(render_settings, 'motion_blur_shutter', 0.5))
            position = getattr(render_settings, 'motion_blur_position', 'CENTER')
            frame = float(scene.frame_current)

            # Compute shutter start/end times (Blender convention)
            if position == 'START':
                t_start, t_end = frame, frame + shutter
            elif position == 'CENTER':
                t_start, t_end = frame - shutter / 2.0, frame + shutter / 2.0
            elif position == 'END':
                t_start, t_end = frame - shutter, frame
            else:
                t_start, t_end = frame, frame + shutter  # fallback to START

            cam_obj = scene.camera
            if cam_obj is not None:
                # Evaluate camera transform at shutter boundaries
                T_start = self._get_camera_transform_at_time(scene, depsgraph, cam_obj, t_start)
                T_end = self._get_camera_transform_at_time(scene, depsgraph, cam_obj, t_end)

                # Decompose transforms into T/R/S (pkg88-A requires decomposed components)
                loc_start, rot_start, scale_start = T_start.decompose()
                loc_end, rot_end, scale_end = T_end.decompose()

                # Convert to lists for pybind (quaternion: [w,x,y,z], translation/scale: [x,y,z])
                start_t = [loc_start.x, loc_start.y, loc_start.z]
                start_r = [rot_start.w, rot_start.x, rot_start.y, rot_start.z]
                start_s = [scale_start.x, scale_start.y, scale_start.z]
                end_t = [loc_end.x, loc_end.y, loc_end.z]
                end_r = [rot_end.w, rot_end.x, rot_end.y, rot_end.z]
                end_s = [scale_end.x, scale_end.y, scale_end.z]

                # Map Blender position enum to renderer convention (0=Start, 1=Center, 2=End)
                position_map = {'START': 0, 'CENTER': 1, 'END': 2}
                shutter_position = position_map.get(position, 0)

                renderer.set_camera_motion_blur(start_t, start_r, start_s, end_t, end_r, end_s,
                                                shutter, shutter_position)

            # pkg88-B: snapshot every real (non-dupli) mesh-able object's
            # matrix_world at BOTH shutter boundaries, one depsgraph evaluation
            # per time value -- exactly mirroring the camera path above, which
            # calls _get_camera_transform_at_time once for t_start and once for
            # t_end. Both endpoints are required: the renderer blends
            # positions_start at ray time=0 and positions_end at time=1
            # (Triangle::hit, include/astroray/shapes.h), and Camera::getRay maps
            # that same time across t_start -> t_end. Feeding the CURRENT
            # (frame) pose as positions_start would desync object motion from
            # camera motion for CENTER, and would make END a silent no-op
            # (t_end == frame, so the object would never register as moving).
            # Q2: bake rigid transforms into per-vertex motion at the addon
            # boundary -- Astroray has no first-class instance/animated-transform
            # system. Dupli/particle/geometry-node instances are excluded here
            # (depsgraph.objects yields real objects only); see convert_objects'
            # docstring for the pkg114-instancing interaction.
            candidate_names = {
                obj.name for obj in (getattr(depsgraph, 'objects', None) or [])
                if getattr(obj, 'type', None) in {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'}
            }
            if candidate_names:
                motion_start_matrices = self._get_object_matrices_at_time(
                    scene, depsgraph, candidate_names, t_start)
                motion_end_matrices = self._get_object_matrices_at_time(
                    scene, depsgraph, candidate_names, t_end)

        seed = int(getattr(cycles, 'seed', 0)) if cycles else 0
        use_animated_seed = bool(getattr(cycles, 'use_animated_seed', False)) if cycles else False
        if use_animated_seed:
            seed = seed + scene.frame_current
        renderer.set_seed(seed)
        filter_type_map = {'BOX': 0, 'GAUSSIAN': 1, 'BLACKMAN_HARRIS': 2}
        filter_type_str = getattr(cycles, 'pixel_filter_type', 'GAUSSIAN') if cycles else 'GAUSSIAN'
        filter_type = filter_type_map.get(filter_type_str, 1)
        filter_width = float(getattr(cycles, 'filter_width', 1.5)) if cycles else 1.5
        renderer.set_pixel_filter(filter_type, filter_width)
        # setup_camera was hoisted above the motion-blur block -- see the
        # ORDER IS LOAD-BEARING note there before reinstating a call here.
        material_map = self.convert_materials(depsgraph, renderer)
        self.convert_objects(depsgraph, renderer, material_map,
                             motion_start_matrices, motion_end_matrices)
        self.convert_lights(depsgraph, renderer)
        self.setup_world(scene, renderer)

    def setup_camera(self, scene, renderer, width, height):
        cam_obj = scene.camera
        if not cam_obj: return
        self._apply_camera(renderer, cam_obj, width, height)

    def _get_camera_transform_at_time(self, scene, depsgraph, cam_obj, frame):
        """Evaluate depsgraph at `frame` and return camera.matrix_world.

        Cycles reference: intern/cycles/blender/camera.cpp::BlenderSync::sync_camera_motion (Apache-2.0).
        Temporarily sets scene.frame_current to the requested time, updates the depsgraph,
        and samples the camera transform. Restores the original frame before returning.
        """
        original_frame = scene.frame_current
        original_subframe = scene.frame_subframe
        try:
            # Set scene to target frame (Blender accepts fractional frames)
            scene.frame_set(int(frame), subframe=frame - int(frame))
            # Force depsgraph to update at the new time
            depsgraph.update()
            # Sample the evaluated camera transform
            evaluated_camera = cam_obj.evaluated_get(depsgraph)
            matrix = evaluated_camera.matrix_world.copy()  # mathutils.Matrix (4x4)
            return matrix
        finally:
            # Restore original frame state
            scene.frame_set(int(original_frame), subframe=original_subframe)
            depsgraph.update()

    def _get_object_matrices_at_time(self, scene, depsgraph, obj_names, frame):
        """pkg88-B: evaluate depsgraph at `frame` and return {obj.name:
        matrix_world} for every name in `obj_names`, in ONE frame_set/
        depsgraph.update() round trip (unlike `_get_camera_transform_at_time`,
        which is called per-object by design for the single camera -- doing
        that per OBJECT here would mean one full depsgraph re-cook per
        animated mesh). Same restore-the-original-frame contract.
        """
        original_frame = scene.frame_current
        original_subframe = scene.frame_subframe
        try:
            scene.frame_set(int(frame), subframe=frame - int(frame))
            depsgraph.update()
            result = {}
            for obj in depsgraph.objects:
                if obj.name in obj_names:
                    result[obj.name] = obj.matrix_world.copy()
            return result
        finally:
            scene.frame_set(int(original_frame), subframe=original_subframe)
            depsgraph.update()

    def _compute_vfov_degrees(self, camera, width, height):
        """Vertical FOV in degrees for a Blender camera datablock.

        Cycles/Eevee pick the sensor axis from `sensor_fit`, then derive the
        image FOV from `lens` (focal length). We need VERTICAL FOV specifically
        because the raytracer's Camera class uses it to compute the view
        frustum height. So for HORIZONTAL/AUTO-wide fits we convert hfov→vfov
        using the final image aspect."""
        if camera.type != 'PERSP':
            # ORTHO / PANO: fall back to a plausible vfov so at least the
            # scene is visible. A full ortho-camera implementation would
            # require plumbing an orthographic flag into the C++ camera.
            return 40.0

        aspect = width / max(1, height)
        fit = camera.sensor_fit
        # AUTO picks the axis with the larger image dimension
        if fit == 'AUTO':
            fit = 'HORIZONTAL' if width >= height else 'VERTICAL'

        if fit == 'VERTICAL':
            sensor = camera.sensor_height
            vfov_rad = 2.0 * math.atan(sensor / (2.0 * camera.lens))
        else:  # HORIZONTAL
            sensor = camera.sensor_width
            hfov_rad = 2.0 * math.atan(sensor / (2.0 * camera.lens))
            vfov_rad = 2.0 * math.atan(math.tan(hfov_rad / 2.0) / aspect)
        return math.degrees(vfov_rad)

    def _apply_camera(self, renderer, cam_obj, width, height, vfov_scale=1.0,
                      viewport_shift=(0.0, 0.0), rv3d=None):
        """Extract lookFrom/lookAt/vup from a Blender camera object and push
        it to the renderer. Blender cameras point along their local -Z and
        use local +Y as 'up'; we rotate those unit vectors by the camera's
        world rotation to get world-space directions.

        P4 fix (BUG-08): when called from viewport code with rv3d, derives vfov
        from rv3d.window_matrix (after zoom scaling) instead of re-deriving
        from the camera datablock's sensor/lens, so the rendered framing matches
        Blender's viewport overlay.

        `vfov_scale` (default 1.0) shrinks the effective image plane. Used by
        viewport CAMERA-view wheel-zoom to narrow the FOV without changing
        the scene camera (pkg52). 1.0 = no change; <1.0 = zoom in.

        `viewport_shift` is the CAMERA-view pan offset from RegionView3D. It
        is added to the camera datablock's own shift and passed as an
        image-plane shift to the C++ camera.

        `rv3d` (optional): when present, vfov is extracted from rv3d.window_matrix
        instead of re-deriving from camera sensor/lens (P4 fix for viewport alignment).
        """
        matrix = cam_obj.matrix_world
        loc, rot_quat, _scale = matrix.decompose()

        forward = rot_quat @ mathutils.Vector((0.0, 0.0, -1.0))
        up      = rot_quat @ mathutils.Vector((0.0, 1.0,  0.0))

        look_from = [loc.x, loc.y, loc.z]
        look_at   = [loc.x + forward.x, loc.y + forward.y, loc.z + forward.z]
        vup       = [up.x, up.y, up.z]

        camera = cam_obj.data

        # pkg193: reproduce Blender's camera projection EXACTLY so the rendered
        # framing matches the viewport overlay (numpad-0) and the F12 render.
        #
        # VIEWPORT (rv3d present, valid window_matrix): Blender's camera-view
        # window_matrix is an off-center (asymmetric) perspective frustum whose
        # principal-point shift bakes in lens shift + view pan/zoom + sensor-fit
        # letterboxing. Astroray's symmetric-vfov+shift camera reproduces ANY
        # axis-aligned perspective frustum exactly (4 dof: vfov, aspect, shiftX,
        # shiftY), so we invert OpenGL perspective_m4:
        #     vfov   = 2*atan(1/m11)            (m11 = 2n/(t-b) = 1/tan(vfov/2))
        #     aspect = m11/m00                  (= (r-l)/(t-b))
        #     shiftX = m02/2 = (r+l)/(2(r-l)) ; shiftY = m12/2 = (t+b)/(2(t-b))
        # where m02/m12 are window_matrix[0][2]/[1][2] (mathutils row-major). The
        # window_matrix ALREADY contains view_camera_zoom, view_camera_offset AND
        # the datablock shift, so they must NOT be re-added (the pre-pkg193 code
        # dropped m02/m12 and re-derived shift from datablock+pan, measuring
        # 25-223 px of overlay offset under lens shift / non-AUTO sensor fit).
        # Verified 0.00 px vs Blender 5.1 window_matrix over 8 conditions.
        proj = rv3d.window_matrix if (rv3d is not None and hasattr(rv3d, 'window_matrix')) else None
        if proj is not None and abs(proj[1][1]) > 1e-6 and abs(proj[0][0]) > 1e-6:
            vfov = math.degrees(2.0 * math.atan(1.0 / proj[1][1]))
            aspect = proj[1][1] / proj[0][0]
            shift_x = proj[0][2] / 2.0
            shift_y = proj[1][2] / 2.0
        else:
            # F12 batch render (rv3d=None) or degenerate window_matrix: derive from
            # the camera datablock. Cycles blender_camera_viewplane (Apache-2.0)
            # offsets the viewplane by dx = shift_x*viewfac, dy = shift_y*viewfac
            # with viewfac = winx for a HORIZONTAL sensor fit else ycor*winy. In
            # Astroray's frame-fraction shift units that is shift_x*viewfac/winx and
            # shift_y*viewfac/winy; WITHOUT this film-fit scaling the F12 render was
            # 20-42 px off the camera frame (Blender world_to_camera_view) for
            # shifted / non-square cameras (pkg193; verified 0.00 px on 8 conditions).
            vfov = self._compute_vfov_degrees(camera, width, height)
            # Apply viewport zoom by scaling the image plane → tighter FOV.
            if vfov_scale != 1.0 and vfov_scale > 0.0:
                half = math.radians(vfov) / 2.0
                vfov = math.degrees(2.0 * math.atan(math.tan(half) * vfov_scale))
            aspect = width / max(1, height)
            fit = getattr(camera, "sensor_fit", "AUTO")
            if fit == 'AUTO':
                fit = 'HORIZONTAL' if width >= height else 'VERTICAL'
            viewfac = width if fit == 'HORIZONTAL' else height
            shift_x = (float(getattr(camera, "shift_x", 0.0)) * viewfac / max(1, width)
                       + float(viewport_shift[0]))
            shift_y = (float(getattr(camera, "shift_y", 0.0)) * viewfac / max(1, height)
                       + float(viewport_shift[1]))

        aperture, focus_dist = 0.0, 10.0
        if camera.dof.use_dof:
            if camera.dof.aperture_fstop > 0:
                # Cycles intern/cycles/blender/camera.cpp::BlenderCamera::sync (Apache-2.0):
                # aperture_radius = (focal_length_m) / (2 * fstop). camera.lens is in mm.
                focal_length_m = float(camera.lens) * 1e-3
                aperture_radius = focal_length_m / (2.0 * float(camera.dof.aperture_fstop))
                # C++ Camera takes diameter (lensRadius = aperture/2), so pass 2x.
                aperture = 2.0 * aperture_radius
            if camera.dof.focus_object:
                focus_dist = (loc - camera.dof.focus_object.matrix_world.translation).length
            else:
                focus_dist = camera.dof.focus_distance

        renderer.setup_camera(look_from, look_at, vup, vfov,
                              aspect,
                              aperture, focus_dist, width, height,
                              shift_x, shift_y)

    def convert_materials(self, depsgraph, renderer):
        # In Blender 5.0+ every material is node-based (use_nodes is deprecated
        # and always True), so we always go through the node tree conversion.
        material_map = {}
        self._volume_material_map = {}
        # pkg178 Stage 5: resolve the Principled routing flag once per conversion
        # (default ON — see use_native_principled). Stored on the engine so the
        # per-material helpers reach it without re-plumbing the scene through
        # every call site.
        _settings = getattr(depsgraph.scene, "custom_raytracer", None)
        self._use_native_principled_flag = bool(
            getattr(_settings, "use_native_principled", True))
        # pkg195 Stage C: whether this render targets the GPU (for the Replace-mode
        # spectral degradation note — GPU keeps ExtendOnly semantics).
        self._device_is_gpu = (
            bool(getattr(renderer, "_use_gpu", False))
            or getattr(_settings, "device_mode", "auto") == "gpu")
        # pkg195 Stage C: set True when any material gets a Replace-mode authored
        # spectrum, so render() can route the visible-band CPU render to the MW
        # integrator (the only transport that consults evalSpectralExt in-band).
        self._has_replace_profile = False
        # pkg115 generated-coords: textures created in GENERATED mode while
        # converting a material are recorded per material name so
        # convert_objects can bake each using object's bounding box onto them
        # (Blender Texture Coordinate > Generated semantics).
        self._generated_textures_by_material = {}
        for mat in bpy.data.materials:
            self._current_material_name = mat.name
            mat_id = self.convert_node_material(mat, renderer)
            material_map[mat.name] = mat_id
            # pkg87c — Set material name for Cryptomatte hashing
            if hasattr(renderer, "set_material_name"):
                renderer.set_material_name(mat_id, mat.name)
        return material_map

    def convert_node_material(self, mat, renderer):
        """Convert a Blender material to Astroray.

        Uses `material.inline_shader_nodes()` (Blender 5.0+) to get a flattened
        node tree with node groups inlined, reroutes removed, and muted nodes
        stripped — this is a MUCH more robust starting point than walking the
        raw user node tree. Falls back to `mat.node_tree` on older Blender.
        """
        # CRITICAL: keep `inlined` alive while accessing `node_tree`. When it's
        # garbage collected the node_tree reference becomes invalid, so we store
        # it locally and only let it drop after this function returns.
        def _apply_spectral_profile(material_id):
            try:
                # pkg195 Stage C: a source node (Drawn / Spectrum Preset / Spectral
                # Profile) wired to a Surface registers+attaches its profile with an
                # explicit mode (Replace for reflectance sources, ExtendOnly for the
                # IR/UV band wrapper). Honor that over the pkg58 material-panel
                # fallback, which stays ExtendOnly and must NOT clobber it.
                node_prof = getattr(self, "_current_node_profile", None)
                if node_prof is not None:
                    name, replace = node_prof
                    if name and hasattr(renderer, "set_material_spectral_profile"):
                        renderer.set_material_spectral_profile(material_id, name, replace)
                        if replace:
                            self._has_replace_profile = True
                            # Replace mode is CPU-exact only; the GPU MW kernel keeps
                            # ExtendOnly semantics (out-of-band only) — report the drop.
                            if getattr(self, "_device_is_gpu", False):
                                self._degradation_report().ignore(
                                    "Spectral Replace mode",
                                    "GPU renders out-of-band only; CPU is exact")
                    return material_id
                mat_settings = getattr(mat, "custom_raytracer", None)
                profile = getattr(mat_settings, "spectral_profile", "__none__") if mat_settings else "__none__"
                if (hasattr(renderer, "set_material_spectral_profile") and
                        hasattr(renderer, "clear_material_spectral_profile")):
                    if profile and profile != "__none__":
                        renderer.set_material_spectral_profile(material_id, profile)
                    else:
                        renderer.clear_material_spectral_profile(material_id)
            except Exception:
                pass
            return material_id
        self._current_node_profile = None

        # P3-c probe & fix (BUG-09): inline_shader_nodes() may strip custom node
        # subclasses. Check the original tree for Astroray nodes; if present but
        # absent in the flattened tree, use the original for detection. This ensures
        # custom nodes reach the converter even if flattening removes them.
        original_tree = getattr(mat, 'node_tree', None)
        inlined = None
        try:
            inlined = mat.inline_shader_nodes()
            node_tree = inlined.node_tree
        except (AttributeError, RuntimeError):
            # Pre-5.0 Blender: fall back to direct access
            node_tree = original_tree
        if node_tree is None:
            return _apply_spectral_profile(renderer.create_material('disney', [0.8, 0.8, 0.8], {}))

        # P3-c: defensive custom-node detection. Check both trees; prefer the one
        # that actually contains the node. If flattening stripped it, detect on original.
        astroray_out = next(
            (n for n in node_tree.nodes if getattr(n, 'bl_idname', None) == 'AstrorayOutputNode'),
            None,
        )
        if astroray_out is None and original_tree is not None and original_tree != node_tree:
            # Not in flattened tree; check original (P3-c fallback for flatten-stripped nodes)
            astroray_out = next(
                (n for n in original_tree.nodes if getattr(n, 'bl_idname', None) == 'AstrorayOutputNode'),
                None,
            )
            if astroray_out is not None:
                # Custom node survived only in original tree — use original for conversion
                node_tree = original_tree

        if astroray_out is not None:
            return _apply_spectral_profile(
                self.convert_astroray_output(astroray_out, renderer, node_tree, mat))

        # Find the active output node (preferred), or any OUTPUT_MATERIAL
        output = None
        for node in node_tree.nodes:
            if node.type == 'OUTPUT_MATERIAL' and getattr(node, 'is_active_output', True):
                output = node
                break
        if output is None:
            output = next((n for n in node_tree.nodes if n.type == 'OUTPUT_MATERIAL'), None)
        if output is None:
            return _apply_spectral_profile(renderer.create_material('disney', [0.8, 0.8, 0.8], {}))

        volume_input = output.inputs.get('Volume')
        volume_spec = None
        if volume_input and volume_input.is_linked:
            volume_spec = self.convert_volume_node(volume_input.links[0].from_node, node_tree)
        self._volume_material_map[mat.name] = volume_spec

        surface_input = output.inputs.get('Surface')
        if not surface_input or not surface_input.is_linked:
            if volume_spec is not None:
                # Volume-only materials should keep the boundary mostly invisible.
                return _apply_spectral_profile(renderer.create_material('glass', [1.0, 1.0, 1.0], {'ior': 1.0}))
            return _apply_spectral_profile(renderer.create_material('disney', [0.8, 0.8, 0.8], {}))

        shader_node = surface_input.links[0].from_node
        # A native Astroray node (Sellmeier Glass, Blackbody/Spectral source,
        # IR/UV, NRC hint) wired straight into the stock Material Output must
        # convert identically to the AstrorayOutputNode path — otherwise it
        # falls through to convert_shader_node and silently renders neutral grey
        # (the #1 "spectral/dispersion nodes don't work" report). See the
        # shared _convert_astroray_native_surface helper.
        native = self._convert_astroray_native_surface(shader_node, mat, renderer, node_tree)
        if native is not None:
            return _apply_spectral_profile(native)
        return _apply_spectral_profile(self.convert_shader_node(shader_node, renderer, node_tree))

    # ------------------------------------------------------------------ #
    # pkg57: Astroray-native node tree conversion.
    # Mirrors the dispatch shape of convert_shader_node + _principled_shader_spec
    # so the new path reads like the existing one.
    # ------------------------------------------------------------------ #

    def convert_astroray_output(self, output_node, renderer, node_tree, mat):
        """Resolve the BSDF wired into an AstrorayOutputNode → material id."""
        surface_input = output_node.inputs.get('Surface')
        if not surface_input or not surface_input.is_linked:
            # No surface wired — fall back to a neutral disney to keep the
            # frame renderable (mirrors the OUTPUT_MATERIAL no-surface branch).
            return renderer.create_material('disney', [0.8, 0.8, 0.8], {})

        wired = surface_input.links[0].from_node
        native = self._convert_astroray_native_surface(wired, mat, renderer, node_tree)
        if native is not None:
            return native
        # Cycles / standalone fallback: dispatch through the existing path.
        return self.convert_shader_node(wired, renderer, node_tree)

    def _convert_astroray_native_surface(self, wired, mat, renderer, node_tree):
        """Dispatch an Astroray-native surface node to its material builder.

        Returns a material id, or None when `wired` is not a recognized native
        node (the caller then falls back to convert_shader_node). Shared by
        convert_astroray_output (the AstrorayOutputNode path) AND
        convert_node_material's standard Material Output path, so a native node
        renders identically no matter which output it is wired into. This
        matches the Cycles workflow, where users wire everything to the stock
        "Material Output" — without this, a native node on Material Output fell
        through to convert_shader_node and silently rendered neutral grey.
        """
        bl_idname = getattr(wired, 'bl_idname', '')
        if bl_idname == 'AstrorayShaderNodeSellmeierGlass':
            return self._create_astroray_material(
                self._astroray_sellmeier_spec(wired, mat), renderer, node_tree)
        if bl_idname == 'AstrorayShaderNodeIrUvResponse':
            return self._astroray_ir_uv_material(wired, mat, renderer, node_tree)
        if bl_idname == 'AstrorayShaderNodeNrcHint':
            return self._create_astroray_material(
                self._astroray_nrc_hint_spec(wired, mat, renderer), renderer, node_tree)
        if bl_idname in ('AstrorayShaderNodeSpectralProfile',
                         'AstrorayShaderNodeSpectrumPreset',
                         'AstrorayShaderNodeDrawnSpectrum'):
            # pkg195 Stage C: a spectrum SOURCE node wired to Surface produces a
            # neutral white diffuse whose per-λ reflectance is the authored
            # spectrum, attached in Replace mode (drives all λ, bypassing the JH
            # RGB round trip). _register_source_node_profile records the profile
            # + mode into self._current_node_profile for _apply_spectral_profile.
            self._register_source_node_profile(wired, mat)
            return self._create_astroray_material(
                {'kind': 'astroray_spectral_only'}, renderer, node_tree)
        return None

    def _register_source_node_profile(self, node, mat):
        """pkg195 Stage C: resolve a spectrum source node to a profile NAME and
        record (name, replace=True) in self._current_node_profile. Drawn nodes
        register their curve as a runtime profile first; Preset/Spectral Profile
        nodes name a DB profile directly."""
        self._current_node_profile = None
        bl_idname = getattr(node, 'bl_idname', '')
        name = ''
        if bl_idname == 'AstrorayShaderNodeDrawnSpectrum':
            name = self._register_drawn_spectrum(node, mat)
        elif bl_idname == 'AstrorayShaderNodeSpectrumPreset':
            prof = getattr(node, 'profile', '') or ''
            name = prof if prof and prof != '__none__' else ''
        else:  # AstrorayShaderNodeSpectralProfile
            name = self._astroray_read_profile(node, mat)
        if name:
            self._current_node_profile = (name, True)  # Replace mode

    def _register_drawn_spectrum(self, node, mat):
        """Evaluate a Drawn Spectrum node's CurveMapping at 5 nm and register it as
        a runtime profile under __blend__/<mat>/<node>. Returns the name, or ''."""
        if (not RAYTRACER_AVAILABLE or astroray_nodes is None
                or not hasattr(astroray, 'register_spectral_profile')):
            return ''
        sampler = getattr(astroray_nodes, 'sample_drawn_spectrum', None)
        if sampler is None:
            return ''
        try:
            sampled = sampler(node)
        except Exception:
            sampled = None
        if not sampled:
            return ''
        lmin, step, values = sampled
        owner = getattr(mat, 'name', 'material') or 'material'
        name = f"__blend__/{owner}/{getattr(node, 'name', 'drawn')}"
        try:
            if not astroray.register_spectral_profile(name, lmin, step, list(values)):
                return ''
        except Exception:
            return ''
        return name

    def _astroray_read_profile(self, node, mat):
        """Read the spectral profile name from an AstroraySpectralProfile node,
        falling back to mat.custom_raytracer.spectral_profile when empty."""
        prof = getattr(node, 'profile', '') or ''
        if not prof or prof == '__none__':
            crt = getattr(mat, 'custom_raytracer', None)
            prof = getattr(crt, 'spectral_profile', '') if crt else ''
        return prof if prof and prof != '__none__' else ''

    def _astroray_sellmeier_spec(self, node, mat):
        """Build a spec dict for the dielectric (Sellmeier) plugin."""
        tint_socket = node.inputs.get('Tint')
        tint = [1.0, 1.0, 1.0]
        if tint_socket is not None and not tint_socket.is_linked:
            try:
                tint = list(tint_socket.default_value)[:3]
            except (TypeError, IndexError):
                pass
        spec = {
            'kind': 'astroray_sellmeier',
            'tint': tint,
            'use_preset': bool(getattr(node, 'use_preset', True)),
            'preset': getattr(node, 'preset', '') or '',
            'ior': float(getattr(node, 'ior_design', 1.5168)),
        }
        # Carry the manual B/C overrides from socket defaults (the dielectric
        # plugin currently consumes the preset; B/C plumbing remains a
        # forward-compatibility carry until the plugin grows raw-coefficient
        # parameters — flagged in the package note).
        b_socket = node.inputs.get('Sellmeier B')
        c_socket = node.inputs.get('Sellmeier C')
        try:
            if b_socket is not None and not b_socket.is_linked:
                spec['sellmeier_b'] = list(b_socket.default_value)[:3]
            if c_socket is not None and not c_socket.is_linked:
                spec['sellmeier_c'] = list(c_socket.default_value)[:3]
        except (TypeError, IndexError):
            pass
        # Material-level fallback preset (pkg37-era materials).
        if not spec['preset']:
            astro = getattr(mat, 'astroray', None)
            spec['preset'] = getattr(astro, 'sellmeier_preset', '') if astro else ''
        return spec

    def _astroray_ir_uv_material(self, node, mat, renderer, node_tree):
        """pkg195 Stage C: NON-DESTRUCTIVE IR/UV Response. The wired base BSDF
        converts normally (base colour preserved — the pkg57 grey-Disney
        promotion is gone), and the node only attaches a constant-band ExtendOnly
        profile built from its band + reflectance. Because ExtendOnly touches only
        λ outside [380,780] nm, the visible render is pixel-identical to the base
        with no node present."""
        surface_in = node.inputs.get('Surface')
        if surface_in is not None and surface_in.is_linked:
            base_id = self.convert_shader_node(
                surface_in.links[0].from_node, renderer, node_tree)
        else:
            # No base wired — neutral diffuse, still non-destructive.
            base_id = renderer.create_material('disney', [0.8, 0.8, 0.8], {})
        band = getattr(node, 'band', 'ir')
        reflectance = float(getattr(node, 'reflectance', 0.5))
        name = self._register_ir_uv_band_profile(node, mat, band, reflectance)
        if name:
            self._current_node_profile = (name, False)  # ExtendOnly (out-of-band)
        return base_id

    def _register_ir_uv_band_profile(self, node, mat, band, reflectance):
        """Register a constant-in-band reflectance profile (0 outside the band)
        over 300-1000 nm @ 5 nm. IR: 700-1000, UV: 300-400, both: both bands."""
        if (not RAYTRACER_AVAILABLE or astroray_nodes is None
                or not hasattr(astroray, 'register_spectral_profile')):
            return ''
        grid = getattr(astroray_nodes, 'spectrum_grid', None)
        step = getattr(astroray_nodes, 'DRAWN_SPECTRUM_STEP_NM', 5.0)
        if grid is None:
            return ''
        count, lmin, lmax = grid(300.0, 1000.0, step)
        in_ir = band in ('ir', 'both')
        in_uv = band in ('uv', 'both')
        values = []
        for i in range(count):
            wl = lmin + i * step
            hit = (in_ir and 700.0 <= wl <= 1000.0) or (in_uv and 300.0 <= wl <= 400.0)
            values.append(reflectance if hit else 0.0)
        owner = getattr(mat, 'name', 'material') or 'material'
        name = f"__blend__/{owner}/{getattr(node, 'name', 'iruv')}"
        try:
            if not astroray.register_spectral_profile(name, lmin, step, list(values)):
                return ''
        except Exception:
            return ''
        return name

    def _astroray_nrc_hint_spec(self, node, mat, renderer):
        """NRC hint is a passthrough — it annotates the underlying BSDF and
        does not change the material kind. Resolve the inner shader and
        forward it; record the cache flag on mat.astroray for the integrator
        to query."""
        astro = getattr(mat, 'astroray', None)
        if astro is not None:
            try:
                astro.nrc_cache_hint = bool(getattr(node, 'cache_this', True))
            except (AttributeError, TypeError):
                pass
        inner = node.inputs.get('Surface')
        if inner is None or not inner.is_linked:
            return {'kind': 'principled', 'base_color': [0.8, 0.8, 0.8], 'params': {}}
        wired = inner.links[0].from_node
        # Recurse via convert_shader_node by emitting an opaque pass-through
        # spec the material creator forwards via the existing path.
        return {'kind': 'astroray_passthrough', 'inner': wired,
                'cache_this': bool(getattr(node, 'cache_this', True))}

    def _create_astroray_material(self, spec, renderer, node_tree):
        """Materialise an Astroray-native spec dict into a renderer material."""
        if spec is None:
            return renderer.create_material('disney', [0.8, 0.8, 0.8], {})
        kind = spec.get('kind')

        if kind == 'astroray_sellmeier':
            params = {}
            if spec.get('use_preset') and spec.get('preset'):
                params['sellmeier_preset'] = spec['preset']
            else:
                params['ior'] = spec.get('ior', 1.5168)
            # Carry manual B/C as forward-compat keys; dielectric.cpp ignores
            # them today but a future patch can read them directly.
            if 'sellmeier_b' in spec:
                params['sellmeier_b'] = spec['sellmeier_b']
            if 'sellmeier_c' in spec:
                params['sellmeier_c'] = spec['sellmeier_c']
            return renderer.create_material('dielectric', list(spec.get('tint', [1, 1, 1])), params)

        if kind == 'astroray_passthrough':
            inner = spec.get('inner')
            if inner is None:
                return renderer.create_material('disney', [0.8, 0.8, 0.8], {})
            return self.convert_shader_node(inner, renderer, node_tree)

        if kind == 'astroray_spectral_only':
            # pkg195 Stage C: a neutral WHITE diffuse; the authored spectrum is the
            # per-λ reflectance, attached in Replace mode via _apply_spectral_profile
            # (self._current_node_profile was set by _register_source_node_profile).
            return renderer.create_material('disney', [1.0, 1.0, 1.0], {})

        # Unknown kind — neutral fallback.
        return renderer.create_material('disney', [0.8, 0.8, 0.8], {})

    # ------------------------------------------------------------------ #
    # Node-input helpers (unlinked defaults + linked image texture lookup)
    # ------------------------------------------------------------------ #

    def get_float_input(self, node, name, default):
        """Read a scalar input. Follows linked Math/Clamp/MapRange node chains."""
        inp = node.inputs.get(name)
        if not inp:
            return default
        if not inp.is_linked:
            val = inp.default_value
            if hasattr(val, '__iter__'):
                try:
                    return float(val[0])
                except Exception:
                    return default
            return float(val)
        # Try to evaluate the linked node chain
        try:
            src_node = inp.links[0].from_node
            src_socket = inp.links[0].from_socket.name
            result = self._eval_float_socket_node(src_node, src_socket)
            if result is not None:
                return float(result)
        except (IndexError, AttributeError):
            pass
        return default

    def get_color_input(self, node, name, default):
        """Read a color input. Follows linked color node chains."""
        inp = node.inputs.get(name)
        if not inp:
            return list(default)
        if not inp.is_linked:
            val = inp.default_value
            if hasattr(val, '__iter__'):
                return list(val[:3])
            return list(default)
        # Try to evaluate the linked node chain
        try:
            src_node = inp.links[0].from_node
            src_socket = inp.links[0].from_socket.name
            result = self._eval_color_socket_node(src_node, src_socket)
            if result is not None:
                return result
        except (IndexError, AttributeError):
            pass
        return list(default)

    def get_color_or_texture(self, node, input_name, default_color):
        """Read a color input; if linked to an Image Texture node, also return
        the image datablock. Returns (fallback_color, bpy_image_or_None)."""
        inp = node.inputs.get(input_name)
        if not inp:
            return list(default_color), None

        if not inp.is_linked:
            val = inp.default_value
            if hasattr(val, '__iter__'):
                return list(val[:3]), None
            return list(default_color), None

        try:
            linked_node = inp.links[0].from_node
        except (IndexError, AttributeError):
            return list(default_color), None

        # Follow a single Normal Map / Hue-Saturation / etc. wrapper to its
        # underlying Image Texture if present. Otherwise only direct TEX_IMAGE.
        if linked_node.type == 'TEX_IMAGE' and linked_node.image:
            fallback = list(inp.default_value[:3]) if hasattr(inp.default_value, '__iter__') else list(default_color)
            return fallback, linked_node.image
        if linked_node.type in ('NORMAL_MAP', 'HUE_SAT', 'GAMMA', 'BRIGHTCONTRAST'):
            color_in = linked_node.inputs.get('Color')
            if color_in and color_in.is_linked:
                try:
                    deeper = color_in.links[0].from_node
                    if deeper.type == 'TEX_IMAGE' and deeper.image:
                        return list(default_color), deeper.image
                except (IndexError, AttributeError):
                    pass
        return list(default_color), None

    # ------------------------------------------------------------------ #
    # Export-time shader node evaluation (#21 color nodes, #22 converter nodes)
    # ------------------------------------------------------------------ #

    def _get_socket_float(self, socket, depth=0):
        """Return float from a socket (linked or unlinked), or None."""
        if socket is None:
            return None
        if not socket.is_linked:
            val = socket.default_value
            return float(val) if not hasattr(val, '__iter__') else None
        try:
            src_node = socket.links[0].from_node
            src_name = socket.links[0].from_socket.name
        except (IndexError, AttributeError):
            return None
        return self._eval_float_socket_node(src_node, src_name, depth)

    def _get_socket_color(self, socket, depth=0):
        """Return [r,g,b] from a socket (linked or unlinked), or None."""
        if socket is None:
            return None
        if not socket.is_linked:
            val = socket.default_value
            if hasattr(val, '__iter__'):
                return list(val[:3])
            f = float(val)
            return [f, f, f]
        try:
            src_node = socket.links[0].from_node
            src_name = socket.links[0].from_socket.name
        except (IndexError, AttributeError):
            return None
        return self._eval_color_socket_node(src_node, src_name, depth)

    def _eval_float_socket_node(self, node, output_name='Value', depth=0):
        """Evaluate a node's float output. Returns float or None."""
        if depth > 8:
            return None
        import math
        ntype = node.type
        if ntype == 'VALUE':
            return float(node.outputs[0].default_value)
        if ntype == 'MATH':
            op = node.operation
            a = self._get_socket_float(node.inputs[0] if len(node.inputs) > 0 else None, depth + 1)
            b = self._get_socket_float(node.inputs[1] if len(node.inputs) > 1 else None, depth + 1)
            if a is None:
                return None
            b = b if b is not None else 0.0
            ops = {
                'ADD': a + b, 'SUBTRACT': a - b, 'MULTIPLY': a * b,
                'DIVIDE': a / b if b != 0 else 0.0,
                'POWER': a ** b if not (a < 0 and b != int(b)) else 0.0,
                'SQRT': math.sqrt(max(0.0, a)), 'ABSOLUTE': abs(a),
                'MINIMUM': min(a, b), 'MAXIMUM': max(a, b),
                'FLOOR': math.floor(a), 'CEIL': math.ceil(a),
                'FRACT': a - math.floor(a),
                'MODULO': math.fmod(a, b) if b != 0 else 0.0,
                'SINE': math.sin(a), 'COSINE': math.cos(a), 'TANGENT': math.tan(a),
                'ARCSINE': math.asin(max(-1.0, min(1.0, a))),
                'ARCCOSINE': math.acos(max(-1.0, min(1.0, a))),
                'ARCTANGENT': math.atan(a), 'ARCTAN2': math.atan2(a, b),
                'LOGARITHM': math.log(max(1e-10, a)) / math.log(max(1e-10, b)) if b not in (0, 1) else math.log(max(1e-10, a)),
                'LESS_THAN': 1.0 if a < b else 0.0,
                'GREATER_THAN': 1.0 if a > b else 0.0,
                'SIGN': math.copysign(1.0, a) if a != 0.0 else 0.0,
                'SNAP': round(a / b) * b if b != 0 else 0.0,
                'WRAP': a - b * math.floor(a / b) if b != 0 else 0.0,
                'PINGPONG': abs(a - b * round(a / b)) if b != 0 else 0.0,
                'MULTIPLY_ADD': a * b + (self._get_socket_float(node.inputs[2], depth + 1) or 0.0),
                'COMPARE': 1.0 if abs(a - b) <= (self._get_socket_float(node.inputs[2], depth + 1) or 0.0) else 0.0,
            }
            result = ops.get(op)
            if result is None:
                return None
            result = float(result)
            if getattr(node, 'use_clamp', False):
                result = max(0.0, min(1.0, result))
            return result
        if ntype == 'CLAMP':
            val = self._get_socket_float(node.inputs.get('Value'), depth + 1)
            mn = self._get_socket_float(node.inputs.get('Min'), depth + 1)
            mx = self._get_socket_float(node.inputs.get('Max'), depth + 1)
            if val is None:
                return None
            mn = mn if mn is not None else 0.0
            mx = mx if mx is not None else 1.0
            return max(mn, min(mx, val))
        if ntype == 'MAP_RANGE':
            val = self._get_socket_float(node.inputs.get('Value'), depth + 1)
            from_min = self._get_socket_float(node.inputs.get('From Min'), depth + 1)
            from_max = self._get_socket_float(node.inputs.get('From Max'), depth + 1)
            to_min = self._get_socket_float(node.inputs.get('To Min'), depth + 1)
            to_max = self._get_socket_float(node.inputs.get('To Max'), depth + 1)
            if val is None:
                return None
            from_min = from_min if from_min is not None else 0.0
            from_max = from_max if from_max is not None else 1.0
            to_min = to_min if to_min is not None else 0.0
            to_max = to_max if to_max is not None else 1.0
            denom = from_max - from_min
            if abs(denom) < 1e-10:
                return to_min
            t = (val - from_min) / denom
            interp = getattr(node, 'interpolation_type', 'LINEAR')
            if interp == 'SMOOTHSTEP':
                t = t * t * (3.0 - 2.0 * t)
            elif interp == 'SMOOTHERSTEP':
                t = t * t * t * (t * (t * 6.0 - 15.0) + 10.0)
            result = to_min + t * (to_max - to_min)
            if getattr(node, 'clamp', False):
                lo, hi = min(to_min, to_max), max(to_min, to_max)
                result = max(lo, min(hi, result))
            return result
        if ntype == 'RGBTOBW':
            col = self._get_socket_color(node.inputs.get('Color'), depth + 1)
            if col is None:
                return None
            return 0.2126 * col[0] + 0.7152 * col[1] + 0.0722 * col[2]
        return None

    def _eval_color_socket_node(self, node, output_name='Color', depth=0):
        """Evaluate a node's color output. Returns [r,g,b] or None."""
        if depth > 8:
            return None
        import colorsys, math
        ntype = node.type
        if ntype == 'RGB':
            val = node.outputs[0].default_value
            return list(val[:3])
        if ntype == 'TEX_IMAGE':
            return None  # can't evaluate dynamically; caller handles texture lookup
        if ntype in ('MIX_RGB', 'MIX'):
            fac_inp = node.inputs.get('Fac') or node.inputs.get('Factor')
            col1_inp = node.inputs.get('Color1') or node.inputs.get('A') or (node.inputs[1] if len(node.inputs) > 1 else None)
            col2_inp = node.inputs.get('Color2') or node.inputs.get('B') or (node.inputs[2] if len(node.inputs) > 2 else None)
            fac = self._get_socket_float(fac_inp, depth + 1)
            col1 = self._get_socket_color(col1_inp, depth + 1)
            col2 = self._get_socket_color(col2_inp, depth + 1)
            fac = fac if fac is not None else 0.5
            col1 = col1 if col1 is not None else [0.0, 0.0, 0.0]
            col2 = col2 if col2 is not None else [1.0, 1.0, 1.0]
            blend_type = getattr(node, 'blend_type', 'MIX')
            return self._mix_rgb(blend_type, fac, col1, col2)
        if ntype == 'INVERT':
            fac = self._get_socket_float(node.inputs.get('Fac'), depth + 1)
            col = self._get_socket_color(node.inputs.get('Color'), depth + 1)
            if col is None:
                return None
            fac = fac if fac is not None else 1.0
            return [col[i] * (1.0 - fac) + (1.0 - col[i]) * fac for i in range(3)]
        if ntype == 'GAMMA':
            col = self._get_socket_color(node.inputs.get('Color'), depth + 1)
            gamma = self._get_socket_float(node.inputs.get('Gamma'), depth + 1)
            if col is None:
                return None
            gamma = gamma if gamma is not None else 1.0
            return [max(0.0, c) ** gamma for c in col]
        if ntype == 'HUE_SAT':
            hue = self._get_socket_float(node.inputs.get('Hue'), depth + 1)
            sat = self._get_socket_float(node.inputs.get('Saturation'), depth + 1)
            val_mult = self._get_socket_float(node.inputs.get('Value'), depth + 1)
            fac = self._get_socket_float(node.inputs.get('Fac'), depth + 1)
            col = self._get_socket_color(node.inputs.get('Color'), depth + 1)
            if col is None:
                return None
            hue = hue if hue is not None else 0.5
            sat = sat if sat is not None else 1.0
            val_mult = val_mult if val_mult is not None else 1.0
            fac = fac if fac is not None else 1.0
            h, s, v = colorsys.rgb_to_hsv(col[0], col[1], col[2])
            h2 = (h + hue - 0.5) % 1.0
            s2 = max(0.0, s * sat)
            v2 = v * val_mult
            result = list(colorsys.hsv_to_rgb(h2, s2, v2))
            return [col[i] * (1.0 - fac) + result[i] * fac for i in range(3)]
        if ntype == 'BRIGHTCONTRAST':
            col = self._get_socket_color(node.inputs.get('Color'), depth + 1)
            bright = self._get_socket_float(node.inputs.get('Bright'), depth + 1)
            contrast = self._get_socket_float(node.inputs.get('Contrast'), depth + 1)
            if col is None:
                return None
            bright = bright if bright is not None else 0.0
            contrast = contrast if contrast is not None else 0.0
            # Cycles formula: out = (in - 0.5) * (contrast + 1) + 0.5 + bright
            return [max(0.0, (c - 0.5) * (contrast + 1.0) + 0.5 + bright) for c in col]
        if ntype == 'VALTORGB':  # Color Ramp
            fac = self._get_socket_float(node.inputs.get('Fac'), depth + 1)
            if fac is None:
                return None
            try:
                color = node.color_ramp.evaluate(fac)
                return list(color[:3])
            except Exception:
                return None
        if ntype == 'WAVELENGTH':
            wl = self._get_socket_float(node.inputs.get('Wavelength'), depth + 1)
            if wl is None:
                return None
            return self._wavelength_to_rgb(wl)
        if ntype == 'BLACKBODY':
            temp = self._get_socket_float(node.inputs.get('Temperature'), depth + 1)
            if temp is None:
                return None
            return self._blackbody_to_rgb(temp)
        if ntype == 'RGBTOBW':
            col = self._get_socket_color(node.inputs.get('Color'), depth + 1)
            if col is None:
                return None
            bw = 0.2126 * col[0] + 0.7152 * col[1] + 0.0722 * col[2]
            return [bw, bw, bw]
        return None

    def _mix_rgb(self, blend_type, fac, a, b):
        """Apply a MixRGB blend operation matching Cycles behavior."""
        if blend_type == 'MIX':
            return [a[i] * (1.0 - fac) + b[i] * fac for i in range(3)]
        elif blend_type == 'ADD':
            return [min(1.0, a[i] + b[i] * fac) for i in range(3)]
        elif blend_type == 'MULTIPLY':
            return [a[i] * (1.0 - fac) + a[i] * b[i] * fac for i in range(3)]
        elif blend_type == 'SUBTRACT':
            return [max(0.0, a[i] - b[i] * fac) for i in range(3)]
        elif blend_type == 'SCREEN':
            return [1.0 - (1.0 - a[i]) * (1.0 - b[i] * fac) for i in range(3)]
        elif blend_type == 'DIVIDE':
            return [a[i] * (1.0 - fac) + (a[i] / max(1e-5, b[i])) * fac for i in range(3)]
        elif blend_type == 'DIFFERENCE':
            return [a[i] * (1.0 - fac) + abs(a[i] - b[i]) * fac for i in range(3)]
        elif blend_type == 'DARKEN':
            return [a[i] * (1.0 - fac) + min(a[i], b[i]) * fac for i in range(3)]
        elif blend_type == 'LIGHTEN':
            return [a[i] * (1.0 - fac) + max(a[i], b[i]) * fac for i in range(3)]
        elif blend_type == 'OVERLAY':
            def ov(x, y):
                return 2.0 * x * y if x < 0.5 else 1.0 - 2.0 * (1.0 - x) * (1.0 - y)
            blended = [ov(a[i], b[i]) for i in range(3)]
            return [a[i] * (1.0 - fac) + blended[i] * fac for i in range(3)]
        else:
            return [a[i] * (1.0 - fac) + b[i] * fac for i in range(3)]

    def _wavelength_to_rgb(self, wavelength_nm):
        """Approximate CIE spectral locus mapping of wavelength (nm) to RGB."""
        wl = wavelength_nm
        if wl < 380.0 or wl > 780.0:
            return [0.0, 0.0, 0.0]
        if wl < 440.0:
            r = -(wl - 440.0) / (440.0 - 380.0); g = 0.0; b = 1.0
        elif wl < 490.0:
            r = 0.0; g = (wl - 440.0) / (490.0 - 440.0); b = 1.0
        elif wl < 510.0:
            r = 0.0; g = 1.0; b = -(wl - 510.0) / (510.0 - 490.0)
        elif wl < 580.0:
            r = (wl - 510.0) / (580.0 - 510.0); g = 1.0; b = 0.0
        elif wl < 645.0:
            r = 1.0; g = -(wl - 645.0) / (645.0 - 580.0); b = 0.0
        else:
            r = 1.0; g = 0.0; b = 0.0
        factor = (0.3 + 0.7 * (wl - 380.0) / (420.0 - 380.0) if wl < 420.0
                  else 0.3 + 0.7 * (780.0 - wl) / (780.0 - 700.0) if wl > 700.0
                  else 1.0)
        return [r * factor, g * factor, b * factor]

    def _blackbody_to_rgb(self, temperature_k):
        """Approximate Planckian locus (Kang et al. polynomial) to linear RGB."""
        import math
        t = max(1000.0, min(40000.0, temperature_k))
        if t <= 6600.0:
            r = 1.0
            g_raw = 99.4708025861 * math.log(t / 100.0) - 161.1195681661
            g = max(0.0, min(1.0, g_raw / 255.0))
            if t <= 1900.0:
                b = 0.0
            else:
                b_raw = 138.5177312231 * math.log(t / 100.0 - 10.0) - 305.0447927307
                b = max(0.0, min(1.0, b_raw / 255.0))
        else:
            r_raw = 329.698727446 * ((t / 100.0 - 60.0) ** -0.1332047592)
            r = max(0.0, min(1.0, r_raw / 255.0))
            g_raw = 288.1221695283 * ((t / 100.0 - 60.0) ** -0.0755148492)
            g = max(0.0, min(1.0, g_raw / 255.0))
            b = 1.0
        return [r, g, b]

    def get_image_from_socket(self, socket):
        """Resolve a directly linked Image Texture datablock from a socket."""
        if not socket or not socket.is_linked:
            return None
        try:
            src = socket.links[0].from_node
        except (IndexError, AttributeError):
            return None
        if src.type == 'TEX_IMAGE' and src.image:
            return src.image
        return None

    def get_normal_inputs(self, node):
        """Extract normal-map / bump-map inputs wired into Principled Normal."""
        result = {
            'normal_image': None,
            'normal_strength': 1.0,
            'bump_image': None,
            'bump_strength': 1.0,
            'bump_distance': 0.01,
        }
        visited = set()

        def walk_normal_chain(socket):
            if not socket or not socket.is_linked:
                return
            try:
                src = socket.links[0].from_node
            except (IndexError, AttributeError):
                return
            key = id(src)
            if key in visited:
                return
            visited.add(key)

            if src.type == 'NORMAL_MAP':
                result['normal_strength'] = self.get_float_input(src, 'Strength', 1.0)
                result['normal_image'] = self.get_image_from_socket(src.inputs.get('Color'))
                walk_normal_chain(src.inputs.get('Normal'))
                return

            if src.type == 'BUMP':
                result['bump_strength'] = self.get_float_input(src, 'Strength', 1.0)
                result['bump_distance'] = self.get_float_input(src, 'Distance', 0.01)
                result['bump_image'] = self.get_image_from_socket(src.inputs.get('Height'))
                walk_normal_chain(src.inputs.get('Normal'))
                return

        walk_normal_chain(node.inputs.get('Normal'))
        return result

    # ------------------------------------------------------------------ #
    # pkg59 follow-up: Vector input → coord_mode + UV transform
    # ------------------------------------------------------------------ #

    @staticmethod
    def _resolve_vector_input(vector_socket, depth=0, default_coord_mode="UV"):
        """Walk the Vector input on a TEX_IMAGE / procedural texture node and
        return ``(coord_mode, scale_xy, offset_xy, rotation_z, uv_layer_name)``:

        - ``coord_mode``: one of "UV", "GENERATED", "OBJECT" — passed straight
          to ``renderer.set_texture_coord_mode``. Other Texture Coordinate
          outputs (Camera, Window, Reflection, Normal) currently fall back to
          "UV"; the C++ side supports them but the Blender semantics need a
          real test scene to pin down.
        - ``scale_xy`` / ``offset_xy``: (sx, sy) and (ox, oy) baked from a
          ``Mapping`` node on the chain.
        - ``rotation_z``: float in radians, baked from a ``Mapping`` node's
          Rotation.z (Blender 2D-effective Z component). Default 0.
        - ``default_coord_mode``: fallback when vector_socket is unlinked.
          Per pkg115 Blender parity audit: procedural textures default to
          "GENERATED", Image Texture defaults to "UV".

        Limit chain depth to avoid pathological node graphs (Mapping → Mapping
        → Mapping…).
        """
        coord_mode = default_coord_mode
        scale = (1.0, 1.0)
        offset = (0.0, 0.0)
        rotation = 0.0
        uv_layer_name = ""
        if depth > 4 or vector_socket is None or not getattr(vector_socket, 'is_linked', False):
            return coord_mode, scale, offset, rotation, uv_layer_name
        try:
            link = vector_socket.links[0]
            src = link.from_node
            src_socket_name = link.from_socket.name
        except (IndexError, AttributeError):
            return coord_mode, scale, offset, rotation, uv_layer_name

        ntype = getattr(src, 'type', None)
        if ntype == 'MAPPING':
            # Read Location, Rotation, and Scale defaults. Linked inputs
            # aren't followed — would require a real expression evaluator.
            # Most user-facing mappings have constant defaults.
            loc_inp = src.inputs.get('Location') if hasattr(src, 'inputs') else None
            if loc_inp is not None and not getattr(loc_inp, 'is_linked', False):
                v = loc_inp.default_value
                try:
                    offset = (float(v[0]), float(v[1]))
                except (TypeError, IndexError):
                    pass
            rot_inp = src.inputs.get('Rotation') if hasattr(src, 'inputs') else None
            if rot_inp is not None and not getattr(rot_inp, 'is_linked', False):
                v = rot_inp.default_value
                try:
                    # 2D-effective: only the Z component rotates UVs.
                    rotation = float(v[2])
                except (TypeError, IndexError):
                    pass
            scl_inp = src.inputs.get('Scale') if hasattr(src, 'inputs') else None
            if scl_inp is not None and not getattr(scl_inp, 'is_linked', False):
                v = scl_inp.default_value
                try:
                    scale = (float(v[0]), float(v[1]))
                except (TypeError, IndexError):
                    pass
            # Recurse to find the upstream coord source.
            inner_socket = src.inputs.get('Vector') if hasattr(src, 'inputs') else None
            inner_coord, _inner_scale, _inner_offset, _inner_rot, inner_layer = \
                CustomRaytracerRenderEngine._resolve_vector_input(inner_socket, depth + 1, default_coord_mode)
            return inner_coord, scale, offset, rotation, inner_layer

        if ntype == 'TEX_COORD':
            if src_socket_name == 'Generated':
                return "GENERATED", scale, offset, rotation, uv_layer_name
            if src_socket_name == 'Object':
                return "OBJECT", scale, offset, rotation, uv_layer_name
            if src_socket_name == 'UV':
                return "UV", scale, offset, rotation, getattr(src, 'uv_map', '') or ""
            # pkg219a: Camera / Window / Reflection / Normal are all implemented
            # C++-side (Texture::CoordMode / parseCoordMode). Route them through
            # instead of the old blanket UV fallback.
            if src_socket_name == 'Camera':
                return "CAMERA", scale, offset, rotation, uv_layer_name
            if src_socket_name == 'Window':
                return "WINDOW", scale, offset, rotation, uv_layer_name
            if src_socket_name == 'Reflection':
                return "REFLECTION", scale, offset, rotation, uv_layer_name
            if src_socket_name == 'Normal':
                return "NORMAL", scale, offset, rotation, uv_layer_name
            return "UV", scale, offset, rotation, uv_layer_name

        if ntype == 'UVMAP':
            return "UV", scale, offset, rotation, getattr(src, 'uv_map', '') or ""

        return coord_mode, scale, offset, rotation, uv_layer_name

    @staticmethod
    def _compose_mapping_matrix(location, rotation, scale, vector_type='POINT'):
        """Build a Blender Mapping-node affine as a numpy 4x4.

        Reference: Cycles ``svm/mapping_util.h`` ``svm_mapping`` POINT
        (Apache-2.0): ``out = location + Rotate(euler)*(scale*vector)`` ==
        ``M = Translate(loc) @ Rot_XYZ(rot) @ Scale(scale)``. The euler order is
        Blender's default 'XYZ' (extrinsic X→Y→Z, i.e. R = Rz @ Ry @ Rx). See
        .astroray_plan/docs/pkg219a-mapping-transform-research.md.

        vector_type: POINT (affine incl. translation), VECTOR (no translation),
        TEXTURE (inverse of POINT), NORMAL (rotation only; direction).
        """
        import numpy as np
        import math
        rx, ry, rz = float(rotation[0]), float(rotation[1]), float(rotation[2])
        sx, sy, sz = float(scale[0]), float(scale[1]), float(scale[2])
        lx, ly, lz = float(location[0]), float(location[1]), float(location[2])
        cx, sxr = math.cos(rx), math.sin(rx)
        cy, syr = math.cos(ry), math.sin(ry)
        cz, szr = math.cos(rz), math.sin(rz)
        Rx = np.array([[1, 0, 0], [0, cx, -sxr], [0, sxr, cx]], dtype=np.float64)
        Ry = np.array([[cy, 0, syr], [0, 1, 0], [-syr, 0, cy]], dtype=np.float64)
        Rz = np.array([[cz, -szr, 0], [szr, cz, 0], [0, 0, 1]], dtype=np.float64)
        R = Rz @ Ry @ Rx  # Blender euler 'XYZ'
        S = np.diag([sx, sy, sz])
        M = np.identity(4, dtype=np.float64)
        if vector_type == 'NORMAL':
            # Direction, rotation only (scale inverse-transpose approximated as R).
            M[:3, :3] = R
        elif vector_type == 'VECTOR':
            M[:3, :3] = R @ S  # no translation
        else:  # POINT (default)
            M[:3, :3] = R @ S
            M[:3, 3] = [lx, ly, lz]
        if vector_type == 'TEXTURE':
            M = np.linalg.inv(M)
        return M

    def _resolve_mapping_matrix(self, vector_socket, depth=0):
        """Walk the Vector chain and compose all Mapping nodes into a single
        3x4 (top-rows, row-major) affine, or return None if there is no
        non-identity Mapping. pkg219a: full 3-D transform incl. X/Y rotation and
        Z location/scale — supersedes the old 2-D ``_resolve_vector_input``
        scale/offset/rotation for texture sampling.

        Linked Location/Rotation/Scale inputs cannot be constant-folded (that is
        the op-VM's job, pkg219b) — those components fall back to their socket
        defaults and record a visible degradation entry.
        """
        import numpy as np
        if depth > 4 or vector_socket is None or not getattr(vector_socket, 'is_linked', False):
            return None
        try:
            src = vector_socket.links[0].from_node
        except (IndexError, AttributeError):
            return None
        if getattr(src, 'type', None) != 'MAPPING':
            return None

        def _default(name, fallback):
            inp = src.inputs.get(name) if hasattr(src, 'inputs') else None
            if inp is None:
                return fallback
            if getattr(inp, 'is_linked', False):
                self._warn_shader_fallback(
                    'MAPPING',
                    f"linked '{name}' input constant-folded to its default "
                    f"(per-texel Mapping inputs need the op-VM, pkg219b)")
                return fallback
            v = inp.default_value
            try:
                return (float(v[0]), float(v[1]), float(v[2]))
            except (TypeError, IndexError):
                return fallback

        location = _default('Location', (0.0, 0.0, 0.0))
        rotation = _default('Rotation', (0.0, 0.0, 0.0))
        scale = _default('Scale', (1.0, 1.0, 1.0))
        vtype = getattr(src, 'vector_type', 'POINT')
        M = self._compose_mapping_matrix(location, rotation, scale, vtype)

        inner_socket = src.inputs.get('Vector') if hasattr(src, 'inputs') else None
        inner = self._resolve_mapping_matrix(inner_socket, depth + 1)
        if inner is not None:
            M = M @ np.array(inner + [0.0, 0.0, 0.0, 1.0], dtype=np.float64).reshape(4, 4)

        if np.allclose(M, np.identity(4), atol=1e-7):
            return None
        return [float(x) for x in M[:3, :].reshape(-1)]

    @staticmethod
    def _is_default_uv_transform(coord_mode, scale, offset, rotation, uv_layer_name=""):
        return (coord_mode == "UV"
                and abs(scale[0] - 1.0) < 1e-6 and abs(scale[1] - 1.0) < 1e-6
                and abs(offset[0]) < 1e-6 and abs(offset[1]) < 1e-6
                and abs(rotation) < 1e-6
                and not uv_layer_name)

    @staticmethod
    def _texture_variant_key(base_name, coord_mode, scale, offset, rotation,
                             uv_layer_name="", mapping_matrix=None):
        """Cache key that distinguishes the same image used with different
        Mapping or coord-mode wiring across materials."""
        if (mapping_matrix is None
                and CustomRaytracerRenderEngine._is_default_uv_transform(
                    coord_mode, scale, offset, rotation, uv_layer_name)):
            return base_name
        # pkg219a: a full 3-D Mapping matrix supersedes the 2-D scale/offset/rot
        # in the key so the same image under different 3-D mappings gets distinct
        # C++ texture entries.
        if mapping_matrix is not None:
            mstr = ",".join(f"{v:.4f}" for v in mapping_matrix)
            return f"{base_name}::{coord_mode}::M[{mstr}]::{uv_layer_name}"
        return (f"{base_name}::{coord_mode}::"
                f"{scale[0]:.4f},{scale[1]:.4f},"
                f"{offset[0]:.4f},{offset[1]:.4f},"
                f"{rotation:.4f}::{uv_layer_name}")

    def _apply_texture_transform(self, renderer, tex_name, coord_mode,
                                 scale, offset, rotation, uv_layer_name="",
                                 mapping_matrix=None):
        """Push coord_mode + UV transform to the C++ side (no-ops if default)."""
        try:
            if coord_mode != "UV":
                renderer.set_texture_coord_mode(tex_name, coord_mode)
            if coord_mode == "GENERATED":
                # pkg115: convert_objects bakes the user object's bbox onto
                # this texture (set_texture_generated_bbox).
                mat_name = getattr(self, "_current_material_name", None)
                if mat_name is not None:
                    self._generated_textures_by_material.setdefault(
                        mat_name, []).append(tex_name)
            if uv_layer_name and hasattr(renderer, "set_texture_uv_layer"):
                renderer.set_texture_uv_layer(tex_name, uv_layer_name)
            # pkg219a: a full 3-D Mapping matrix supersedes the legacy 2-D UV
            # transform. Prefer it when present (image textures sample at
            # (M*coord).xy on both CPU and GPU).
            if mapping_matrix is not None and hasattr(renderer, "set_texture_mapping_matrix"):
                renderer.set_texture_mapping_matrix(tex_name, list(mapping_matrix))
                return
            non_identity = (
                abs(scale[0] - 1.0) >= 1e-6 or abs(scale[1] - 1.0) >= 1e-6
                or abs(offset[0]) >= 1e-6 or abs(offset[1]) >= 1e-6
                or abs(rotation) >= 1e-6
            )
            if non_identity:
                renderer.set_texture_uv_transform(
                    tex_name,
                    float(scale[0]), float(scale[1]),
                    float(offset[0]), float(offset[1]),
                    float(rotation),
                )
        except AttributeError:
            # Older C++ module without these bindings — silently skip.
            pass

    def load_blender_image(self, bpy_image, renderer, vector_input=None):
        """Load a Blender image datablock into the renderer's texture manager.
        Returns the texture name (string) on success, None on failure.

        ``vector_input`` is the Image Texture node's Vector socket. If linked
        through a ``Mapping`` node or a non-default ``Texture Coordinate``
        output, the resulting coord_mode + UV transform is baked into the
        uploaded texture. The cache key includes the transform so the same
        image used with different Mapping nodes across materials gets
        independent texture entries.

        Blender stores image pixels bottom-to-top; the C++ ImageTexture expects
        top-to-bottom, so we flip vertically before uploading.
        """
        if bpy_image is None:
            return None
        # Image Texture defaults to UV when Vector socket is unconnected.
        coord_mode, uv_scale, offset, rotation, uv_layer_name = self._resolve_vector_input(vector_input, default_coord_mode="UV")
        mapping_matrix = self._resolve_mapping_matrix(vector_input)
        cache_key = self._texture_variant_key(bpy_image.name, coord_mode, uv_scale, offset, rotation, uv_layer_name, mapping_matrix)

        # Deduplicate: a single (image, transform) pair is uploaded at most
        # once per conversion pass.
        cache = getattr(self, '_texture_cache', None)
        if cache is None:
            cache = {}
            self._texture_cache = cache
        if cache_key in cache:
            return cache[cache_key]

        try:
            width, height = bpy_image.size
            if width == 0 or height == 0:
                return None
            # Force pixel data to be available (packed/generated images may not
            # have pixels loaded until reload() is called).
            if not bpy_image.has_data:
                try:
                    bpy_image.reload()
                except Exception:
                    pass
            if len(bpy_image.pixels) == 0:
                return None

            # pixels are a flat RGBA float array, row-major, bottom-to-top
            pixels = np.asarray(bpy_image.pixels[:], dtype=np.float32)
            pixels = pixels.reshape(height, width, 4)
            # Flip vertically (Blender stores row 0 = bottom)
            pixels = np.ascontiguousarray(pixels[::-1, :, :])
            # Drop alpha; renderer takes RGB float
            rgb = pixels[:, :, :3].reshape(-1).tolist()

            renderer.load_texture(cache_key, rgb, width, height)
            self._apply_texture_transform(renderer, cache_key, coord_mode, uv_scale, offset, rotation, uv_layer_name, mapping_matrix)
            cache[cache_key] = cache_key
            return cache_key
        except Exception as e:
            print(f"Astroray: failed to load texture '{bpy_image.name}': {e}")
            return None

    def load_procedural_texture(self, node, renderer, vector_input=None):
        """Export a Blender procedural texture node to the Astroray texture manager.
        Returns a texture name string on success, None on failure.

        Supported node types: TEX_NOISE, TEX_VORONOI, TEX_WAVE, TEX_MAGIC,
        TEX_CHECKER, TEX_BRICK, TEX_GRADIENT, TEX_MUSGRAVE.

        ``vector_input`` is the procedural node's Vector socket. If it's
        linked through a Mapping / Texture Coordinate chain, we bake the
        coord_mode + UV transform onto the created texture.
        """
        cache = getattr(self, '_proc_tex_cache', None)
        if cache is None:
            cache = {}
            self._proc_tex_cache = cache
        # Cache key includes the transform so the same procedural node used
        # with different Mapping wiring gets distinct entries. A procedural
        # node only has one Vector input in practice, so the same id+vector
        # combination is always identical — the variant key is defensive.
        # pkg115 parity fix: procedural textures default to GENERATED when
        # Vector socket is unconnected (Blender standard behavior).
        coord_mode, uv_scale, offset, rotation, uv_layer_name = self._resolve_vector_input(vector_input, default_coord_mode="GENERATED")
        # pkg115 residual fix (black gradient/magic spheres): id(node) is NOT a
        # stable key — convert_node_material works on a temporary
        # inline_shader_nodes() tree that is freed after each material, and
        # CPython reuses the freed addresses, so a later material's texture
        # node can alias an earlier cache entry (observed: the magic sphere
        # silently bound the brick texture, the wave sphere the gradient one;
        # which spheres went black shifted run to run). Key on material + node
        # name instead — unique within a conversion pass and stable across the
        # per-material tree lifetimes. Stub nodes in unit tests may lack
        # .name; those fall back to id() (single-node test scope).
        mat_name = getattr(self, "_current_material_name", "") or ""
        node_id = f"{mat_name}.{getattr(node, 'name', '') or id(node)}"
        cache_key = self._texture_variant_key(f"_proc_{node_id}", coord_mode, uv_scale, offset, rotation, uv_layer_name)
        if cache_key in cache:
            return cache[cache_key]

        ntype = node.type
        tex_name = None
        try:
            if ntype == 'TEX_NOISE':
                # pkg115 chunk 2: ShaderNodeTexNoise → NoiseTextureCycles (Perlin + fractal).
                # Params: [scale, detail, roughness, lacunarity, offset, gain, distortion, noise_type, normalize]
                def _nsock(name, fallback):
                    s = node.inputs.get(name)
                    return float(s.default_value) if s is not None else fallback
                noise_scale = _nsock('Scale', 5.0)
                noise_detail = _nsock('Detail', 2.0)
                noise_rough = _nsock('Roughness', 0.5)
                noise_lac = _nsock('Lacunarity', 2.0)
                noise_offset = _nsock('Offset', 0.0)
                noise_gain = _nsock('Gain', 1.0)
                noise_dist = _nsock('Distortion', 0.0)
                # Blender Noise Texture noise_dimensions: '3D' is the only one the engine supports (node has 1D/2D/3D/4D).
                # noise_type: Blender enum FBM/MULTIFRACTAL/RIDGED_MULTIFRACTAL/HYBRID_MULTIFRACTAL/HETERO_TERRAIN
                # maps to the ENGINE ordering (advanced_features.h noise_select):
                # 0=fBM, 1=multifractal, 2=HYBRID, 3=RIDGED, 4=hetero.
                # (pkg98 chunk-6 review B1: an earlier draft swapped 2/3.)
                noise_type_map = {
                    'FBM': 0.0, 'MULTIFRACTAL': 1.0, 'HYBRID_MULTIFRACTAL': 2.0,
                    'RIDGED_MULTIFRACTAL': 3.0, 'HETERO_TERRAIN': 4.0
                }
                nt = noise_type_map.get(getattr(node, 'noise_type', 'FBM'), 0.0)
                noise_norm = 1.0 if getattr(node, 'normalize', True) else 0.0
                tex_name = f"_proc_noise_{node_id}"
                renderer.create_procedural_texture(tex_name, 'noise_perlin',
                    [noise_scale, noise_detail, noise_rough, noise_lac, noise_offset, noise_gain, noise_dist, nt, noise_norm])
            elif ntype == 'TEX_CHECKER':
                scale = float(node.inputs['Scale'].default_value) if node.inputs.get('Scale') else 5.0
                c1 = list(node.inputs['Color1'].default_value[:3]) if node.inputs.get('Color1') else [1,1,1]
                c2 = list(node.inputs['Color2'].default_value[:3]) if node.inputs.get('Color2') else [0,0,0]
                tex_name = f"_proc_checker_{node_id}"
                renderer.create_procedural_texture(tex_name, 'checker',
                    c1 + c2 + [scale])
            elif ntype == 'TEX_VORONOI':
                def _vsock(name, fallback):
                    s = node.inputs.get(name)
                    return float(s.default_value) if s is not None else fallback
                scale = _vsock('Scale', 5.0)
                randomness = _vsock('Randomness', 1.0)
                smoothness = _vsock('Smoothness', 1.0)
                detail = _vsock('Detail', 0.0)
                roughness = _vsock('Roughness', 0.5)
                lacunarity = _vsock('Lacunarity', 2.0)
                exponent = _vsock('Exponent', 0.5)
                dist_map = {'EUCLIDEAN': 0, 'MANHATTAN': 1, 'CHEBYCHEV': 2, 'MINKOWSKI': 3}
                # Feature enum MUST match the C++ VoronoiTexture order (pkg115 chunk 4,
                # advanced_features.h): 0=F1, 1=Smooth F1, 2=F2, 3=Distance to Edge,
                # 4=N-Sphere Radius. (Older Blender 'F1_F2' has no Cycles socket anymore.)
                feat_map = {'F1': 0, 'SMOOTH_F1': 1, 'F2': 2,
                            'DISTANCE_TO_EDGE': 3, 'N_SPHERE_RADIUS': 4}
                dm = dist_map.get(getattr(node, 'distance', 'EUCLIDEAN'), 0)
                feat = feat_map.get(getattr(node, 'feature', 'F1'), 0)
                normalize = 1.0 if getattr(node, 'normalize', False) else 0.0
                tex_name = f"_proc_voronoi_{node_id}"
                # Full Cycles-parity param vector (see TextureManager::createProceduralTexture
                # "voronoi" in module/blender_module.cpp): trailing detail/roughness/lacunarity/
                # exponent/normalize drive the fractal wrapper + Minkowski exponent + normalize.
                renderer.create_procedural_texture(tex_name, 'voronoi',
                    [scale, randomness, float(dm), float(feat), smoothness,
                     0, 0, 0, 1, 1, 1,
                     detail, roughness, lacunarity, exponent, normalize])
            elif ntype == 'TEX_WAVE':
                # pkg115 chunk 3 + chunk 6 (addon dedup): full Cycles-parity Wave.
                # Params: [wave_type, bands_direction, rings_direction, profile, scale, distortion,
                #          detail, detail_scale, detail_roughness, phase_offset, r1,g1,b1, r2,g2,b2]
                scale = float(node.inputs['Scale'].default_value) if node.inputs.get('Scale') else 5.0
                dist = float(node.inputs['Distortion'].default_value) if node.inputs.get('Distortion') else 0.0
                detail = float(node.inputs['Detail'].default_value) if node.inputs.get('Detail') else 2.0
                dscale = float(node.inputs['Detail Scale'].default_value) if node.inputs.get('Detail Scale') else 1.0
                drough = float(node.inputs['Detail Roughness'].default_value) if node.inputs.get('Detail Roughness') else 0.5
                phase = float(node.inputs['Phase Offset'].default_value) if node.inputs.get('Phase Offset') else 0.0
                # wave_type: BANDS=0, RINGS=1
                wt = 1 if getattr(node, 'wave_type', 'BANDS') == 'RINGS' else 0
                # bands_direction: X=0, Y=1, Z=2, DIAGONAL=3; Blender property 'bands_direction'
                bands_dir_map = {'X': 0, 'Y': 1, 'Z': 2, 'DIAGONAL': 3}
                bd = bands_dir_map.get(getattr(node, 'bands_direction', 'X'), 0)
                # rings_direction: X=0, Y=1, Z=2, SPHERICAL=3; Blender property 'rings_direction'
                rings_dir_map = {'X': 0, 'Y': 1, 'Z': 2, 'SPHERICAL': 3}
                rd = rings_dir_map.get(getattr(node, 'rings_direction', 'X'), 0)
                # wave_profile: SINE=0, SAW=1, TRIANGLE=2; Blender property 'wave_profile'
                profile_map = {'SIN': 0, 'SAW': 1, 'TRI': 2}
                prof = profile_map.get(getattr(node, 'wave_profile', 'SIN'), 0)
                tex_name = f"_proc_wave_{node_id}"
                renderer.create_procedural_texture(tex_name, 'wave',
                    [float(wt), float(bd), float(rd), float(prof), scale, dist, detail, dscale, drough, phase,
                     0,0,0, 1,1,1])
            elif ntype == 'TEX_MAGIC':
                depth = int(node.turbulence_depth) if hasattr(node, 'turbulence_depth') else 2
                scale = float(node.inputs['Scale'].default_value) if node.inputs.get('Scale') else 5.0
                dist = float(node.inputs['Distortion'].default_value) if node.inputs.get('Distortion') else 1.0
                tex_name = f"_proc_magic_{node_id}"
                renderer.create_procedural_texture(tex_name, 'magic',
                    [float(depth), scale, dist, 0,0,0, 1,1,1])
            elif ntype == 'TEX_BRICK':
                # pkg115 chunk 3 + chunk 6 (addon dedup): full Cycles-parity Brick.
                # Params: [brick1_r,g,b, brick2_r,g,b, mortar_r,g,b, scale, mortar_size, mortar_smooth,
                #          bias, brick_width, row_height, offset_amount, offset_freq, squash, squash_freq]
                c1 = list(node.inputs['Color1'].default_value[:3]) if node.inputs.get('Color1') else [0.8, 0.8, 0.8]
                c2 = list(node.inputs['Color2'].default_value[:3]) if node.inputs.get('Color2') else [0.2, 0.2, 0.2]
                c_mortar = list(node.inputs['Color3'].default_value[:3]) if node.inputs.get('Color3') else [0.0, 0.0, 0.0]
                scale = float(node.inputs['Scale'].default_value) if node.inputs.get('Scale') else 5.0
                mort_size = float(node.inputs['Mortar Size'].default_value) if node.inputs.get('Mortar Size') else 0.02
                mort_smooth = float(node.inputs['Mortar Smooth'].default_value) if node.inputs.get('Mortar Smooth') else 0.1
                bias = float(node.inputs['Bias'].default_value) if node.inputs.get('Bias') else 0.0
                bw = float(node.inputs['Brick Width'].default_value) if node.inputs.get('Brick Width') else 0.5
                rh = float(node.inputs['Row Height'].default_value) if node.inputs.get('Row Height') else 0.25
                # Blender Brick properties: offset, offset_frequency, squash, squash_frequency
                offamt = float(node.inputs['Offset'].default_value) if node.inputs.get('Offset') else 0.5
                offfreq = float(getattr(node, 'offset_frequency', 2))
                sq = float(getattr(node, 'squash', 1.0))
                sqfreq = float(getattr(node, 'squash_frequency', 2))
                tex_name = f"_proc_brick_{node_id}"
                renderer.create_procedural_texture(tex_name, 'brick',
                    c1 + c2 + c_mortar + [scale, mort_size, mort_smooth, bias, bw, rh, offamt, offfreq, sq, sqfreq])
            elif ntype == 'TEX_GRADIENT':
                grad_map = {'LINEAR': 0, 'QUADRATIC': 1, 'EASING': 2, 'DIAGONAL': 3,
                            'SPHERICAL': 4, 'QUADRATIC_SPHERE': 5, 'RADIAL': 6}
                gt = float(grad_map.get(getattr(node, 'gradient_type', 'LINEAR'), 0))
                tex_name = f"_proc_gradient_{node_id}"
                renderer.create_procedural_texture(tex_name, 'gradient',
                    [gt, 1.0, 0,0,0, 1,1,1])
            elif ntype == 'TEX_MUSGRAVE':
                scale = float(node.inputs['Scale'].default_value) if node.inputs.get('Scale') else 5.0
                detail = float(node.inputs['Detail'].default_value) if node.inputs.get('Detail') else 2.0
                dim = float(node.inputs['Dimension'].default_value) if node.inputs.get('Dimension') else 2.0
                lac = float(node.inputs['Lacunarity'].default_value) if node.inputs.get('Lacunarity') else 2.0
                mus_map = {'FBM': 0, 'MULTIFRACTAL': 1, 'RIDGED_MULTIFRACTAL': 2, 'HYBRID_MULTIFRACTAL': 3, 'HETERO_TERRAIN': 3}
                mt = float(mus_map.get(getattr(node, 'musgrave_type', 'FBM'), 0))
                tex_name = f"_proc_musgrave_{node_id}"
                renderer.create_procedural_texture(tex_name, 'musgrave',
                    [mt, scale, detail, dim, lac, 1.0, 0,0,0, 1,1,1])
        except Exception as e:
            print(f"Astroray: failed to create procedural texture '{ntype}': {e}")
            return None

        if tex_name:
            self._apply_texture_transform(renderer, tex_name, coord_mode, uv_scale, offset, rotation, uv_layer_name)
            cache[cache_key] = tex_name
        return tex_name

    def get_base_color_texture(self, node, input_name, renderer):
        """Returns (fallback_color, tex_name_or_None) for a color input,
        handling both Image Texture and procedural texture nodes."""
        inp = node.inputs.get(input_name)
        if not inp or not inp.is_linked:
            if inp:
                val = inp.default_value
                if hasattr(val, '__iter__'):
                    return list(val[:3]), None
            return [0.8, 0.8, 0.8], None
        try:
            linked_node = inp.links[0].from_node
        except (IndexError, AttributeError):
            return [0.8, 0.8, 0.8], None
        # Image texture — pkg59: also pass the texture node's Vector input
        # so Mapping/Texture-Coordinate wiring is honored by the upload path.
        if linked_node.type == 'TEX_IMAGE' and linked_node.image:
            vector_inp = linked_node.inputs.get('Vector') if hasattr(linked_node, 'inputs') else None
            tex_name = self.load_blender_image(linked_node.image, renderer, vector_input=vector_inp)
            fallback = list(inp.default_value[:3]) if hasattr(inp.default_value, '__iter__') else [0.8, 0.8, 0.8]
            return fallback, tex_name
        # Procedural texture
        PROC_TYPES = {'TEX_NOISE', 'TEX_CHECKER', 'TEX_VORONOI', 'TEX_WAVE',
                      'TEX_MAGIC', 'TEX_BRICK', 'TEX_GRADIENT', 'TEX_MUSGRAVE'}
        if linked_node.type in PROC_TYPES:
            vector_inp = linked_node.inputs.get('Vector') if hasattr(linked_node, 'inputs') else None
            tex_name = self.load_procedural_texture(linked_node, renderer, vector_input=vector_inp)
            return [0.8, 0.8, 0.8], tex_name
        return [0.8, 0.8, 0.8], None

    # ------------------------------------------------------------------ #
    # Shader-node dispatch
    # ------------------------------------------------------------------ #

    def _shader_input_node(self, node, input_name):
        inp = node.inputs.get(input_name)
        if not inp or not inp.is_linked:
            return None
        try:
            return inp.links[0].from_node
        except (IndexError, AttributeError):
            return None

    def _principled_shader_spec(self, node, renderer=None):
        base_color = self.get_color_input(node, 'Base Color', [0.8, 0.8, 0.8])
        spec = {
            'kind': 'principled',
            'base_color': list(base_color),
            'params': {
                'metallic':        self.get_float_input(node, 'Metallic', 0.0),
                'roughness':       self.get_float_input(node, 'Roughness', 0.5),
                'ior':             self.get_float_input(node, 'IOR', 1.45),
                'transmission':    self._float_with_fallback(node, 'Transmission Weight', 'Transmission', 0.0),
                'clearcoat':       self._float_with_fallback(node, 'Coat Weight', 'Clearcoat', 0.0),
                'clearcoat_gloss': 1.0 - self._float_with_fallback(node, 'Coat Roughness', 'Clearcoat Roughness', 0.0),
                'anisotropic':     self.get_float_input(node, 'Anisotropic', 0.0),
                'sheen':           self._float_with_fallback(node, 'Sheen Weight', 'Sheen', 0.0),
                'subsurface':      self._float_with_fallback(node, 'Subsurface Weight', 'Subsurface', 0.0),
            },
            'emission_color': self.get_color_input(node, 'Emission Color', [0.0, 0.0, 0.0]),
            'emission_strength': self.get_float_input(node, 'Emission Strength', 0.0),
        }
        # pkg178 Stage 5: carry the FULL native-socket map alongside the Disney
        # 'params' above. The Disney fallback path reads 'params' (byte-unchanged);
        # the native 'principled' path reads 'native_params'. 'native_gaps' records
        # any socket the native path does not honour (pkg119-C — never a silent drop).
        spec['native_params'] = self._principled_native_params(node)
        spec['native_gaps'] = self._native_principled_gaps(node, spec['native_params'])
        # Carry texture-name references through the spec when a renderer is
        # available (i.e. during real conversion, not unit-tests of the spec
        # shape). Without this, an Image Texture connected to Base Color was
        # silently dropped and the material rendered as grey Disney —
        # the bug behind the project-owner-reported "default cube + default
        # Image Texture shows no pattern" screenshot.
        if renderer is not None:
            _, base_color_tex = self.get_base_color_texture(node, 'Base Color', renderer)
            if base_color_tex is not None:
                spec['base_color_texture'] = base_color_tex
            normal_inputs = self.get_normal_inputs(node)
            if normal_inputs.get('normal_image') is not None:
                tex = self.load_blender_image(normal_inputs['normal_image'], renderer)
                if tex:
                    spec['normal_map_texture'] = tex
                    spec['normal_strength'] = normal_inputs['normal_strength']
            if normal_inputs.get('bump_image') is not None:
                tex = self.load_blender_image(normal_inputs['bump_image'], renderer)
                if tex:
                    spec['bump_map_texture'] = tex
                    spec['bump_strength'] = normal_inputs['bump_strength']
                    spec['bump_distance'] = normal_inputs['bump_distance']
        return spec

    # pkg178 Stage 5: Blender Principled sockets present on 5.x but NOT honoured
    # by the native 'principled' material. Thin Film (thickness/IOR), Thin Wall and
    # Subsurface Anisotropy are now wired (pkg178 Stage 4 on main) and no longer
    # listed here. What remains genuinely unmapped: Subsurface IOR (native material
    # has no per-medium IOR knob), and the per-lobe normal/tangent vector sockets
    # (Coat Normal, Tangent — native uses the shading/UV normal + UV tangent).
    # Reported per-render via the pkg119-C degradation policy, never dropped silently.
    _NATIVE_PRINCIPLED_UNMAPPED = (
        'Subsurface IOR', 'Coat Normal', 'Tangent',
    )

    def _use_native_principled(self):
        """pkg178 Stage 5 routing flag. Defaults ON (experimental build) so
        direct helper calls outside a full convert_materials() lifecycle (unit
        tests, previews) match the shipped default; convert_materials resolves
        the real per-scene value onto self._use_native_principled_flag."""
        return bool(getattr(self, "_use_native_principled_flag", True))

    def _principled_native_params(self, node):
        """Map EVERY Blender Principled socket the native 'principled' material
        accepts onto its Cycles/native param name (plugins/materials/principled.cpp).
        Sockets absent on this Blender version are skipped (renamed-input
        fallbacks cover 3.x/4.x/5.x drift). Colours are read only from RGBA/VECTOR
        sockets so 3.x float Specular-Tint / Sheen-Tint don't poison the colour
        params. pkg178 Stage 5. Emission + base colour are carried at the spec
        top level, not here."""
        p = {}

        def put_float(dst, *names):
            for nm in names:
                if node.inputs.get(nm) is not None:
                    p[dst] = self.get_float_input(node, nm, 0.0)
                    return

        def put_vec(dst, *names):
            for nm in names:
                inp = node.inputs.get(nm)
                if inp is not None and getattr(inp, 'type', 'RGBA') in ('RGBA', 'VECTOR'):
                    p[dst] = self.get_color_input(node, nm, [1.0, 1.0, 1.0])
                    return

        # Core
        put_float('metallic', 'Metallic')
        put_float('roughness', 'Roughness')
        put_float('ior', 'IOR')
        put_float('diffuse_roughness', 'Diffuse Roughness')
        # Specular (Cycles: Specular IOR Level + Specular Tint; 3.x 'Specular' float)
        put_float('specular_ior_level', 'Specular IOR Level', 'Specular')
        put_vec('specular_tint', 'Specular Tint')
        # Transmission
        put_float('transmission_weight', 'Transmission Weight', 'Transmission')
        # Coat (4.x+: weight/roughness/ior/tint; 3.x 'Clearcoat' pair)
        put_float('coat_weight', 'Coat Weight', 'Clearcoat')
        put_float('coat_roughness', 'Coat Roughness', 'Clearcoat Roughness')
        put_float('coat_ior', 'Coat IOR')
        put_vec('coat_tint', 'Coat Tint')
        # Sheen (4.x+: weight/roughness/tint; 3.x 'Sheen' float)
        put_float('sheen_weight', 'Sheen Weight', 'Sheen')
        put_float('sheen_roughness', 'Sheen Roughness')
        put_vec('sheen_tint', 'Sheen Tint')
        # Anisotropy
        put_float('anisotropic', 'Anisotropic')
        put_float('anisotropic_rotation', 'Anisotropic Rotation')
        # Subsurface (approximate D2(a) diffusion in the native material)
        put_float('subsurface_weight', 'Subsurface Weight', 'Subsurface')
        put_float('subsurface_scale', 'Subsurface Scale')
        put_vec('subsurface_radius', 'Subsurface Radius')
        # Subsurface anisotropy (thin-subsurface diffuse/translucent split; Cycles
        # bsdf_thin_subsurface_setup). Now honoured by the native material (pkg178
        # Stage 4 on main); previously in _NATIVE_PRINCIPLED_UNMAPPED.
        put_float('subsurface_anisotropy', 'Subsurface Anisotropy')
        # Thin Film iridescence (Belcour-Barla) + Thin Wall translucency — pkg178
        # Stage 4, now on main. Thin Wall is a boolean socket; get_float_input
        # returns 1.0/0.0 which the engine reads as thin_wall>0.5.
        put_float('thin_film_thickness', 'Thin Film Thickness')
        put_float('thin_film_ior', 'Thin Film IOR')
        put_float('thin_wall', 'Thin Wall')
        # Dispersion (pkg187) — FORWARD-COMPATIBLE probe. No shipped Blender exposes
        # a Dispersion socket on Principled BSDF: headless probes of 4.3.2 / 4.5.0 /
        # 5.1.0 / 5.2.0 all return no such input. It is the unmerged upstream WIP,
        # Blender PR #162041, which adds two sockets — 'Dispersion Scale' (in [0,1])
        # and 'Dispersion Abbe Number' (default 20). These put_float calls are a
        # no-op on every current build (socket absent -> key not written -> engine
        # stays non-dispersive) and start round-tripping automatically the day that
        # PR ships. The native material (principled.cpp) reads dispersion_scale +
        # dispersion_abbe; a one-socket 'Dispersion' build aliases the scale.
        put_float('dispersion_scale', 'Dispersion Scale', 'Dispersion')
        put_float('dispersion_abbe', 'Dispersion Abbe Number')
        # Alpha — a REAL value routed to the native transparent lobe; NOT folded
        # into transmission (that conflation is the convicted BSDF_TRANSPARENT
        # bug family the Disney path still carries).
        put_float('alpha', 'Alpha')
        return p

    def _native_principled_gaps(self, node, native_params):
        """pkg119-C: sockets the native Principled path does not honour, surfaced
        per-render so nothing is dropped silently. Linked unmapped sockets
        (Subsurface IOR, Coat Normal, Tangent) and the approximate subsurface
        model get a report line. Thin Film, Thin Wall and Subsurface Anisotropy
        are now wired (pkg178 Stage 4) and no longer reported as gaps."""
        gaps = []
        for nm in self._NATIVE_PRINCIPLED_UNMAPPED:
            inp = node.inputs.get(nm)
            if inp is None:
                continue
            if getattr(inp, 'is_linked', False):
                gaps.append(f"Principled socket '{nm}' is linked but not honoured "
                            f"by the native material (dropped)")
        if float(native_params.get('subsurface_weight', 0.0)) > 0.0:
            gaps.append("Principled Subsurface uses the approximate diffusion model "
                        "(D2(a), not the Cycles random-walk BSSRDF)")
        return gaps

    # pkg178 Stage 5: Disney param name -> native 'principled' param name, for
    # 'principled'-kind specs that only carry Disney-named params (standalone
    # BSDF nodes, Mix/Add blends). clearcoat_gloss inverts to coat_roughness.
    _DISNEY_TO_NATIVE_PARAM = {
        'metallic': 'metallic',
        'roughness': 'roughness',
        'ior': 'ior',
        'transmission': 'transmission_weight',
        'clearcoat': 'coat_weight',
        'anisotropic': 'anisotropic',
        'sheen': 'sheen_weight',
        'subsurface': 'subsurface_weight',
    }

    def _disney_params_to_native(self, params):
        """Translate a Disney-named param dict to native 'principled' names.
        Non-material keys (textures, alpha) are left for the caller to handle."""
        native = {}
        for dk, nk in self._DISNEY_TO_NATIVE_PARAM.items():
            if dk in params:
                native[nk] = params[dk]
        if 'clearcoat_gloss' in params:
            native['coat_roughness'] = 1.0 - float(params['clearcoat_gloss'])
        return native

    def _create_native_principled_material(self, spec, renderer, color, params,
                                           emission_color, emission_strength):
        """pkg178 Stage 5 — route a Blender Principled node to the NATIVE
        'principled' material. Alpha routes through the native 'alpha' param (NOT
        the transmission conflation the Disney path uses); emission lives inside
        the node (the promote-to-light heuristic is retired on this path). A
        textured base colour still routes through textured-lambertian because
        neither material has a base-colour texture slot (spec Non-goal)."""
        # Standalone BSDF nodes (Glass/Metallic/Glossy/...) and Mix/Add blends
        # produce a 'principled' spec whose 'params' use Disney names but carry
        # NO native_params. Translate those to native names first so their
        # metallic/transmission/roughness are not lost, then overlay the richer
        # native_params (the Principled-node parse) which wins where present.
        native = self._disney_params_to_native(params)
        native.update(spec.get('native_params', {}))

        # Alpha may also arrive from a Mix-with-Transparent (shader_blending sets
        # params['alpha']); an explicit native alpha wins, else honour that.
        if 'alpha' not in native and 'alpha' in params:
            native['alpha'] = float(params['alpha'])

        # Emission inside the node (native material emits directly).
        native['emission_color'] = list(emission_color)
        native['emission_strength'] = float(emission_strength)

        # Normal/bump textures plumb through to the native material.
        for key in ('normal_map_texture', 'normal_strength',
                    'bump_map_texture', 'bump_strength', 'bump_distance'):
            if key in spec:
                native[key] = spec[key]

        # pkg119-C: surface every socket the native path does not honour.
        for msg in spec.get('native_gaps', []):
            self._warn_shader_fallback('BSDF_PRINCIPLED', msg)

        # Textured base colour → textured-lambertian (Non-goal: base-colour
        # texture slot on the native material). Mirrors the Disney path.
        base_tex = spec.get('base_color_texture')
        if base_tex is not None:
            self._warn_shader_fallback(
                'BSDF_PRINCIPLED',
                'textured Base Color routes through lambertian (native material '
                'has no base-color texture slot yet)')
            lambert_params = {'texture': base_tex}
            for key in ('normal_map_texture', 'normal_strength',
                        'bump_map_texture', 'bump_strength', 'bump_distance'):
                if key in native:
                    lambert_params[key] = native[key]
            return renderer.create_material('lambertian', color, lambert_params)

        return renderer.create_material('principled', color, native)

    def _degradation_report(self):
        """pkg119 Phase C: the per-render degradation policy accumulator. Lazily
        created so translation helpers called outside a full render() lifecycle
        (material preview, viewport convert) still record cleanly; render() resets
        it at the start of each final render and emits it once at the end."""
        report = getattr(self, "_degradation", None)
        if report is None:
            report = DegradationReport()
            self._degradation = report
        return report

    def _warn_shader_fallback(self, node_type, message):
        # pkg119 Phase C: funnel shader-node fallbacks into the single degradation
        # policy (recorded as APPROXIMATED, de-duplicated there) instead of
        # emitting a separate per-node warning. The consolidated report surfaces
        # once per render (final render path).
        self._degradation_report().approximate(node_type, message)

    def _standalone_bsdf_spec(self, node):
        ntype = node.type
        if ntype == 'BSDF_DIFFUSE':
            color = self.get_color_input(node, 'Color', [0.8, 0.8, 0.8])
            rough = self.get_float_input(node, 'Roughness', 0.0)
            if rough > 1e-4:
                self._warn_shader_fallback('BSDF_DIFFUSE', 'Oren-Nayar diffuse is approximated with Disney rough diffuse')
            return {'kind': 'principled', 'base_color': color, 'params': {'metallic': 0.0, 'roughness': rough}}
        if ntype in ('BSDF_GLOSSY', 'BSDF_ANISOTROPIC'):
            color = self.get_color_input(node, 'Color', [0.8, 0.8, 0.8])
            rough = self.get_float_input(node, 'Roughness', 0.5)
            params = {'metallic': 1.0, 'roughness': rough}
            if ntype == 'BSDF_ANISOTROPIC':
                if node.inputs.get('Anisotropy') is not None:
                    params['anisotropic'] = self.get_float_input(node, 'Anisotropy', 0.0)
                else:
                    params['anisotropic'] = self.get_float_input(node, 'Anisotropic', 0.0)
            return {'kind': 'principled', 'base_color': color, 'params': params}
        if ntype == 'BSDF_GLASS':
            color = self.get_color_input(node, 'Color', [1.0, 1.0, 1.0])
            rough = self.get_float_input(node, 'Roughness', 0.0)
            ior = self.get_float_input(node, 'IOR', 1.5)
            return {'kind': 'principled', 'base_color': color, 'params': {'transmission': 1.0, 'ior': ior, 'roughness': rough}}
        if ntype == 'BSDF_TRANSLUCENT':
            color = self.get_color_input(node, 'Color', [0.8, 0.8, 0.8])
            self._warn_shader_fallback('BSDF_TRANSLUCENT', 'true normal-flipped diffuse transmission is approximated with rough transmission')
            return {'kind': 'principled', 'base_color': color, 'params': {'transmission': 1.0, 'roughness': 1.0, 'ior': 1.0}}
        if ntype == 'BSDF_TRANSPARENT':
            color = self.get_color_input(node, 'Color', [1.0, 1.0, 1.0])
            return {'kind': 'transparent', 'base_color': color}
        if ntype == 'BSDF_REFRACTION':
            color = self.get_color_input(node, 'Color', [1.0, 1.0, 1.0])
            rough = self.get_float_input(node, 'Roughness', 0.0)
            ior = self.get_float_input(node, 'IOR', 1.5)
            self._warn_shader_fallback('BSDF_REFRACTION', 'pure refraction without Fresnel reflection is approximated with Disney transmission')
            return {'kind': 'principled', 'base_color': color, 'params': {'transmission': 1.0, 'roughness': rough, 'ior': ior}}
        if ntype == 'BSDF_SHEEN':
            color = self.get_color_input(node, 'Color', [0.8, 0.8, 0.8])
            rough = self.get_float_input(node, 'Roughness', 0.5)
            weight = self.get_float_input(node, 'Weight', 1.0)
            self._warn_shader_fallback('BSDF_SHEEN', 'Cycles microfiber sheen is approximated with Disney sheen')
            return {'kind': 'principled', 'base_color': color, 'params': {'sheen': weight, 'roughness': rough}}
        if ntype == 'BSDF_METALLIC':
            if node.inputs.get('Base Color') is not None:
                color = self.get_color_input(node, 'Base Color', [0.8, 0.8, 0.8])
            else:
                color = self.get_color_input(node, 'Color', [0.8, 0.8, 0.8])
            rough = self.get_float_input(node, 'Roughness', 0.2)
            self._warn_shader_fallback('BSDF_METALLIC', 'F82 edge tint is approximated with Disney metallic base color')
            return {'kind': 'principled', 'base_color': color, 'params': {'metallic': 1.0, 'roughness': rough}}
        return None

    def _shader_spec_from_node(self, node, renderer, node_tree, depth=0):
        if node is None or depth > 32:
            return None
        ntype = node.type

        if ntype == 'BSDF_PRINCIPLED':
            return self._principled_shader_spec(node, renderer)
        standalone = self._standalone_bsdf_spec(node)
        if standalone is not None:
            return standalone
        if ntype == 'EMISSION':
            return {'kind': 'emission', 'base_color': self.get_color_input(node, 'Color', [1.0, 1.0, 1.0]), 'emission_strength': self.get_float_input(node, 'Strength', 1.0)}
        if ntype == 'MIX_SHADER':
            fac = self.get_float_input(node, 'Fac', 0.5)
            a = self._shader_spec_from_node(self._shader_input_node(node, 'Shader'), renderer, node_tree, depth + 1)
            b = self._shader_spec_from_node(self._shader_input_node(node, 'Shader_001'), renderer, node_tree, depth + 1)
            return blend_shader_specs(fac, a, b)
        if ntype == 'ADD_SHADER':
            a = self._shader_spec_from_node(self._shader_input_node(node, 'Shader'), renderer, node_tree, depth + 1)
            b = self._shader_spec_from_node(self._shader_input_node(node, 'Shader_001'), renderer, node_tree, depth + 1)
            return add_shader_specs(a, b)
        return None

    def _create_material_from_shader_spec(self, spec, renderer):
        if spec is None:
            return renderer.create_material('disney', [0.8, 0.8, 0.8], {})

        kind = spec.get('kind')
        if kind == 'emission':
            return renderer.create_material('light', spec.get('base_color', [1, 1, 1]),
                                            {'intensity': float(spec.get('emission_strength', 1.0))})

        if kind == 'principled':
            color = list(spec.get('base_color', [0.8, 0.8, 0.8]))
            params = dict(spec.get('params', {}))
            emission_strength = float(spec.get('emission_strength', 0.0))
            emission_color = list(spec.get('emission_color', [0.0, 0.0, 0.0]))

            # pkg178 Stage 5: flag-aware routing. When native Principled is on,
            # drive the faithful 'principled' material (coat/sheen/aniso/alpha/
            # emission direct); otherwise fall through to the Disney path below,
            # which is preserved byte-for-byte as the fallback.
            if self._use_native_principled():
                return self._create_native_principled_material(
                    spec, renderer, color, params, emission_color, emission_strength)

            # Renderer has no explicit alpha channel; approximate transparency.
            alpha = params.pop('alpha', None)
            if alpha is not None:
                params['transmission'] = max(float(params.get('transmission', 0.0)), 1.0 - float(alpha))

            # Add-Shader / Mix-with-Emission approximation:
            # preserve surface and bias base color towards emission.
            if emission_strength > 0.0 and any(c > 0.0 for c in emission_color):
                if emission_strength >= 1.0 and float(params.get('metallic', 0.0)) == 0.0 and float(params.get('transmission', 0.0)) == 0.0:
                    return renderer.create_material('light', emission_color, {'intensity': emission_strength})
                glow = min(1.0, 0.2 * emission_strength)
                color = [max(0.0, min(1.0, (1.0 - glow) * color[i] + glow * emission_color[i])) for i in range(3)]

            # Plumb normal/bump textures through to whichever material we pick.
            for key in ('normal_map_texture', 'normal_strength',
                        'bump_map_texture', 'bump_strength', 'bump_distance'):
                if key in spec:
                    params[key] = spec[key]

            # Textured base color: route through the textured-Lambertian path
            # because the registry's Disney plugin does not currently accept a
            # base-color texture slot. Same compromise as the orphaned
            # convert_principled_bsdf_v2 helper just below — once Disney gains
            # a texture slot, both paths can target Disney directly.
            base_tex = spec.get('base_color_texture')
            if base_tex is not None:
                lambert_params = {'texture': base_tex}
                for key in ('normal_map_texture', 'normal_strength',
                            'bump_map_texture', 'bump_strength', 'bump_distance'):
                    if key in params:
                        lambert_params[key] = params[key]
                return renderer.create_material('lambertian', color, lambert_params)

            return renderer.create_material('disney', color, params)

        if kind == 'transparent':
            color = list(spec.get('base_color', [1.0, 1.0, 1.0]))
            return renderer.create_material('disney', color, {'transmission': 1.0, 'roughness': 0.0, 'ior': 1.0})

        return renderer.create_material('disney', [0.8, 0.8, 0.8], {})

    @staticmethod
    def _blackbody_to_rgb(temperature_k):
        """Approximate blackbody color (1000K..40000K) in linear RGB-like space."""
        t = max(1000.0, min(40000.0, float(temperature_k))) / 100.0
        if t <= 66.0:
            r = 255.0
            g = 99.4708025861 * math.log(t) - 161.1195681661
            if t <= 19.0:
                b = 0.0
            else:
                b = 138.5177312231 * math.log(t - 10.0) - 305.0447927307
        else:
            r = 329.698727446 * ((t - 60.0) ** -0.1332047592)
            g = 288.1221695283 * ((t - 60.0) ** -0.0755148492)
            b = 255.0
        return [max(0.0, min(1.0, c / 255.0)) for c in (r, g, b)]

    def _volume_spec_from_node(self, node, depth=0):
        if node is None or depth > 32:
            return None

        ntype = node.type
        if ntype == 'VOLUME_ABSORPTION':
            return {
                'color': self.get_color_input(node, 'Color', [1.0, 1.0, 1.0]),
                'density': self.get_float_input(node, 'Density', 1.0),
                'anisotropy': 0.0,
                'emission_strength': 0.0,
                'emission_color': [0.0, 0.0, 0.0],
            }
        if ntype == 'VOLUME_SCATTER':
            return {
                'color': self.get_color_input(node, 'Color', [1.0, 1.0, 1.0]),
                'density': self.get_float_input(node, 'Density', 1.0),
                'anisotropy': self.get_float_input(node, 'Anisotropy', 0.0),
                'emission_strength': 0.0,
                'emission_color': [0.0, 0.0, 0.0],
            }
        if ntype == 'PRINCIPLED_VOLUME':
            density = self.get_float_input(node, 'Density', 1.0)
            emission_strength = self.get_float_input(node, 'Emission Strength', 0.0)
            emission_color = self.get_color_input(node, 'Emission Color', [0.0, 0.0, 0.0])
            blackbody_intensity = self.get_float_input(node, 'Blackbody Intensity', 0.0)
            temperature = self.get_float_input(node, 'Temperature', 1000.0)
            if blackbody_intensity > 0.0:
                bb = self._blackbody_to_rgb(temperature)
                emission_color = [emission_color[i] + bb[i] * blackbody_intensity for i in range(3)]
                emission_strength += blackbody_intensity
            return {
                'color': self.get_color_input(node, 'Color', [1.0, 1.0, 1.0]),
                'density': density,
                'anisotropy': self.get_float_input(node, 'Anisotropy', 0.0),
                'emission_strength': emission_strength,
                'emission_color': emission_color,
            }
        if ntype == 'MIX_SHADER':
            fac = self.get_float_input(node, 'Fac', 0.5)
            a = self._volume_spec_from_node(self._shader_input_node(node, 'Shader'), depth + 1)
            b = self._volume_spec_from_node(self._shader_input_node(node, 'Shader_001'), depth + 1)
            if a is None:
                return b
            if b is None:
                return a
            return {
                'color': [(1.0 - fac) * a['color'][i] + fac * b['color'][i] for i in range(3)],
                'density': (1.0 - fac) * float(a['density']) + fac * float(b['density']),
                'anisotropy': (1.0 - fac) * float(a['anisotropy']) + fac * float(b['anisotropy']),
                'emission_strength': (1.0 - fac) * float(a['emission_strength']) + fac * float(b['emission_strength']),
                'emission_color': [(1.0 - fac) * a['emission_color'][i] + fac * b['emission_color'][i] for i in range(3)],
            }
        if ntype == 'ADD_SHADER':
            a = self._volume_spec_from_node(self._shader_input_node(node, 'Shader'), depth + 1)
            b = self._volume_spec_from_node(self._shader_input_node(node, 'Shader_001'), depth + 1)
            if a is None:
                return b
            if b is None:
                return a
            total_density = float(a['density']) + float(b['density'])
            anisotropy = 0.0
            if total_density > 0.0:
                anisotropy = (
                    float(a['density']) * float(a['anisotropy']) +
                    float(b['density']) * float(b['anisotropy'])
                ) / total_density
            return {
                'color': [max(0.0, min(1.0, a['color'][i] + b['color'][i])) for i in range(3)],
                'density': total_density,
                'anisotropy': max(-0.99, min(0.99, anisotropy)),
                'emission_strength': float(a['emission_strength']) + float(b['emission_strength']),
                'emission_color': [max(0.0, min(1.0, a['emission_color'][i] + b['emission_color'][i])) for i in range(3)],
            }
        return None

    def convert_volume_node(self, node, node_tree):
        del node_tree  # reserved for future graph-dependent volume conversion.
        return self._volume_spec_from_node(node)

    def convert_shader_node(self, node, renderer, node_tree):
        """Route a surface-shader node to the appropriate material builder."""
        ntype = node.type
        if ntype in ('VOLUME_ABSORPTION', 'VOLUME_SCATTER', 'PRINCIPLED_VOLUME'):
            return renderer.create_material('glass', [1.0, 1.0, 1.0], {'ior': 1.0})
        spec = self._shader_spec_from_node(node, renderer, node_tree)
        if spec is None:
            # pkg119 Phase C: the surface node has no translation and would
            # otherwise fall through to a neutral grey with NO trace (the
            # DROPPED-SILENT failure mode this program exists to kill). Record
            # it as an explicitly-reported-ignored input in the degradation
            # policy so it surfaces in the per-render report.
            self._degradation_report().ignore(
                f"shader node '{ntype}'",
                "unsupported surface shader -> neutral grey",
            )
        return self._create_material_from_shader_spec(spec, renderer)

    def _float_with_fallback(self, node, new_name, old_name, default):
        """Principled BSDF renamed several inputs between Blender 3.x and 4.x
        ('Transmission' → 'Transmission Weight', etc.). Try the new name first,
        fall back to the old."""
        if node.inputs.get(new_name) is not None:
            return self.get_float_input(node, new_name, default)
        return self.get_float_input(node, old_name, default)

    def convert_principled_bsdf_v2(self, node, renderer):
        """Full Principled BSDF → Disney BRDF conversion with texture support.

        Reads default values from every socket, follows linked Image Texture
        nodes on Base Color (other sockets: defaults only for now), and picks
        up the renamed sockets introduced in Blender 4.0.
        """
        # --- Base Color (may be image-textured or procedural) ---
        base_color, base_color_tex_name = self.get_base_color_texture(
            node, 'Base Color', renderer)
        # Also check legacy path for backward compatibility
        _, base_color_img = self.get_color_or_texture(node, 'Base Color', [0.8, 0.8, 0.8])
        if base_color_tex_name is None and base_color_img is not None:
            base_color_tex_name = self.load_blender_image(base_color_img, renderer)

        # --- Scalar parameters (with renamed-input fallbacks) ---
        metallic  = self.get_float_input(node, 'Metallic', 0.0)
        roughness = self.get_float_input(node, 'Roughness', 0.5)
        ior       = self.get_float_input(node, 'IOR', 1.45)

        transmission   = self._float_with_fallback(node, 'Transmission Weight', 'Transmission',  0.0)
        coat_weight    = self._float_with_fallback(node, 'Coat Weight',         'Clearcoat',     0.0)
        coat_roughness = self._float_with_fallback(node, 'Coat Roughness',      'Clearcoat Roughness', 0.0)
        sheen          = self._float_with_fallback(node, 'Sheen Weight',        'Sheen',         0.0)
        subsurface     = self._float_with_fallback(node, 'Subsurface Weight',   'Subsurface',    0.0)
        anisotropic    = self.get_float_input(node, 'Anisotropic', 0.0)

        # --- Emission (combined with surface; we treat strongly-emissive as
        # a pure light until DisneyBRDF gains an emission term) ---
        emission_color    = self.get_color_input(node, 'Emission Color', [0, 0, 0])
        emission_strength = self.get_float_input(node, 'Emission Strength', 0.0)
        # pkg178 Stage 5: the promote-to-light heuristic is a Disney-path
        # workaround (Disney has no emission term). On the native path emission
        # lives inside the material, so skip the promotion when the flag is on.
        if (not self._use_native_principled()
                and emission_strength > 0.0 and any(c > 0 for c in emission_color)):
            # Heuristic: treat as a dedicated light material when emission
            # dominates the surface response.
            if emission_strength >= 1.0 and metallic == 0.0 and transmission == 0.0:
                return renderer.create_material(
                    'light', emission_color, {'intensity': emission_strength})

        params = {
            'metallic':        metallic,
            'roughness':       roughness,
            'ior':             ior,
            'transmission':    transmission,
            'clearcoat':       coat_weight,
            'clearcoat_gloss': 1.0 - coat_roughness,
            'anisotropic':     anisotropic,
            'sheen':           sheen,
            'subsurface':      subsurface,
        }

        normal_inputs = self.get_normal_inputs(node)
        if normal_inputs['normal_image'] is not None:
            tex_name = self.load_blender_image(normal_inputs['normal_image'], renderer)
            if tex_name:
                params['normal_map_texture'] = tex_name
                params['normal_strength'] = normal_inputs['normal_strength']
        if normal_inputs['bump_image'] is not None:
            tex_name = self.load_blender_image(normal_inputs['bump_image'], renderer)
            if tex_name:
                params['bump_map_texture'] = tex_name
                params['bump_strength'] = normal_inputs['bump_strength']
                params['bump_distance'] = normal_inputs['bump_distance']

        # If base color is textured, load it and route through the 'lambertian'
        # textured path (DisneyBRDF doesn't currently accept a texture, and the
        # TexturedLambertian gives correct base color sampling for most PBR
        # scenes while preserving roughness/metallic-less appearance).
        if base_color_tex_name is not None:
            # Use textured lambertian (the only path that currently samples
            # a texture on hit). TODO: extend DisneyBRDF with a base-color
            # texture slot so we can keep metallic/roughness too.
            lambert_params = {'texture': base_color_tex_name}
            for key in ('normal_map_texture', 'normal_strength',
                        'bump_map_texture', 'bump_strength', 'bump_distance'):
                if key in params:
                    lambert_params[key] = params[key]
            return renderer.create_material('lambertian', base_color,
                                            lambert_params)

        # pkg178 Stage 5: flag-aware routing (mirrors _create_material_from_shader_spec).
        # When native Principled is on, drive the faithful 'principled' material;
        # otherwise keep the Disney fallback below byte-unchanged.
        if self._use_native_principled():
            native = self._principled_native_params(node)
            native['emission_color'] = list(emission_color)
            native['emission_strength'] = float(emission_strength)
            for key in ('normal_map_texture', 'normal_strength',
                        'bump_map_texture', 'bump_strength', 'bump_distance'):
                if key in params:
                    native[key] = params[key]
            for msg in self._native_principled_gaps(node, native):
                self._warn_shader_fallback('BSDF_PRINCIPLED', msg)
            return renderer.create_material('principled', base_color, native)

        return renderer.create_material('disney', base_color, params)

    def _render_will_use_gpu(self, settings, renderer):
        """Pure device pre-check (no side effects), mirroring configure_backend's
        decision. convert_objects runs BEFORE the backend is configured, so we
        can't read renderer._use_gpu — we replicate the decision from the same
        inputs (device_mode + integrator GPU support + renderer.gpu_available).
        pkg114 inc 3c: instancing is GPU-only (the CPU render path has no two-level
        traversal), so a CPU render must keep flattening."""
        mode = getattr(settings, "device_mode", "auto")
        if mode == "cpu":
            return False
        try:
            integ = _effective_integrator_name(settings)
            if not bool(_integrator_capabilities(integ).get("gpuSupported", False)):
                return False
            return bool(renderer.gpu_available)
        except Exception:
            return False

    @staticmethod
    def _material_emits(mat):
        """Shallow node scan for an NEE-relevant mesh emitter, mirroring the
        renderer's own 'light'-material gate in _create_material_from_shader_spec:
        an EMISSION node, or a Principled with Emission Strength >= 1 AND a
        non-black Emission Color. (A default Principled has strength 1 but BLACK
        emission → not an emitter → still instanceable.) Linked emission inputs are
        treated as emitting (conservative). Excluding emitters keeps them on the
        flatten path so their NEE/area-light contribution is not lost (instanced
        meshes are not in the GPU NEE light list — pkg114 inc 3c deferral)."""
        if mat is None:
            return False
        nt = getattr(mat, "node_tree", None)
        if nt is None:
            return False

        def _input(node, *names):
            for nm in names:
                inp = node.inputs.get(nm) if hasattr(node.inputs, 'get') else None
                if inp is not None:
                    return inp
            return None

        def _ge1(inp):
            if inp is None:
                return False
            if getattr(inp, 'is_linked', False):
                return True
            try:
                return float(inp.default_value) >= 1.0
            except (TypeError, ValueError):
                return True

        def _color_pos(inp):
            if inp is None:
                return False
            if getattr(inp, 'is_linked', False):
                return True
            try:
                return any(float(v) > 0.0 for v in inp.default_value[:3])
            except (TypeError, ValueError):
                return True

        for n in nt.nodes:
            t = getattr(n, "type", "")
            if t == 'EMISSION':
                return True
            if t == 'BSDF_PRINCIPLED':
                if _ge1(_input(n, 'Emission Strength')) and \
                        _color_pos(_input(n, 'Emission Color', 'Emission')):
                    return True
        return False

    def _object_instanceable(self, obj):
        """A mesh object is eligible for the two-level instancing fast-path only
        when it is a plain MESH with no instancing-deferred feature: no emissive
        material (NEE), no caustic-caster flag (SMS), no volume material. Anything
        else falls back to the flatten path (current behaviour, fully correct)."""
        if obj is None or obj.type != 'MESH':
            return False
        ao = getattr(obj, "astroray_object", None)
        if bool(getattr(ao, "is_caustic_caster", False)):
            return False
        vol_map = getattr(self, "_volume_material_map", {}) or {}
        for slot in obj.material_slots:
            mat = slot.material
            if mat is None:
                continue
            # vol_map holds a None placeholder for every material; only a non-None
            # spec means an actual volume (matches convert_objects' usage).
            if vol_map.get(mat.name) is not None:
                return False
            if self._material_emits(mat):
                return False
        return True

    def _register_instanced_groups(self, depsgraph, renderer, material_map, is_render):
        """pkg114 inc 3c — GPU fast-path: register each shared mesh datablock ONCE
        into a BLAS and emit one add_instance(matrix_world) per instance, instead
        of flattening every dupli into world-space triangles. Returns the set of
        object_instance ENUMERATION INDICES that were instanced (the caller skips
        them in the flatten loop). Empty set ⇒ nothing instanced (caller flattens
        everything, unchanged).

        Grouping key is (mesh datablock, obj.name): duplis of one source share the
        name → one shared BLAS + one Cryptomatte matte (matches the flatten path);
        linked duplicates have distinct names → distinct count-1 groups → they
        flatten (no regression). Only groups with >= 2 instances are worth it.

        pkg114 inc 3d wiring: also records `_renderer_instance_id_map`
        {source obj.name: [instance_id, ...] in dupli-enumeration order} so a
        later transform-only viewport edit can refit the TLAS instead of a full
        geometry re-upload, and `_renderer_instancer_eligible` {instancer obj.name:
        bool} so a moved instancer EMPTY can also refit. An instancer is eligible
        only when EVERY dupli it generated went through the shared BLAS (none
        flattened) and it is not itself nested — otherwise moving it also moves
        flat-scene geometry the refit wouldn't touch, so it must full-sync. Both
        maps are reset here so a full re-sync always rebuilds them (empty ⇒ nothing
        instanced ⇒ the transform path stays on full sync)."""
        self._renderer_instance_id_map = {}
        self._renderer_instancer_eligible = {}
        if not (hasattr(renderer, "register_mesh_bulk") and hasattr(renderer, "add_instance")):
            return set()
        settings = getattr(depsgraph.scene, "custom_raytracer", None)
        if settings is None or not self._render_will_use_gpu(settings, renderer):
            return set()
        if not BULK_GEOMETRY_UPLOAD:
            return set()

        # Pass A — collect eligible instances grouped by (datablock, name), and
        # track each instancer's generated duplis for the inc-3d empty-move guard.
        groups = {}      # key -> list of (enum_index, obj, matrix_world.copy())
        instancer_members = {}   # instancer name -> [member source obj.name, ...]
        instancer_nested = set()  # instancer names that generate a nested instancer
        for i, inst in enumerate(depsgraph.object_instances):
            obj = inst.object
            if obj is None:
                continue
            if is_render:
                if getattr(obj, 'hide_render', False):
                    continue
            elif getattr(obj, 'hide_viewport', False):
                continue
            # Record which instancer produced this (visible) dupli BEFORE the
            # instanceable filter — a flattened member still poisons its instancer.
            if getattr(inst, 'is_instance', False):
                parent = getattr(inst, 'parent', None)
                pname = getattr(parent, 'name', None) if parent is not None else None
                if pname is not None:
                    instancer_members.setdefault(pname, []).append(obj.name)
                    # A dupli whose source is itself an instancer ⇒ nested; refit
                    # of the outer empty can't reason about the inner TLAS → poison.
                    if getattr(obj, 'instance_type', 'NONE') not in ('NONE', None, ''):
                        instancer_nested.add(pname)
            if not self._object_instanceable(obj):
                continue
            key = (obj.data, obj.name)
            groups.setdefault(key, []).append((i, obj, inst.matrix_world.copy()))

        skip = set()
        instanced_names = set()  # source names that made it into a shared BLAS
        identity4 = mathutils.Matrix.Identity(4)
        identity3 = mathutils.Matrix.Identity(3)
        for (data, name), entries in groups.items():
            if len(entries) < 2:
                continue  # nothing shared → flatten (no instancing win)
            src_obj = entries[0][1]
            # OBJECT-LOCAL geometry (identity transform): the per-instance world
            # transform is supplied by add_instance(matrix_world).
            mesh = src_obj.data
            try:
                mesh.calc_loop_triangles()
            except Exception:
                continue
            n_tri = len(mesh.loop_triangles)
            if n_tri == 0:
                continue
            slot_to_id = {}
            for slot_idx, slot in enumerate(src_obj.material_slots):
                m = slot.material
                slot_to_id[slot_idx] = material_map.get(m.name, 0) if m is not None else 0
            default_mat_id = slot_to_id.get(0, 0)
            uv_items = []
            active_uv = mesh.uv_layers.active if mesh.uv_layers.active else None
            if active_uv is not None:
                uv_items.append((getattr(active_uv, "name", "") or "UVMap", active_uv.data))
            for layer in mesh.uv_layers:
                if layer is active_uv:
                    continue
                uv_items.append((getattr(layer, "name", "") or "UVMap", layer.data))
            positions, material_ids, mat_pass, uvs, uv_names, normals = \
                mesh_to_bulk_arrays(mesh, identity4, identity3,
                                    slot_to_id, default_mat_id, uv_items)
            mesh_id = renderer.register_mesh_bulk(
                positions, material_ids, mat_pass,
                int(getattr(src_obj, "pass_index", 0)), uvs, uv_names, normals,
                name)
            for enum_i, _obj, mw in entries:
                iid = renderer.add_instance(mesh_id, [v for row in mw for v in row])
                skip.add(enum_i)
                # pkg114 inc 3d: dupli-enumeration-ordered id list per source name,
                # keyed so the transform-only path can look the instances up by name
                # and refit them (matches the add_instance order used at refit time).
                self._renderer_instance_id_map.setdefault(name, []).append(iid)
            instanced_names.add(name)

        # pkg114 inc 3d: an instancer EMPTY is refit-eligible only if it is not
        # nested and EVERY dupli it generated went through the shared BLAS. If any
        # member flattened (count-1 linked dupe, emissive/caustic/volume, non-MESH),
        # moving the empty also moves flat-scene geometry a TLAS refit won't touch,
        # so that instancer must full-sync.
        for pname, member_names in instancer_members.items():
            self._renderer_instancer_eligible[pname] = (
                pname not in instancer_nested
                and all(m in instanced_names for m in member_names))
        if skip:
            print(f"Astroray: instanced {len(skip)} objects across "
                  f"{sum(1 for e in groups.values() if len(e) >= 2)} shared meshes (two-level BVH)")
        return skip

    def refit_instance_transforms(self, depsgraph, renderer):
        """pkg114 inc 3d — TLAS-only refit for a transform-only viewport edit.

        Re-walks `depsgraph.object_instances` in the SAME dupli-enumeration order
        `_register_instanced_groups` used, and pushes each registered instance's
        fresh `inst.matrix_world` onto its recorded instance id via
        `update_instance_transform` (CPU, in place). The caller then does one
        `upload_instance_transforms()` (re-push d_instances + d_tlas only) and
        renders with `skip_upload=True`. No BLAS geometry is touched.

        Every mapped instance is refreshed, not only the moved one — the whole TLAS
        is rebuilt from current transforms on upload regardless, so refreshing all
        is free and immune to per-object change-attribution subtleties (team-lead
        decision, 2026-07-17). The visibility filter mirrors registration so the
        per-name id cursor stays aligned for an unchanged topology."""
        id_map = getattr(self, '_renderer_instance_id_map', None)
        if not id_map:
            return
        is_render = getattr(depsgraph, 'mode', 'VIEWPORT') == 'RENDER'
        cursor = {name: 0 for name in id_map}
        for inst in depsgraph.object_instances:
            obj = inst.object
            if obj is None:
                continue
            if is_render:
                if getattr(obj, 'hide_render', False):
                    continue
            elif getattr(obj, 'hide_viewport', False):
                continue
            ids = id_map.get(obj.name)
            if not ids:
                continue
            k = cursor[obj.name]
            if k >= len(ids):
                continue  # topology drifted since registration — skip (full sync
                          # would have been taken for a genuine geometry change).
            mw = inst.matrix_world
            renderer.update_instance_transform(ids[k], [v for row in mw for v in row])
            cursor[obj.name] = k + 1

    def convert_objects(self, depsgraph, renderer, material_map,
                        motion_start_matrices=None, motion_end_matrices=None):
        """`motion_start_matrices` / `motion_end_matrices` (pkg88-B, optional):
        {obj.name: matrix_world at shutter open / shutter close}, computed once
        each by convert_scene (empty/None when motion blur is off, or when
        called directly like the viewport-sync path in exporter.py, which
        doesn't bake object motion).

        BOTH endpoints are needed and neither is the object's current pose. The
        renderer blends positions_start at ray time=0 and positions_end at
        time=1 (`Triangle::hit`, include/astroray/shapes.h), and `Camera::getRay`
        maps that same time across t_start -> t_end, so positions_start must be
        the t_start pose for object blur to line up with camera blur. Using the
        current (frame) pose instead silently halves the CENTER arc and disables
        END entirely (t_end == frame there, so nothing ever reads as moving).

        Instancing interaction (pkg114 two-level BVH/TLAS): `_register_instanced_groups`
        below runs FIRST and is entirely unaware of motion -- it always builds its
        shared BLAS from the CURRENT (un-shifted) geometry. An object that both (a)
        qualifies for GPU instancing (>=2 duplis sharing the same (mesh data, name),
        the pkg114 grouping key) AND (b) is independently rigid-transform-animated
        stays on the EXISTING static instancing path and gets NO motion blur -- it
        renders at its current-frame pose for every instance, same as pre-pkg88-B.
        This is a pre-existing pkg114 limitation ("Deformation motion on INSTANCED
        meshes is out of scope v1", pkg88-C.0 status note); Phase B does not change
        it. Only REAL (non-dupli) objects are considered for motion baking below
        (`getattr(obj_instance, 'is_instance', False)`); dupli/particle/geometry-node
        instance motion (per-dupli transforms from a particle system etc.) is out of
        scope for v1 -- reliably re-evaluating per-dupli identity at a different
        frame is a materially harder problem than a single object's matrix_world and
        isn't attempted here. Because instanced entries are skipped via
        `instanced_indices` BEFORE this loop runs, the instanced and motion-baked
        code paths are mutually exclusive by construction -- no mixed/corrupted
        state is possible either way.
        """
        motion_start_matrices = motion_start_matrices or {}
        motion_end_matrices = motion_end_matrices or {}
        tri_count = 0
        obj_count = 0
        is_render = getattr(depsgraph, 'mode', 'VIEWPORT') == 'RENDER'
        active_view_layer = getattr(depsgraph, "view_layer", None)
        # pkg114 inc 3c — GPU two-level instancing fast-path: register shared mesh
        # datablocks once + add_instance per dupli, and skip those instances in the
        # flatten loop below. No-op (empty set) on CPU / when ineligible.
        instanced_indices = self._register_instanced_groups(
            depsgraph, renderer, material_map, is_render)
        for _inst_idx, obj_instance in enumerate(depsgraph.object_instances):
            if _inst_idx in instanced_indices:
                continue
            obj = obj_instance.object
            if obj is None:
                continue
            # Use the visibility flag appropriate to the evaluation context.
            # Passing view_layer= to visible_get() checks against that specific
            # layer and returns False when depsgraph.view_layer doesn't match
            # the active viewport layer, hiding all objects. Instead:
            #   render path  → honour the "hide for render" toggle
            #   viewport path → honour the "hide in viewport" toggle
            if is_render:
                if getattr(obj, 'hide_render', False):
                    continue
            else:
                if getattr(obj, 'hide_viewport', False):
                    continue

            # Black hole empties
            if obj.type == 'EMPTY' and hasattr(obj, 'astroray_black_hole'):
                bh = obj.astroray_black_hole
                if bh.mass > 0:
                    try:
                        mw = obj_instance.matrix_world
                        params = {
                            'disk_outer':     bh.disk_outer,
                            'accretion_rate': bh.accretion_rate,
                            'inclination':    bh.inclination,
                            'enable_jet':     bh.enable_jet,
                            'lorentz_factor': bh.jet_lorentz_factor,
                            'half_angle_degrees': bh.jet_half_angle,
                            'power_law_index': bh.jet_power_law_index,
                            'base_density': bh.jet_base_density,
                            'magnetic_field': bh.jet_magnetic_field,
                        }
                        # pkg107: r_obs_M world-to-GR scale (default 100, smaller → bigger shadow)
                        if hasattr(bh, 'r_obs_M'):
                            params['r_obs_M'] = bh.r_obs_M
                        # General Kerr spin (Schwarzschild = 0)
                        if hasattr(bh, 'spin'):
                            params['spin'] = bh.spin
                        # pkg43: accretion model selector
                        if hasattr(bh, 'accretion_model'):
                            params['accretion_model'] = bh.accretion_model
                            # Slim disk specific parameters
                            if bh.accretion_model == 'SLIM_DISK':
                                params['slim_disk_spin'] = bh.slim_disk_spin
                                params['slim_disk_r_inner'] = bh.slim_disk_r_inner
                                params['slim_disk_intensity_scale'] = bh.slim_disk_intensity_scale
                                params['slim_disk_base_density'] = bh.slim_disk_base_density
                            # pkg44: ADAF parameters
                            elif bh.accretion_model == 'ADAF':
                                params['enable_adaf'] = True
                                params['adaf_mdot_edd'] = bh.adaf_mdot_edd
                                params['adaf_electron_temp'] = bh.adaf_electron_temp
                                params['adaf_beta_mag'] = bh.adaf_beta_mag
                                params['adaf_r_inner'] = bh.adaf_r_inner
                                params['adaf_r_outer'] = bh.adaf_r_outer
                                params['adaf_flattening'] = bh.adaf_flattening
                                params['adaf_alpha'] = bh.adaf_alpha
                                params['adaf_s'] = bh.adaf_s
                                params['adaf_intensity_scale'] = bh.adaf_intensity_scale
                        renderer.add_black_hole(
                            [mw.translation.x, mw.translation.y, mw.translation.z],
                            bh.mass,
                            bh.influence_radius,
                            params
                        )
                    except Exception as e:
                        print(f"Black hole conversion error: {e}")
                continue

            # pkg117: render to_mesh()-able non-MESH geometry (curve/text/metaball/
            # surface) by evaluating it to a temporary mesh, mirroring Cycles
            # (intern/cycles/blender/mesh.cpp BlenderSync::sync_mesh). Objects from
            # depsgraph.object_instances are already evaluated, so modifiers and
            # curve/text/metaball resolution apply. The temporary mesh must be freed
            # with to_mesh_clear() once its triangles are uploaded.
            _temp_mesh = False
            if obj.type == 'MESH':
                mesh = obj.data
            elif obj.type in {'CURVE', 'SURFACE', 'FONT', 'META'}:
                try:
                    mesh = obj.to_mesh()
                except Exception as e:
                    print(f"Astroray: to_mesh() failed on '{obj.name}': {e}")
                    mesh = None
                if mesh is None:
                    # Empty curves and non-basis metaball members produce no mesh.
                    continue
                _temp_mesh = True
            else:
                continue

            if mesh is None:
                continue
            matrix = obj_instance.matrix_world
            obj_count += 1

            # pkg88-B: object motion blur candidate. Only real (non-dupli)
            # objects whose pose actually changes ACROSS THE SHUTTER (t_start vs
            # t_end -- NOT vs the current frame pose, which is a different
            # instant for CENTER/END) are eligible; see the instancing-
            # interaction note in this method's docstring. Everything else keeps
            # the static add_triangles_bulk path below untouched.
            motion_start_matrix = motion_end_matrix = None
            if motion_end_matrices and not getattr(obj_instance, 'is_instance', False):
                _start_mw = motion_start_matrices.get(obj.name)
                _end_mw = motion_end_matrices.get(obj.name)
                if (_start_mw is not None and _end_mw is not None
                        and _matrices_differ(_start_mw, _end_mw)):
                    motion_start_matrix, motion_end_matrix = _start_mw, _end_mw

            volume_spec = None
            for slot in obj.material_slots:
                mat = slot.material
                if mat is None:
                    continue
                spec = self._volume_material_map.get(mat.name) if hasattr(self, '_volume_material_map') else None
                if spec is not None:
                    volume_spec = spec
                    break

            if volume_spec is not None:
                try:
                    bbox_points = [matrix @ mathutils.Vector(corner) for corner in obj.bound_box]
                    center = sum(bbox_points, mathutils.Vector((0.0, 0.0, 0.0))) / len(bbox_points)
                    radius = max((p - center).length for p in bbox_points)
                    density = max(0.0, float(volume_spec.get('density', 0.0)))
                    if radius > 0.0 and density > 0.0:
                        renderer.add_volume(
                            [center.x, center.y, center.z],
                            float(radius),
                            density,
                            list(volume_spec.get('color', [1.0, 1.0, 1.0])),
                            float(volume_spec.get('anisotropy', 0.0)),
                            float(volume_spec.get('emission_strength', 0.0)),
                            list(volume_spec.get('emission_color', [0.0, 0.0, 0.0])),
                        )
                except Exception as e:
                    print(f"Astroray: volume conversion error on '{obj.name}': {e}")

            # -------- Per-slot material map --------
            # Blender meshes carry one material_index per face; resolve each
            # slot once up front, then look up by index inside the hot loop.
            slot_to_id = {}
            for slot_idx, slot in enumerate(obj.material_slots):
                mat = slot.material
                if mat is not None and mat.name in material_map:
                    slot_to_id[slot_idx] = material_map[mat.name]
                else:
                    slot_to_id[slot_idx] = 0
            default_mat_id = slot_to_id.get(0, 0)

            # -------- pkg115 generated-coords bbox bake --------
            # GENERATED coordinates = object-local position normalized to the
            # object's bounding box (Blender Texture Coordinate > Generated;
            # Cycles orco). The exporter bakes world transforms into vertices,
            # so the WORLD-space bbox of this object is the right frame here.
            # Shared-material multi-object scenes: last writer wins (per-object
            # texture instancing is a recorded follow-up).
            gen_by_mat = getattr(self, "_generated_textures_by_material", {})
            if gen_by_mat and hasattr(renderer, "set_texture_generated_bbox"):
                gen_texs = []
                for slot in obj.material_slots:
                    if slot.material is not None:
                        gen_texs.extend(gen_by_mat.get(slot.material.name, ()))
                if gen_texs:
                    corners = [matrix @ mathutils.Vector(c)
                               for c in obj.bound_box]
                    bmin = [min(c[i] for c in corners) for i in range(3)]
                    bmax = [max(c[i] for c in corners) for i in range(3)]
                    bsize = [max(bmax[i] - bmin[i], 1e-6) for i in range(3)]
                    for tex_name in set(gen_texs):
                        renderer.set_texture_generated_bbox(
                            tex_name, bmin, bsize)

            # -------- Normal transform --------
            # Normals transform by the INVERSE TRANSPOSE of the model matrix's
            # 3x3 rotation/scale block. Using the model matrix directly would
            # skew normals under non-uniform scaling.
            try:
                normal_matrix = matrix.to_3x3().inverted_safe().transposed()
            except Exception:
                normal_matrix = matrix.to_3x3()

            # pkg64 Phase 3 — record the renderer scene size before this
            # object's triangles are pushed; after the loop we flip the
            # caustic-caster flag on the [pre, post) range.
            ao = getattr(obj, "astroray_object", None)
            is_caustic_caster = bool(getattr(ao, "is_caustic_caster", False))
            scene_count_before = (renderer.scene_object_count()
                                  if hasattr(renderer, "scene_object_count") else 0)

            mesh.calc_loop_triangles()
            # split_normals carries the correct per-corner normal for
            # smooth/flat/custom shading. Available since Blender 4.1; on
            # older versions we silently skip it (fall back to face normals).
            uv_layer_items = []
            active_uv = mesh.uv_layers.active if mesh.uv_layers.active else None
            if active_uv is not None:
                uv_layer_items.append((getattr(active_uv, "name", "") or "UVMap", active_uv.data))
            for layer in mesh.uv_layers:
                if layer is active_uv:
                    continue
                uv_layer_items.append((getattr(layer, "name", "") or "UVMap", layer.data))
            uv_data = uv_layer_items[0][1] if uv_layer_items else None

            n_tri = len(mesh.loop_triangles)
            # pkg112: bulk geometry upload — fill contiguous NumPy arrays with
            # Blender's C-speed foreach_get and push the whole mesh in ONE
            # add_triangles_bulk() call instead of one pybind round-trip per
            # triangle (the dominant geometry-sync cost on big meshes). Pixel-
            # identical to the per-tri fallback below: same world transform, same
            # slot→id remap, same active-first UV-layer order, same inverse-
            # transpose corner normals. Falls back when the engine build lacks the
            # bulk binding (older .pyd) or when BULK_GEOMETRY_UPLOAD is disabled.
            if (BULK_GEOMETRY_UPLOAD and n_tri > 0
                    and hasattr(renderer, "add_triangles_bulk")):
                positions, material_ids, mat_pass, uvs, uv_names, normals = \
                    mesh_to_bulk_arrays(mesh, matrix, normal_matrix,
                                        slot_to_id, default_mat_id, uv_layer_items)
                # pkg88-B: motion candidates go through add_triangles_bulk_motion
                # with the SHUTTER-OPEN pose as positions_start (NOT `positions`,
                # which mesh_to_bulk_arrays built from the current-frame matrix --
                # a different instant for CENTER/END) and the shutter-close pose
                # as positions_end. Cycles motion_triangle.h (Apache-2.0) linear
                # blend; the renderer reads positions_start at ray time=0 and
                # positions_end at time=1. Only the bulk path supports motion --
                # the no-bulk fallback below has no motion twin, so a moving
                # object without bulk support silently stays static.
                # UVs/normals/material arrays are pose-independent, so `positions`
                # is the only piece of mesh_to_bulk_arrays' output replaced here.
                if motion_end_matrix is not None and hasattr(renderer, "add_triangles_bulk_motion"):
                    positions_start = mesh_world_positions(mesh, motion_start_matrix)
                    positions_end = mesh_world_positions(mesh, motion_end_matrix)
                    renderer.add_triangles_bulk_motion(
                        positions_start, positions_end, material_ids, mat_pass,
                        int(getattr(obj, "pass_index", 0)), uvs, uv_names, normals)
                else:
                    renderer.add_triangles_bulk(
                        positions, material_ids, mat_pass,
                        int(getattr(obj, "pass_index", 0)), uvs, uv_names, normals)
                tri_count += n_tri
            else:
                for tri in mesh.loop_triangles:
                    v0 = matrix @ mesh.vertices[tri.vertices[0]].co
                    v1 = matrix @ mesh.vertices[tri.vertices[1]].co
                    v2 = matrix @ mesh.vertices[tri.vertices[2]].co

                    # Per-face material index
                    mat_id = slot_to_id.get(tri.material_index, default_mat_id)

                    # UVs
                    uv0 = uv1 = uv2 = []
                    if uv_data is not None:
                        uv0 = list(uv_data[tri.loops[0]].uv)
                        uv1 = list(uv_data[tri.loops[1]].uv)
                        uv2 = list(uv_data[tri.loops[2]].uv)
                    uv_layers = {}
                    if len(uv_layer_items) > 1:
                        for layer_name, layer_data in uv_layer_items:
                            uv_layers[layer_name] = [
                                list(layer_data[tri.loops[0]].uv),
                                list(layer_data[tri.loops[1]].uv),
                                list(layer_data[tri.loops[2]].uv),
                            ]

                    # Per-corner normals (Blender 4.1+). Fall back gracefully.
                    n0 = n1 = n2 = []
                    try:
                        sn = tri.split_normals
                        raw_n0 = mathutils.Vector(sn[0])
                        raw_n1 = mathutils.Vector(sn[1])
                        raw_n2 = mathutils.Vector(sn[2])
                        n0 = list((normal_matrix @ raw_n0).normalized())
                        n1 = list((normal_matrix @ raw_n1).normalized())
                        n2 = list((normal_matrix @ raw_n2).normalized())
                    except (AttributeError, IndexError):
                        n0 = n1 = n2 = []

                    if uv_layers and hasattr(renderer, "add_triangle_layers"):
                        renderer.add_triangle_layers(
                            list(v0), list(v1), list(v2), mat_id,
                            uv_layers,
                            n0, n1, n2,
                            int(getattr(obj, "pass_index", 0)),
                            int(tri.material_index),
                        )
                    else:
                        renderer.add_triangle(
                            list(v0), list(v1), list(v2), mat_id,
                            uv0, uv1, uv2,
                            n0, n1, n2,
                            int(getattr(obj, "pass_index", 0)),
                            int(tri.material_index),
                        )
                    tri_count += 1

            # Flip the caustic-caster flag and set Cryptomatte names on every
            # renderer object the current Blender object contributed (one Blender
            # mesh → many add_triangle calls).
            scene_count_after = (renderer.scene_object_count()
                                 if hasattr(renderer, "scene_object_count") else 0)
            for oid in range(scene_count_before, scene_count_after):
                # pkg64 Phase 3 — caustic caster flag
                if is_caustic_caster and hasattr(renderer, "set_object_caustic_caster"):
                    renderer.set_object_caustic_caster(oid, True)
                # pkg87c — Cryptomatte object name
                if hasattr(renderer, "set_object_name"):
                    renderer.set_object_name(oid, obj.name)

            # pkg117: free the temporary mesh produced by to_mesh() for non-MESH
            # geometry. Blender requires an explicit to_mesh_clear(); plain meshes
            # (obj.data) are not temporary and must NOT be cleared.
            if _temp_mesh:
                obj.to_mesh_clear()

        print(f"Astroray: converted {obj_count} meshes, {tri_count} triangles")

    def convert_lights(self, depsgraph, renderer):
        def _resolve_ies_path(light_data):
            cycles_settings = getattr(light_data, 'cycles', None)
            candidates = []
            for source in (cycles_settings, light_data):
                if source is None:
                    continue
                for name in ('ies', 'ies_file', 'ies_profile'):
                    value = getattr(source, name, None)
                    if value:
                        candidates.append(value)
            for value in candidates:
                if hasattr(value, 'filepath') and value.filepath:
                    return bpy.path.abspath(value.filepath)
                if isinstance(value, str) and value:
                    return bpy.path.abspath(value)
            return ""

        def _build_emission_dict(light):
            # pkg89 Phase B: construct EmissionSpectrum dict from Blender light properties.
            # Q-Owner-1 resolution: default to blackbody (D65 6500K) with color as tint filter.
            # Blender 4.5+ has light.use_temperature toggle; fallback to RGB if not available.
            #
            # pkg195 Stage B: preset / custom_profile spectrum modes emit a
            # MeasuredSPD wrapped in a Composite so the light colour remains a
            # gel tint (blender_module.cpp parseEmissionSpectrum already handles
            # both 'measured_spd' and 'composite'). Native mode is unchanged.
            profile_name = _light_spectrum_profile(light)
            if profile_name:
                measured = {'mode': 'measured_spd', 'profile_name': profile_name}
                tint = list(light.color)
                # Skip the composite wrapper when the tint is (near-)white so the
                # SPD reaches the engine unmodulated.
                if all(abs(c - 1.0) < 1e-4 for c in tint):
                    return measured
                return {
                    'mode': 'composite',
                    'base': measured,
                    'filter_rgb': tint,
                }
            use_temp = getattr(light, 'use_temperature', False)
            if use_temp and hasattr(light, 'temperature'):
                # Blackbody mode: temperature + color as tint filter.
                temp_k = float(light.temperature)
                tint = list(light.color)  # RGB tint (filter on top of blackbody)
                return {
                    'mode': 'blackbody',
                    'temperature_K': temp_k,
                    'tint_rgb': tint
                }
            else:
                # RGB upsample mode (Jakob-Hanika).
                return {
                    'mode': 'rgb',
                    'color': list(light.color)
                }

        # Iterate object_instances (not depsgraph.objects) so lights created by
        # instancing (collection instances, particle/dupli systems) are rendered,
        # matching convert_objects. Real (non-instanced) lights still appear once
        # with is_instance=False, so existing non-instanced scenes are unaffected.
        for obj_instance in depsgraph.object_instances:
            obj = obj_instance.object
            if obj is None or obj.type != 'LIGHT': continue
            light = obj.data
            matrix = obj_instance.matrix_world
            position = list(matrix.translation)
            ies_path = _resolve_ies_path(light)
            emission_dict = _build_emission_dict(light)
            intensity = float(light.energy)
            pass_idx = int(getattr(obj, "pass_index", 0))

            if light.type == 'POINT':
                # pkg89 Phase B: use dedicated PointLight (no more 0.1 m sphere hack).
                radius = float(max(getattr(light, 'shadow_soft_size', 0.0), 0.0))
                renderer.add_point_light(
                    position, emission_dict, intensity, radius, ies_path, pass_idx, 0
                )
            elif light.type == 'SUN':
                # pkg89 Phase B: use dedicated DistantLight with EmissionSpectrum.
                direction = matrix.to_3x3() @ mathutils.Vector((0, 0, -1))
                angle = float(getattr(light, 'angle', 0.0))
                renderer.add_sun_light_dedicated(
                    [direction.x, direction.y, direction.z], angle, emission_dict, intensity,
                    pass_idx, 0
                )
            elif light.type == 'AREA':
                # pkg89 Phase B: use dedicated AreaLight with EmissionSpectrum.
                # pkg139: AreaLight emits along u x v (area_light.h:59). Cycles area
                # lights emit along local -Z (intern/cycles/blender/light.cpp
                # BlenderSync::sync_light: axisu=local X, axisv=local Y, direction=-Z
                # of the light transform) -- the same convention already used here
                # for SUN (:3941) and SPOT (:3971 below). Using +Y for axis_v made
                # u x v = +Z, pointing the light away from the scene at identity
                # rotation (measured 0.089-0.116x vs Cycles). Flipping axis_v to -Y
                # gives u x v = X x (-Y) = -Z, matching Cycles (measured 1.07-1.09x
                # at the same rotation). size_x/size_y still map to u/v respectively;
                # this flip only mirrors v about u, which is a no-op for the centered
                # RECTANGLE/ELLIPSE/DISK shapes we support (symmetric about center).
                basis = matrix.to_3x3()
                axis_u = list((basis @ mathutils.Vector((1, 0, 0))).normalized())
                axis_v = list((basis @ mathutils.Vector((0, -1, 0))).normalized())
                shape = getattr(light, 'shape', 'SQUARE')
                spread = float(getattr(light, 'spread', 1.0))
                size_x = float(light.size)
                size_y = float(getattr(light, 'size_y', light.size))
                if shape in {'SQUARE', 'DISK'}:
                    size_y = size_x
                shape_map = {
                    'SQUARE': 'RECTANGLE',
                    'RECTANGLE': 'RECTANGLE',
                    'DISK': 'DISK',
                    'ELLIPSE': 'ELLIPSE',
                }
                renderer.add_area_light_dedicated(
                    position, axis_u, axis_v, size_x, size_y,
                    shape_map.get(shape, 'RECTANGLE'), emission_dict, intensity, spread,
                    pass_idx, 0
                )
            elif light.type == 'SPOT':
                # pkg89 Phase B: use dedicated SpotLight with EmissionSpectrum.
                direction = (matrix.to_3x3() @ mathutils.Vector((0, 0, -1))).normalized()
                radius = float(max(getattr(light, 'shadow_soft_size', 0.0), 0.0))
                # Blender spot_size is the full cone angle; we need outer half-angle.
                outer_angle = float(light.spot_size) / 2.0
                # Blender spot_blend is the blend zone fraction; compute inner angle.
                blend_fraction = float(light.spot_blend)
                inner_angle = outer_angle * (1.0 - blend_fraction)
                renderer.add_spot_light_dedicated(
                    position,
                    [direction.x, direction.y, direction.z],
                    inner_angle,
                    outer_angle,
                    emission_dict,
                    intensity,
                    radius,
                    ies_path,
                    pass_idx,
                    0,
                )

    def setup_world(self, scene, renderer):
        world = scene.world
        if not world:
            renderer.set_world_volume(0.0, [1.0, 1.0, 1.0], 0.0)
            return

        # Check for node tree (use_nodes is deprecated in Blender 5.x, always True)
        node_tree = getattr(world, 'node_tree', None)
        if not node_tree:
            renderer.set_world_volume(0.0, [1.0, 1.0, 1.0], 0.0)
            return

        # pkg63: Walk the world node tree for full Blender Mapping parity.
        # Cycles equivalent: intern/cycles/blender/shader.cpp add_nodes() converts
        # the entire tree (Apache-2.0). We extract the subset we render against:
        #   - TEX_ENVIRONMENT.image.filepath  → HDRI
        #   - BACKGROUND.Strength             → strength
        #   - BACKGROUND.Color (linked or not) → color tint, follows Mix/RGB nodes
        #   - MAPPING.Rotation (X, Y, Z)      → baked XYZ Euler rotation matrix
        hdri_path = None
        strength = 1.0
        rx = 0.0
        ry = 0.0
        rz = 0.0
        tint = [1.0, 1.0, 1.0]    # multiplicative Background.Color tint (default white)
        bg_color = None           # solid background fallback when no HDRI

        for node in node_tree.nodes:
            if node.type == 'TEX_ENVIRONMENT' and node.image:
                hdri_path = bpy.path.abspath(node.image.filepath)
            elif node.type == 'BACKGROUND':
                strength = float(node.inputs['Strength'].default_value)
                color_input = node.inputs.get('Color')
                if color_input is not None:
                    if not color_input.is_linked:
                        bg_color = list(color_input.default_value[:3])
                        # When no HDRI is loaded, this becomes the solid background;
                        # when an HDRI is loaded, this acts as a tint multiplier.
                        tint = list(bg_color)
                    else:
                        # pkg63: follow the linked node chain (Mix/RGB/Gamma/etc.)
                        # via _get_socket_color, falling back to [1,1,1] on failure.
                        evaluated = self._get_socket_color(color_input)
                        if evaluated is not None:
                            tint = list(evaluated)
            elif node.type == 'MAPPING':
                rot_input = node.inputs.get('Rotation')
                if rot_input:
                    # Blender Mapping uses XYZ Euler order (matches Cycles MappingNode).
                    rx = float(rot_input.default_value[0])
                    ry = float(rot_input.default_value[1])
                    rz = float(rot_input.default_value[2])

        output = next((n for n in node_tree.nodes if n.type == 'OUTPUT_WORLD'), None)
        volume_spec = None
        if output is not None:
            volume_node = self._shader_input_node(output, 'Volume')
            if volume_node is not None and volume_node.type in {'VOLUME_SCATTER', 'PRINCIPLED_VOLUME'}:
                volume_spec = self.convert_volume_node(volume_node, node_tree)
        if volume_spec and float(volume_spec.get('density', 0.0)) > 0.0:
            renderer.set_world_volume(
                float(volume_spec['density']),
                list(volume_spec['color']),
                float(volume_spec.get('anisotropy', 0.0)),
            )
        else:
            renderer.set_world_volume(0.0, [1.0, 1.0, 1.0], 0.0)

        # Apply world bounce limit (Cycles: world.cycles.max_bounces). pkg201
        # Finding B: the prior read used world.light_settings.max_bounces, but
        # light_settings is the ambient-occlusion datablock (WorldLighting) and
        # has NO max_bounces member, so getattr(..., 1024) always won and the
        # control was inert. The real Cycles world light-path prop is
        # world.cycles.max_bounces; keep a getattr default for worlds without a
        # cycles block (non-Cycles scene / test stub) so nothing hard-crashes.
        world_cycles = getattr(world, 'cycles', None)
        world_max_bounces = int(getattr(world_cycles, 'max_bounces', 1024)) if world_cycles else 1024
        renderer.set_world_max_bounces(world_max_bounces)

        # Try loading HDRI first.
        # pkg63: pass full XYZ rotation + RGB color tint; blender_convention=True
        # bakes the Astroray->Blender coord-swap into the rotation matrix.
        if hdri_path and os.path.exists(hdri_path):
            success = renderer.load_environment_map(
                hdri_path, strength,
                rx, ry, rz,
                tint[0], tint[1], tint[2],
                True,  # blender_convention
            )
            if success:
                print(f"Loaded HDRI: {hdri_path} "
                      f"(strength={strength}, rot=({rx:.2f},{ry:.2f},{rz:.2f}), "
                      f"tint=({tint[0]:.2f},{tint[1]:.2f},{tint[2]:.2f}))")
                return
            else:
                print(f"Failed to load HDRI: {hdri_path}")

        # Fallback: solid background color.
        # pkg139: strength == 0.0 is artist intent for a black background, not
        # "no background set" -- previously the `strength > 0.01` guard skipped
        # set_background_color entirely at strength 0, leaving the engine's
        # built-in default background visible instead of black. Always call
        # set_background_color when bg_color is present; strength 0 scales it
        # to explicit black.
        if bg_color is not None:
            scaled_color = [c * strength for c in bg_color]
            renderer.set_background_color(scaled_color)
            print(f"Set background color: {scaled_color}")

    def write_pixels(self, pixels, width, height, alpha=None, renderer=None, view_layer=None, scene=None, layer_name=None):
        # The raytracer returns pixels with y=0 at the TOP of the image (standard
        # image convention). Blender's render_pass.rect expects y=0 at the BOTTOM,
        # so we flip vertically before handing it off — otherwise the output ends
        # up mirrored across the horizontal axis (upside-down).
        rgba = np.ones((height, width, 4), dtype=np.float32)
        rgba[:, :, :3] = pixels
        if alpha is not None:
            alpha_arr = np.asarray(alpha, dtype=np.float32)
            if alpha_arr.shape == (height, width):
                rgba[:, :, 3] = np.clip(alpha_arr, 0.0, 1.0)
        rgba = np.ascontiguousarray(rgba[::-1])

        if layer_name:
            result = self.begin_result(0, 0, width, height, layer=layer_name)
        else:
            result = self.begin_result(0, 0, width, height)
        layer = result.layers[0]
        render_pass = layer.passes.get("Combined")
        if render_pass is None and len(layer.passes) == 1:
            # Legacy compatibility: some Blender builds expose only one pass in
            # this collection. In multi-pass configurations, never fall back to
            # the first pass to avoid overwriting a non-Combined layer.
            render_pass = layer.passes[0]
        if render_pass:
            # foreach_set is ~100x faster than assigning a Python list to .rect
            flat = rgba.reshape(-1)
            try:
                render_pass.rect.foreach_set(flat)
            except AttributeError:
                render_pass.rect = rgba.reshape(-1, 4).tolist()

        if renderer is not None and view_layer is not None:
            for display_name, key in self._enabled_pass_specs(view_layer):
                target_pass = layer.passes.get(display_name)
                if target_pass is None:
                    continue
                try:
                    pass_pixels = renderer.get_render_pass_buffer(key)
                except Exception:
                    continue
                pass_rgba = np.ones((height, width, 4), dtype=np.float32)
                pass_rgba[:, :, :3] = np.asarray(pass_pixels, dtype=np.float32)
                pass_rgba = np.ascontiguousarray(pass_rgba[::-1])
                pass_flat = pass_rgba.reshape(-1)
                try:
                    target_pass.rect.foreach_set(pass_flat)
                except AttributeError:
                    target_pass.rect = pass_rgba.reshape(-1, 4).tolist()

            for display_name, key in self._enabled_data_pass_specs(view_layer):
                target_pass = layer.passes.get(display_name)
                if target_pass is None:
                    continue
                try:
                    if key == "albedo":
                        data_pixels = np.asarray(renderer.get_albedo_buffer(), dtype=np.float32)
                        pass_rgba = np.ones((height, width, 4), dtype=np.float32)
                        pass_rgba[:, :, :3] = data_pixels
                    elif key == "normal":
                        data_pixels = np.asarray(renderer.get_normal_buffer(), dtype=np.float32)
                        pass_rgba = np.ones((height, width, 4), dtype=np.float32)
                        pass_rgba[:, :, :3] = data_pixels
                    elif key == "position":
                        data_pixels = np.asarray(renderer.get_position_buffer(), dtype=np.float32)
                        pass_rgba = np.ones((height, width, 4), dtype=np.float32)
                        pass_rgba[:, :, :3] = data_pixels
                    elif key == "uv":
                        data_pixels = np.asarray(renderer.get_uv_buffer(), dtype=np.float32)
                        pass_rgba = np.ones((height, width, 4), dtype=np.float32)
                        pass_rgba[:, :, :3] = data_pixels
                    elif key == "depth":
                        depth = np.asarray(renderer.get_depth_buffer(), dtype=np.float32)
                        pass_rgba = np.ones((height, width, 4), dtype=np.float32)
                        pass_rgba[:, :, :3] = depth[:, :, None]
                    elif key == "mist":
                        depth = np.asarray(renderer.get_depth_buffer(), dtype=np.float32)
                        mist_settings = getattr(getattr(scene, "world", None), "mist_settings", None)
                        mist_start = float(getattr(mist_settings, "start", 0.0)) if mist_settings else 0.0
                        mist_depth = float(getattr(mist_settings, "depth", 25.0)) if mist_settings else 25.0
                        mist_depth = max(mist_depth, 1e-6)
                        mist = 1.0 - np.clip((depth - mist_start) / mist_depth, 0.0, 1.0)
                        pass_rgba = np.ones((height, width, 4), dtype=np.float32)
                        pass_rgba[:, :, :3] = mist[:, :, None]
                    elif key == "object_index":
                        idx_data = np.asarray(renderer.get_object_index_buffer(), dtype=np.float32)
                        pass_rgba = np.ones((height, width, 4), dtype=np.float32)
                        pass_rgba[:, :, :3] = idx_data[:, :, None]
                    elif key == "material_index":
                        idx_data = np.asarray(renderer.get_material_index_buffer(), dtype=np.float32)
                        pass_rgba = np.ones((height, width, 4), dtype=np.float32)
                        pass_rgba[:, :, :3] = idx_data[:, :, None]
                    else:
                        continue
                except Exception:
                    continue
                pass_rgba = np.ascontiguousarray(pass_rgba[::-1])
                pass_flat = pass_rgba.reshape(-1)
                try:
                    target_pass.rect.foreach_set(pass_flat)
                except AttributeError:
                    target_pass.rect = pass_rgba.reshape(-1, 4).tolist()

            # pkg87c: Pack Cryptomatte ranked histograms into RGBA layers
            # Per Psyop spec: each RGBA layer holds 2 (id, weight) pairs
            # .R = id(2k), .G = weight(2k), .B = id(2k+1), .A = weight(2k+1)
            crypto_obj_specs = [(dn, k) for dn, k, _ in self._cryptomatte_pass_specs(scene) if k == "cryptomatte_object"]
            crypto_mat_specs = [(dn, k) for dn, k, _ in self._cryptomatte_pass_specs(scene) if k == "cryptomatte_material"]

            try:
                crypto_obj_raw = np.asarray(renderer.get_cryptomatte_object_buffer(), dtype=np.float32)  # [H, W, depth*2]
                crypto_mat_raw = np.asarray(renderer.get_cryptomatte_material_buffer(), dtype=np.float32)  # [H, W, depth*2]
            except Exception:
                crypto_obj_raw = crypto_mat_raw = None

            if crypto_obj_raw is not None and crypto_mat_raw is not None:
                # Extract dims: depth*2 = [id0, weight0, id1, weight1, ...]
                depth = crypto_obj_raw.shape[2] // 2  # e.g., shape[2] = 12 → depth = 6
                numLayers = (depth + 1) // 2  # depth 6 → 3 layers

                # Pack object layers
                for layerIdx in range(numLayers):
                    display_name = f"CryptoObject{layerIdx:02d}"
                    if not getattr(view_layer, "use_pass_cryptomatte_object", False):
                        continue
                    target_pass = layer.passes.get(display_name)
                    if target_pass is None:
                        continue

                    rank0 = layerIdx * 2
                    rank1 = rank0 + 1
                    pass_rgba = np.zeros((height, width, 4), dtype=np.float32)
                    if rank0 < depth:
                        pass_rgba[:, :, 0] = crypto_obj_raw[:, :, rank0 * 2]       # id(2k)
                        pass_rgba[:, :, 1] = crypto_obj_raw[:, :, rank0 * 2 + 1]  # weight(2k)
                    if rank1 < depth:
                        pass_rgba[:, :, 2] = crypto_obj_raw[:, :, rank1 * 2]       # id(2k+1)
                        pass_rgba[:, :, 3] = crypto_obj_raw[:, :, rank1 * 2 + 1]  # weight(2k+1)

                    pass_rgba = np.ascontiguousarray(pass_rgba[::-1])  # flip Y
                    pass_flat = pass_rgba.reshape(-1)
                    try:
                        target_pass.rect.foreach_set(pass_flat)
                    except AttributeError:
                        target_pass.rect = pass_rgba.reshape(-1, 4).tolist()

                # Pack material layers
                for layerIdx in range(numLayers):
                    display_name = f"CryptoMaterial{layerIdx:02d}"
                    if not getattr(view_layer, "use_pass_cryptomatte_material", False):
                        continue
                    target_pass = layer.passes.get(display_name)
                    if target_pass is None:
                        continue

                    rank0 = layerIdx * 2
                    rank1 = rank0 + 1
                    pass_rgba = np.zeros((height, width, 4), dtype=np.float32)
                    if rank0 < depth:
                        pass_rgba[:, :, 0] = crypto_mat_raw[:, :, rank0 * 2]       # id(2k)
                        pass_rgba[:, :, 1] = crypto_mat_raw[:, :, rank0 * 2 + 1]  # weight(2k)
                    if rank1 < depth:
                        pass_rgba[:, :, 2] = crypto_mat_raw[:, :, rank1 * 2]       # id(2k+1)
                        pass_rgba[:, :, 3] = crypto_mat_raw[:, :, rank1 * 2 + 1]  # weight(2k+1)

                    pass_rgba = np.ascontiguousarray(pass_rgba[::-1])  # flip Y
                    pass_flat = pass_rgba.reshape(-1)
                    try:
                        target_pass.rect.foreach_set(pass_flat)
                    except AttributeError:
                        target_pass.rect = pass_rgba.reshape(-1, 4).tolist()
        self.end_result(result)

class AstrorayPanelBase:
    """Mixin for every Astroray panel: restricts visibility to scenes where
    our engine is active, and keeps COMPAT_ENGINES consistent for Blender's
    panel-filter machinery."""
    COMPAT_ENGINES = {'CUSTOM_RAYTRACER'}

    @classmethod
    def poll(cls, context):
        return context.scene.render.engine == 'CUSTOM_RAYTRACER'


# ============================================================================ #
# P3-a fix (BUG-15): Standalone material-conversion wrapper
# ============================================================================ #

def _convert_node_material_standalone(mat, renderer):
    """Convert a Blender node material without constructing a RenderEngine.

    P3-a fix (BUG-15): The preview operator needs convert_node_material logic
    but Blender forbids direct RenderEngine() construction. This wrapper creates
    a minimal context object with just `_volume_material_map` and delegates to
    CustomRaytracerRenderEngine's unbound methods, avoiding the forbidden construction.
    """
    class _MinimalConverter:
        """Holds the minimal state convert_node_material needs (_volume_material_map)."""
        def __init__(self):
            self._volume_material_map = {}

    converter = _MinimalConverter()
    # Bind CustomRaytracerRenderEngine's convert_node_material to the minimal converter
    return CustomRaytracerRenderEngine.convert_node_material(converter, mat, renderer)


def _convert_volume_node_standalone(node, node_tree):
    """Convert a Blender volume node without constructing a RenderEngine.

    P3-a fix (BUG-15): Companion to _convert_node_material_standalone for volume conversion.
    """
    class _MinimalConverter:
        pass
    converter = _MinimalConverter()
    return CustomRaytracerRenderEngine.convert_volume_node(converter, node, node_tree)


class RENDER_PT_custom_raytracer_sampling(AstrorayPanelBase, Panel):
    bl_label = "Sampling"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "render"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        settings = context.scene.custom_raytracer

        # pkg176 Stage 4: samples/preview_samples are `direct` rows read natively
        # (native_settings.DIRECT_ALIASES). Cycles bundles them with dropped
        # adaptive/time_limit controls, so the native Sampling panel is NOT
        # adopted (see ADOPTED_NATIVE_PANELS); instead we draw the honest native
        # scene.cycles.samples / preview_samples directly on this custom panel.
        cycles = getattr(context.scene, "cycles", None)
        col = layout.column(align=True)
        if cycles is not None:
            col.prop(cycles, "samples", text="Render")
            col.prop(cycles, "preview_samples", text="Viewport")
        else:
            col.label(text="Enable the Cycles add-on for sample counts", icon='INFO')

        layout.separator()
        col = layout.column(align=True)
        col.prop(settings, "viewport_display_pass", text="Render Pass")
        col.prop(settings, "viewport_oidn", text="Viewport Denoise")
        sub = col.column()
        sub.active = bool(getattr(settings, "viewport_oidn", False))
        sub.prop(settings, "denoiser_backend", text="Denoiser")

        layout.separator()
        layout.prop(settings, "use_adaptive_sampling")
        sub = layout.column()
        sub.active = settings.use_adaptive_sampling
        sub.prop(settings, "adaptive_threshold")

        layout.separator()
        layout.prop(settings, "light_sampler")


# pkg176 Stage 2: the custom "Light Paths" panel (RENDER_PT_custom_raytracer_light_paths)
# was retired here. Every control it drew - max_bounces + diffuse/glossy/transmission/
# volume/transparent bounces, clamp direct/indirect, filter glossy, reflective/refractive
# caustics - is a Stage-0 `direct` row that Stage 1 now reads natively, so the native
# Cycles Light Paths sub-panels (see ADOPTED_NATIVE_PANELS) fully replace it.


class RENDER_PT_custom_raytracer_performance(AstrorayPanelBase, Panel):
    bl_label = "Performance"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "render"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        settings = context.scene.custom_raytracer

        col = layout.column(align=True)
        col.prop(settings, "device_mode", expand=True)

        # pkg178 Stage 5 (experimental): native Principled BSDF routing toggle.
        layout.separator()
        layout.prop(settings, "use_native_principled")

        if RAYTRACER_AVAILABLE:
            try:
                r = astroray.Renderer()
                if r.gpu_available:
                    layout.label(text=f"GPU: {r.gpu_device_name}", icon='CHECKMARK')
                else:
                    layout.label(text="No CUDA GPU detected", icon='INFO')
                    if settings.device_mode == 'gpu':
                        layout.label(text="GPU requested but unavailable — will use CPU", icon='ERROR')
            except Exception:
                pass


class RENDER_PT_custom_raytracer_wavelength(AstrorayPanelBase, Panel):
    """pkg39: Wavelength / multi-spectral rendering settings."""
    bl_label = "Wavelength"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "render"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        settings = context.scene.custom_raytracer

        layout.prop(settings, "wavelength_preset", text="Preset")

        preset = settings.wavelength_preset
        if preset == 'custom':
            col = layout.column(align=True)
            col.prop(settings, "wavelength_min", text="Min (nm)")
            col.prop(settings, "wavelength_max", text="Max (nm)")

        is_outside_visible = preset in ('near_ir', 'uv') or (
            preset == 'custom' and
            (settings.wavelength_max > 780.0 or settings.wavelength_min < 380.0)
        )
        if is_outside_visible:
            layout.separator()
            layout.prop(settings, "colourmap", text="Colourmap")
            layout.label(
                text="Using multiwavelength_path_tracer integrator",
                icon='INFO',
            )


class RENDER_PT_custom_raytracer_diagnostics(AstrorayPanelBase, Panel):
    """Module, GPU, feature, and integrator diagnostics."""
    bl_label = "Diagnostics"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "render"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = False

        settings = context.scene.custom_raytracer

        if not RAYTRACER_AVAILABLE:
            layout.label(text="astroray module not loaded", icon='ERROR')
            return

        col = layout.column(align=False)

        # Module identity
        try:
            mod_path = getattr(astroray, "__file__", "unknown")
            col.label(text=f"Module: {mod_path}", icon='FILE_SCRIPT')
            col.label(text=f"Version: {astroray.__version__}")
        except Exception:
            col.label(text="Module info unavailable", icon='ERROR')

        col.separator()

        # GPU state
        try:
            r = astroray.Renderer()
            if r.gpu_available:
                col.label(text=f"GPU: {r.gpu_device_name}", icon='CHECKMARK')
            else:
                col.label(text="GPU: not available (CPU build or no CUDA device)", icon='INFO')
        except Exception:
            col.label(text="GPU: query failed", icon='ERROR')

        col.separator()

        # Feature flags
        # pkg186: cross-reference the backend-aware __gpu_features__ dict so a
        # capability that is built (on in __features__) but dropped on the GPU
        # backend (off in __gpu_features__ — textures/adaptive_sampling/
        # gr_black_holes; pkg199 moved world volumes OFF this list) is labelled
        # "CPU only" instead of being listed under "On", where it read as a
        # silent claim of GPU support.
        try:
            feats = astroray.__features__
            gpu_feats = getattr(astroray, "__gpu_features__", {})
            cpu_only = [k for k, v in feats.items()
                        if v and k in gpu_feats and not gpu_feats[k]]
            active = [k for k, v in feats.items() if v and k not in cpu_only]
            inactive = [k for k, v in feats.items() if not v]
            col.label(text="Features:")
            col.label(text="  On:  " + (", ".join(active) if active else "none"))
            if cpu_only:
                col.label(text="  CPU only: " + ", ".join(cpu_only), icon='INFO')
            if inactive:
                col.label(text="  Off: " + ", ".join(inactive))
        except Exception:
            col.label(text="Features: unavailable")

        col.separator()

        # Active integrator
        try:
            integrators = astroray.integrator_registry_names()
            col.label(text="Integrators:")
            for name in integrators:
                caps = _integrator_capabilities(name)
                if caps.get("gpuSupported", False):
                    col.label(text=f"  {name}: GPU", icon='CHECKMARK')
                else:
                    reason = caps.get("gpuFallbackReason", "CPU only")
                    col.label(text=f"  {name}: CPU ({reason})", icon='INFO')
            col.label(text=f"Selected: {_effective_integrator_name(settings)}")
        except Exception:
            pass

        # Post-render integrator stats
        stats_str = getattr(settings, "last_render_stats", "")
        if stats_str:
            col.separator()
            col.label(text="Last render stats:")
            for line in stats_str.splitlines()[:6]:
                col.label(text=f"  {line}")

        # pkg56-A: viewport sync per-stage timings (rolling mean over the
        # last ≤100 frames). Hidden until at least one frame has been
        # recorded; pure measurement, no behaviour change.
        try:
            perf_fn = getattr(astroray, "viewport_perf_stats", None)
            if perf_fn is not None:
                stats = perf_fn()
                if stats and int(stats.get("frames", 0)) > 0:
                    col.separator()
                    col.label(
                        text=f"Viewport sync (mean over {stats['frames']} frames):"
                    )
                    for stage in ("geometry", "materials", "lights",
                                  "environment", "render"):
                        col.label(
                            text=f"  {stage}: {float(stats.get(stage, 0.0)):.2f} ms"
                        )
                    col.label(text=f"  total: {float(stats.get('total', 0.0)):.2f} ms")
        except Exception:
            pass


class AstrorayWorldPanelBase(AstrorayPanelBase):
    """World panels only poll when there IS a world to edit."""
    @classmethod
    def poll(cls, context):
        return (context.scene.render.engine == 'CUSTOM_RAYTRACER'
                and context.world is not None)


class WORLD_PT_custom_raytracer_surface(AstrorayWorldPanelBase, Panel):
    bl_label = "Surface"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "world"

    def draw(self, context):
        layout = self.layout
        world = context.world
        layout.prop(world, "use_nodes", icon='NODETREE')
        layout.separator()
        if world.use_nodes and world.node_tree:
            # Let Cycles' world node drawing handle the detail — we just
            # expose the output node's Surface socket for quick edits.
            output = next((n for n in world.node_tree.nodes
                           if n.type == 'OUTPUT_WORLD'), None)
            if output is not None:
                layout.template_node_view(world.node_tree, output,
                                          output.inputs.get('Surface'))
        else:
            layout.prop(world, "color", text="Color")


class MATERIAL_PT_custom_raytracer_surface(AstrorayPanelBase, Panel):
    bl_label = "Surface"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "material"

    @classmethod
    def poll(cls, context):
        return (context.scene.render.engine == 'CUSTOM_RAYTRACER'
                and context.material is not None)

    def draw(self, context):
        layout = self.layout
        mat = context.material
        layout.prop(mat, "use_nodes", icon='NODETREE')
        layout.separator()
        if mat.use_nodes and mat.node_tree:
            output = next((n for n in mat.node_tree.nodes
                           if n.type == 'OUTPUT_MATERIAL' and getattr(n, 'is_active_output', True)),
                          None)
            if output is None:
                output = next((n for n in mat.node_tree.nodes
                               if n.type == 'OUTPUT_MATERIAL'), None)
            if output is not None:
                layout.template_node_view(mat.node_tree, output,
                                          output.inputs.get('Surface'))
        else:
            layout.prop(mat, "diffuse_color", text="Color")


class MATERIAL_PT_AstroraySpectralPreview(AstrorayPanelBase, Panel):
    """pkg58: Spectral profile dropdown + reflectance curve preview."""
    bl_label = "Spectral Profile"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "material"
    bl_parent_id = "MATERIAL_PT_custom_raytracer_surface"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        if context.scene.render.engine != 'CUSTOM_RAYTRACER':
            return False
        if context.material is None:
            return False
        settings = getattr(context.scene, "custom_raytracer", None)
        if settings is None:
            return False
        return getattr(settings, "wavelength_preset", "visible") != "visible"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        mat = context.material
        mat_settings = getattr(mat, "custom_raytracer", None)
        if mat_settings is None:
            layout.label(text="Material settings unavailable", icon='ERROR')
            return

        layout.prop(mat_settings, "spectral_profile", text="Profile")

        profile = getattr(mat_settings, "spectral_profile", "__none__")
        if profile in ("", "__none__"):
            layout.label(text="No profile selected → renders black outside visible", icon='INFO')
            return

        settings = context.scene.custom_raytracer
        lmin, lmax = _active_wavelength_band(settings)
        layout.label(text=f"Band: {lmin:.0f}–{lmax:.0f} nm", icon='CURVE_DATA')

        samples = _spectral_profile_curve_samples(profile, lmin, lmax, n=32)
        img = _update_spectral_preview_image(samples)
        if img is not None:
            try:
                layout.template_preview(img, show_buttons=False)
                return
            except Exception:
                pass

        if samples:
            vals = [s[1] for s in samples]
            layout.label(text=f"Reflectance: min {min(vals):.2f}, max {max(vals):.2f}")


class MATERIAL_OT_astroray_live_preview(Operator):
    bl_idname = "material.astroray_live_preview"
    bl_label = "Render Preview"
    bl_description = "Render the active material on an isolated Astroray preview sphere"

    def execute(self, context):
        if not RAYTRACER_AVAILABLE:
            self.report({'ERROR'}, "astroray module not loaded")
            return {'CANCELLED'}

        obj = getattr(context, "active_object", None)
        mat = getattr(obj, "active_material", None) if obj is not None else None
        mat = mat or getattr(context, "material", None)
        if mat is None:
            self.report({'ERROR'}, "No active material")
            return {'CANCELLED'}

        mat_settings = getattr(mat, "custom_raytracer", None)
        resolution = int(getattr(mat_settings, "live_preview_resolution", "64") or "64")
        samples = int(getattr(mat_settings, "live_preview_samples", 8) or 8)

        start = time.perf_counter()
        renderer = astroray.Renderer()
        mat_id = _create_live_preview_material(renderer, mat)
        render_material_preview, _ = _preview_helpers()
        pixels = render_material_preview(
            renderer,
            mat_id,
            resolution,
            samples,
            max_depth=4,
            hdri_path=_find_preview_hdri(),
        )

        out = Path("test_results") / f"material_preview_{_safe_preview_name(mat.name)}.png"
        _save_preview_image(pixels, out, resolution)
        mat["astroray_preview_path"] = str(out)
        _load_preview_image(str(out))

        elapsed = time.perf_counter() - start
        self.report({'INFO'}, f"Rendered Astroray preview in {elapsed:.2f}s")
        return {'FINISHED'}


class MATERIAL_PT_AstrorayLivePreview(AstrorayPanelBase, Panel):
    bl_label = "Live Material Preview"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "material"
    bl_parent_id = "MATERIAL_PT_custom_raytracer_surface"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return (context.scene.render.engine == 'CUSTOM_RAYTRACER'
                and context.material is not None)

    def draw(self, context):
        layout = self.layout
        mat = context.material
        mat_settings = getattr(mat, "custom_raytracer", None)
        if mat_settings is None:
            layout.label(text="Material settings unavailable", icon='ERROR')
            return

        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(mat_settings, "live_preview_resolution")
        layout.prop(mat_settings, "live_preview_samples")
        layout.operator("material.astroray_live_preview", icon='RENDER_STILL')

        img = _load_preview_image(mat.get("astroray_preview_path", ""))
        if img is not None:
            try:
                layout.template_preview(img, show_buttons=False)
            except Exception:
                pass


class CustomRaytracerPreferences(AddonPreferences):
    bl_idname = __name__
    debug_mode: BoolProperty(name="Debug Mode", default=False)

    def draw(self, context):
        layout = self.layout
        if RAYTRACER_AVAILABLE:
            layout.label(text=f"Raytracer Version: {astroray.__version__}", icon='INFO')
            box = layout.box()
            box.label(text="Features:", icon='CHECKBOX_HLT')
            # pkg186: annotate GPU-dropped-but-built capabilities as "(CPU only)".
            gpu_feats = getattr(astroray, "__gpu_features__", {})
            for feat, enabled in astroray.__features__.items():
                cpu_only = enabled and feat in gpu_feats and not gpu_feats[feat]
                label = f"  {feat.replace('_', ' ').title()}"
                if cpu_only:
                    label += " (CPU only)"
                box.label(text=label, icon='CHECKBOX_HLT' if enabled else 'CHECKBOX_DEHLT')
        else:
            layout.label(text="Raytracer module not loaded!", icon='ERROR')
        layout.prop(self, "debug_mode")

class AstrorayObjectProperties(PropertyGroup):
    # pkg64 Phase 3 — Cycles-style "Shadow Caustics" caster opt-in
    # (intern/cycles/scene/object.h::is_caustics_caster pattern; behaviour
    # only, no GPL source consulted). When True and the renderer's
    # Refractive Caustics toggle is on, the default `path_tracer`
    # attempts an SMS connection through this object at every non-delta
    # vertex, producing prism-accurate caustics. No effect if the object
    # is not a refractive sphere caster (Phase 3 scope).
    is_caustic_caster: BoolProperty(
        name="Caustic Caster",
        default=False,
        description=("Let Astroray's path tracer find caustic paths through "
                     "this object via Specular Manifold Sampling. Only "
                     "refractive sphere casters are sampled in Phase 3."))


class AstrorayBlackHoleProperties(PropertyGroup):
    mass: FloatProperty(name="Mass (M\u2609)", min=0.1, max=1e10, default=10.0,
                        description="Black hole mass in solar masses")
    influence_radius: FloatProperty(name="Influence Radius", min=1.0, max=10000.0, default=100.0,
                                    description="World-space radius of the GR influence sphere")

    # pkg107: world-to-GR scale factor. Smaller values shrink the world-to-GR
    # mapping, growing the visible photon-orbit shadow at the same camera
    # distance. Default 100.0 preserves pkg40-pkg44 baselines; pkg104 reference
    # bank GR scenes use 20.0 for dramatic shadow visualisation.
    r_obs_M: FloatProperty(name="r_obs_M", min=1.0, max=1000.0, default=100.0,
                           description="World-to-GR scale: smaller \u2192 bigger visible shadow at the same camera distance")

    # General Kerr spin (separates from slim_disk_spin which is specific to slim disk).
    # Default 0 = Schwarzschild; \u00b10.998 = near-maximal Kerr.
    spin: FloatProperty(name="Spin (a/M)", min=-0.998, max=0.998, default=0.0,
                        description="Dimensionless Kerr spin parameter (a/M). 0 = Schwarzschild.")

    # pkg43/pkg44: accretion model selector
    accretion_model: EnumProperty(
        name="Accretion Model",
        description="Choose the accretion disk model",
        items=[
            ('NOVIKOV_THORNE', "Novikov-Thorne", "Standard thin disk (Page & Thorne 1974)"),
            ('SLIM_DISK', "Slim Disk", "Super-Eddington disk with advection (Abramowicz 1988 / Sadowski 2009)"),
            ('ADAF', "ADAF", "Advection-dominated accretion flow (Narayan & Yi 1995 / pkg44)"),
        ],
        default='NOVIKOV_THORNE'
    )

    disk_outer: FloatProperty(name="Disk Outer Radius (M)", min=6.0, max=1000.0, default=30.0,
                               description="Accretion disk outer radius in units of M")
    accretion_rate: FloatProperty(name="Accretion Rate", min=0.01, max=100.0, default=1.0,
                                   description="Dimensionless accretion rate (sets disk brightness)")
    inclination: FloatProperty(name="Inclination (\u00b0)", min=0.0, max=90.0, default=75.0,
                                description="Observer inclination from the spin axis")
    show_disk: BoolProperty(name="Show Accretion Disk", default=True)

    # pkg44 ADAF parameters (active when accretion_model == 'ADAF').
    # Defaults are Sgr A*-like (radiatively-inefficient, near-spherical glow).
    adaf_mdot_edd: FloatProperty(name="ADAF mdot/mdot_Edd", min=1e-12, max=1.0, default=1.0e-8,
                                  description="Dimensionless mass accretion rate in units of Eddington")
    adaf_electron_temp: FloatProperty(name="ADAF T_e (K)", min=1e8, max=1e12, default=1.0e10,
                                       description="Electron temperature at outer boundary (K)")
    adaf_beta_mag: FloatProperty(name="ADAF \u03b2 (p_mag/p_gas)", min=0.0, max=1.0, default=0.1,
                                  description="Magnetic-to-gas pressure ratio")
    adaf_r_inner: FloatProperty(name="ADAF r_inner (M)", min=1.0, max=100.0, default=1.5,
                                 description="Inner radius of ADAF flow (M)")
    adaf_r_outer: FloatProperty(name="ADAF r_outer (M)", min=10.0, max=10000.0, default=100.0,
                                 description="Outer radius of ADAF flow (M)")
    adaf_flattening: FloatProperty(name="ADAF flattening", min=0.0, max=1.0, default=0.0,
                                    description="Vertical flattening (0 = spherical, 1 = disk)")
    adaf_alpha: FloatProperty(name="ADAF \u03b1 viscosity", min=0.01, max=1.0, default=0.1,
                               description="Shakura-Sunyaev viscosity")
    adaf_s: FloatProperty(name="ADAF s (outflow)", min=0.0, max=1.0, default=0.3,
                          description="Outflow exponent")
    adaf_intensity_scale: FloatProperty(name="ADAF Intensity Scale", min=1e20, max=1e35, default=1.0e30,
                                         description="Emission intensity multiplier (Sgr A* ~1e30)")

    # Slim disk specific parameters (pkg43)
    slim_disk_spin: FloatProperty(name="Spin (a)", min=-0.998, max=0.998, default=0.0,
                                   description="Dimensionless black hole spin parameter")
    slim_disk_r_inner: FloatProperty(name="Inner Radius (M)", min=0.0, max=100.0, default=0.0,
                                      description="Inner disk edge in M (0 = ISCO)")
    slim_disk_intensity_scale: FloatProperty(name="Intensity Scale", min=0.0, max=1000.0, default=1.0,
                                              description="Emission intensity multiplier")
    slim_disk_base_density: FloatProperty(name="Base Density", min=0.0, max=1.0e12, default=1.0e3,
                                          description="Electron density at midplane in cm^-3")
    enable_jet: BoolProperty(name="Synchrotron Jets", default=False,
                             description="Enable pkg42 bipolar synchrotron jet emission")
    jet_lorentz_factor: FloatProperty(name="Jet Lorentz Factor", min=1.0, max=50.0, default=5.0,
                                      description="Bulk Lorentz factor of the jet plasma")
    jet_half_angle: FloatProperty(name="Jet Half Angle (\u00b0)", min=0.1, max=60.0, default=5.0,
                                  description="Opening half-angle of each conical jet")
    jet_power_law_index: FloatProperty(name="Jet Electron Index", min=1.5, max=6.5, default=2.5,
                                       description="Power-law electron index p")
    jet_base_density: FloatProperty(name="Jet Base Density", min=0.0, max=1.0e12, default=1.0,
                                    description="Electron density at the jet base in cm^-3")
    jet_magnetic_field: FloatProperty(name="Jet Magnetic Field", min=0.0, max=1.0e8, default=30.0,
                                      description="Magnetic field at the jet base in Gauss")


class ASTRORAY_OT_add_black_hole(Operator):
    bl_idname = "astroray.add_black_hole"
    bl_label = "Add Black Hole"
    bl_description = "Add a black hole empty to the scene"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        bpy.ops.object.empty_add(type='SPHERE')
        obj = context.active_object
        obj.name = "BlackHole"
        obj.empty_display_size = 5.0
        return {'FINISHED'}


class OBJECT_PT_astroray_black_hole(Panel):
    bl_label = "Astroray Black Hole"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj is not None and obj.type == 'EMPTY'
                and hasattr(obj, 'astroray_black_hole'))

    def draw(self, context):
        layout = self.layout
        bh = context.active_object.astroray_black_hole
        layout.use_property_split = True
        col = layout.column(align=True)
        col.prop(bh, "mass")
        col.prop(bh, "influence_radius")
        col.prop(bh, "r_obs_M")          # pkg107: controls visible shadow size
        col.prop(bh, "spin")             # general Kerr spin
        col.separator()

        # Accretion model selector (pkg43/pkg44)
        col.prop(bh, "accretion_model")

        col.separator()
        col.prop(bh, "disk_outer")
        col.prop(bh, "accretion_rate")
        col.prop(bh, "inclination")
        col.prop(bh, "show_disk")

        # Show slim disk parameters only when SLIM_DISK is selected
        if bh.accretion_model == 'SLIM_DISK':
            col.separator()
            slim_col = col.column(align=True)
            slim_col.label(text="Slim Disk Parameters:")
            slim_col.prop(bh, "slim_disk_spin")
            slim_col.prop(bh, "slim_disk_r_inner")
            slim_col.prop(bh, "slim_disk_intensity_scale")
            slim_col.prop(bh, "slim_disk_base_density")

        # pkg44 ADAF parameters
        if bh.accretion_model == 'ADAF':
            col.separator()
            adaf_col = col.column(align=True)
            adaf_col.label(text="ADAF Parameters (Narayan & Yi 1995 / pkg44):")
            adaf_col.prop(bh, "adaf_mdot_edd")
            adaf_col.prop(bh, "adaf_electron_temp")
            adaf_col.prop(bh, "adaf_beta_mag")
            adaf_col.prop(bh, "adaf_r_inner")
            adaf_col.prop(bh, "adaf_r_outer")
            adaf_col.prop(bh, "adaf_flattening")
            adaf_col.prop(bh, "adaf_alpha")
            adaf_col.prop(bh, "adaf_s")
            adaf_col.prop(bh, "adaf_intensity_scale")

        col.separator()
        col.prop(bh, "enable_jet")
        jet_col = col.column(align=True)
        jet_col.enabled = bh.enable_jet
        jet_col.prop(bh, "jet_lorentz_factor")
        jet_col.prop(bh, "jet_half_angle")
        jet_col.prop(bh, "jet_power_law_index")
        jet_col.prop(bh, "jet_base_density")
        jet_col.prop(bh, "jet_magnetic_field")


class OBJECT_PT_astroray_object(Panel):
    bl_label = "Astroray"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (context.scene.render.engine == 'CUSTOM_RAYTRACER'
                and obj is not None
                and obj.type in {'MESH', 'EMPTY'}
                and hasattr(obj, 'astroray_object'))

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        ao = context.active_object.astroray_object
        layout.prop(ao, "is_caustic_caster")


class DATA_PT_custom_raytracer_light(AstrorayPanelBase, Panel):
    """pkg195 Stage B: spectral emission authoring for the active light."""
    bl_label = "Astroray Spectrum"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "data"

    @classmethod
    def poll(cls, context):
        return (context.scene.render.engine == 'CUSTOM_RAYTRACER'
                and context.light is not None
                and hasattr(context.light, 'custom_raytracer'))

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        light = context.light
        settings = light.custom_raytracer
        # pkg213: expose the engine-wired intensity. Blender labels this "Power"
        # and applies the type-appropriate unit (W / W/m^2); the value it edits is
        # the same light.energy that convert_lights reads at :4632 and passes to
        # every add_*_light* call. Visible in ALL spectrum modes (native/preset/
        # custom_profile) because the engine multiplies it in unconditionally.
        layout.prop(light, "energy")
        layout.prop(settings, "spectrum_mode")

        mode = settings.spectrum_mode
        profile_name = ""
        if mode == 'preset':
            layout.prop(settings, "preset_profile")
            profile_name = getattr(settings, "preset_profile", "") or ""
        elif mode == 'custom_profile':
            layout.prop(settings, "custom_profile")
            name = getattr(settings, "custom_profile", "") or ""
            profile_name = "" if name == "__none__" else name

        if mode != 'native':
            label = _profile_range_label(profile_name)
            if label:
                layout.label(text=label, icon='IPO_LINEAR')
            layout.label(text="Light colour acts as a gel tint", icon='INFO')
            # pkg195 Stage B: GPU dedicated lights approximate non-RGB emission
            # via deviceReference() RGB (emission_spectrum.h:100-108). The
            # measured SPD is exact only on the CPU integrators; note it so the
            # artist isn't surprised by a GPU/CPU chroma difference.
            layout.label(text="GPU: RGB-approximated (CPU is exact)", icon='ERROR')


classes = [
    CustomRaytracerRenderSettings, CustomRaytracerMaterialSettings,
    CustomRaytracerLightSettings,
    AstrorayObjectProperties,
    AstrorayBlackHoleProperties,
    CustomRaytracerRenderEngine,
    RENDER_PT_custom_raytracer_sampling,
    RENDER_PT_custom_raytracer_performance,
    RENDER_PT_custom_raytracer_wavelength,
    RENDER_PT_custom_raytracer_diagnostics,
    WORLD_PT_custom_raytracer_surface,
    MATERIAL_PT_custom_raytracer_surface,
    MATERIAL_PT_AstroraySpectralPreview,
    MATERIAL_OT_astroray_live_preview,
    MATERIAL_PT_AstrorayLivePreview,
    CustomRaytracerPreferences,
    ASTRORAY_OT_add_black_hole, OBJECT_PT_astroray_black_hole,
    OBJECT_PT_astroray_object,
    DATA_PT_custom_raytracer_light,
]

# ---------------------------------------------------------------------- #
# Built-in panel compatibility
# ---------------------------------------------------------------------- #
#
# Blender's built-in Properties panels (Output, Dimensions, Color Management,
# Post Processing, Output, Metadata, World, Object, Mesh, Modifiers, etc.)
# only show up for a given render engine if that engine is listed in the
# panel class's COMPAT_ENGINES set. Cycles does this wholesale at add-on
# register time — every panel that advertises BLENDER_EEVEE / CYCLES compat
# gets CUSTOM_RAYTRACER appended too. Panels we explicitly DON'T want (engine-
# specific ones like Eevee Indirect Lighting, Cycles Ray Visibility, etc.)
# are excluded so they don't pollute our Properties editor.

def _is_compatible_panel(panel):
    if not hasattr(panel, 'COMPAT_ENGINES'):
        return False
    if 'BLENDER_RENDER' not in panel.COMPAT_ENGINES:
        return False
    # Skip panels we register ourselves
    if panel.__name__.startswith('RENDER_PT_custom_raytracer'):
        return False
    if panel.__name__.startswith('WORLD_PT_custom_raytracer'):
        return False
    if panel.__name__.startswith('MATERIAL_PT_custom_raytracer'):
        return False
    return True


_EXCLUDE_PANELS = {
    # Eevee-specific light-path / indirect-lighting panels
    'RENDER_PT_eevee_ambient_occlusion',
    'RENDER_PT_eevee_motion_blur',
    'RENDER_PT_eevee_next_motion_blur',
    'RENDER_PT_eevee_motion_blur_curve',
    'RENDER_PT_eevee_depth_of_field',
    'RENDER_PT_eevee_next_depth_of_field',
    'RENDER_PT_eevee_subsurface_scattering',
    'RENDER_PT_eevee_screen_space_reflections',
    'RENDER_PT_eevee_shadows',
    'RENDER_PT_eevee_next_shadows',
    'RENDER_PT_eevee_sampling',
    'RENDER_PT_eevee_next_sampling',
    'RENDER_PT_eevee_indirect_lighting',
    'RENDER_PT_eevee_next_indirect_lighting',
    'RENDER_PT_eevee_indirect_lighting_display',
    'RENDER_PT_eevee_film',
    'RENDER_PT_eevee_next_film',
    'RENDER_PT_eevee_hair',
    'RENDER_PT_eevee_performance',
    'RENDER_PT_eevee_next_performance',
    'RENDER_PT_eevee_next_volumetric',
    'RENDER_PT_eevee_next_volumetric_lighting',
    'RENDER_PT_eevee_next_volumetric_shadows',
    'RENDER_PT_eevee_next_horizon_scan',
    'RENDER_PT_eevee_next_raytracing',
    'RENDER_PT_eevee_next_screen_trace',
    'RENDER_PT_eevee_next_denoise',
    # Cycles-specific sampling panels (we have our own)
    'RENDER_PT_sampling_light_tree',
}


def _iter_compat_panels():
    for panel in bpy.types.Panel.__subclasses__():
        if panel.__name__ in _EXCLUDE_PANELS:
            continue
        if _is_compatible_panel(panel):
            yield panel


# ---------------------------------------------------------------------- #
# pkg176 Stage 2 — explicit native Cycles panel adoption
# ---------------------------------------------------------------------- #
#
# Native Cycles panels advertise COMPAT_ENGINES = {'CYCLES'} (never
# 'BLENDER_RENDER'), so the wholesale _iter_compat_panels() loop above does
# NOT pick them up. Stage 2 adopts an EXPLICIT, checked-in subset for
# CUSTOM_RAYTRACER — a panel is adopted only if EVERY control it draws maps to
# a Stage-0 `direct` row (blender_addon/settings_map.py) that Stage 1 already
# reads natively (native_settings.DIRECT_ALIASES), so nothing on an adopted
# panel is silently ignored. The list is explicit (not a blanket rule) so a
# Blender 5.x panel rename/removal fails LOUDLY at register() instead of
# silently dropping a control (Blender 5.0 already removed panels other engines
# had re-registered — see the pkg176 research note).
ADOPTED_NATIVE_PANELS = (
    # Light Paths family. Every control below is a `direct` row:
    #   parent    — draw() is a no-op; its integrator-preset header only writes
    #               the direct bounce/caustics props. Adopted so the sub-panels
    #               (which poll on their own COMPAT_ENGINES) are shown.
    "CYCLES_RENDER_PT_light_paths",
    #   max_bounces — max_bounces (Total) + diffuse/glossy/transmission/volume
    #                 bounces + transparent_max_bounces  (all `direct`).
    "CYCLES_RENDER_PT_light_paths_max_bounces",
    #   clamping    — sample_clamp_direct / sample_clamp_indirect  (both `direct`).
    "CYCLES_RENDER_PT_light_paths_clamping",
    #   caustics    — blur_glossy (Filter Glossy) + caustics_reflective /
    #                 caustics_refractive  (all `direct`).
    "CYCLES_RENDER_PT_light_paths_caustics",
    #
    # Deliberately NOT adopted this stage (a control has no honest native map):
    #   CYCLES_RENDER_PT_light_paths_fast_gi   — use_fast_gi / ao_bounces (`dropped`).
    #   CYCLES_RENDER_PT_sampling(_render/_viewport/_advanced/_lights) — Cycles
    #       bundles `samples` with use_adaptive_sampling / adaptive_threshold /
    #       time_limit (`dropped`) and use_light_tree (`approximated`); no sampling
    #       panel is fully honest, so `samples`/`preview_samples` stay on the custom
    #       Sampling panel until pkg119-C degrades the un-honoured controls.
)


def _adopt_native_panels():
    """Re-register the ADOPTED_NATIVE_PANELS for CUSTOM_RAYTRACER (the standard
    external-engine COMPAT_ENGINES trick), failing loudly if any is missing.

    Route-2 correctness note: all Cycles panels inherit ONE shared
    COMPAT_ENGINES set from CyclesButtonsPanel. Mutating it in place would leak
    CUSTOM_RAYTRACER onto EVERY Cycles panel — including the un-honoured
    sampling / fast-GI ones. So give each adopted panel its OWN copy of the set
    first, then add our engine.
    """
    missing = [name for name in ADOPTED_NATIVE_PANELS
               if getattr(bpy.types, name, None) is None]
    if missing:
        raise RuntimeError(
            "Astroray: native Blender/Cycles panel(s) expected by pkg176 Stage 2 "
            "are missing from bpy.types: " + ", ".join(missing) + ". Blender may "
            "have renamed or removed them; update ADOPTED_NATIVE_PANELS in "
            "blender_addon/__init__.py to match this Blender version."
        )
    for name in ADOPTED_NATIVE_PANELS:
        panel = getattr(bpy.types, name)
        if 'COMPAT_ENGINES' not in vars(panel):
            panel.COMPAT_ENGINES = set(panel.COMPAT_ENGINES)
        panel.COMPAT_ENGINES.add('CUSTOM_RAYTRACER')


def _release_native_panels():
    for name in ADOPTED_NATIVE_PANELS:
        panel = getattr(bpy.types, name, None)
        engines = getattr(panel, 'COMPAT_ENGINES', None) if panel is not None else None
        if engines is not None:
            engines.discard('CUSTOM_RAYTRACER')


def _check_build_integrity():
    """pkg94: verify the loaded module is the one that was installed.

    Compares astroray.__build__ (compile-time build-ID) vs the build-ID
    recorded in the on-disk install manifest (build_report.json). On mismatch,
    raises a loud error instructing the user to restart Blender.

    Rationale: Blender memory-maps astroray.pyd on addon load and holds the
    lock for the process lifetime. Re-installing while Blender runs leaves the
    new .pyd on disk but the running interpreter keeps the *old* class surface.
    The .~stale~NNNN shadow dirs are the OS refusing to overwrite a locked file.
    Without this guard, a stale loaded module disguises itself as a code bug
    (AttributeError: no attribute 'upload_*').
    """
    import json
    if not RAYTRACER_AVAILABLE:
        return  # module didn't load at all; skip guard

    # Read the on-disk install manifest (written by build_blender_addon.py)
    manifest_path = os.path.join(addon_dir, "build_report.json")
    if not os.path.isfile(manifest_path):
        # No manifest → likely a dev build or old addon version; skip guard
        return

    try:
        manifest = json.loads(Path(manifest_path).read_text())
        manifest_build_id = manifest.get("build_id", "")
    except Exception:
        # Corrupt manifest; skip guard rather than breaking the addon
        return

    # Compare with the loaded module's compile-time build-ID
    loaded_build_id = getattr(astroray, "__build__", "")
    if loaded_build_id != manifest_build_id:
        raise RuntimeError(
            f"\n{'='*70}\n"
            f"RESTART BLENDER — stale module loaded\n"
            f"{'='*70}\n"
            f"The running astroray module is from a different build than the\n"
            f"one just installed. Blender has the old .pyd memory-mapped.\n\n"
            f"  Loaded module build-ID:    {loaded_build_id}\n"
            f"  Installed manifest build-ID: {manifest_build_id}\n\n"
            f"Quit Blender completely, then restart it to pick up the new module.\n"
            f"{'='*70}\n"
        )


def _check_openmp_disabled():
    """pkg147: refuse to render CPU with an OpenMP-enabled .pyd.

    render()'s progress callback is invoked from whichever OpenMP worker
    thread finishes a tile (raytracer.h's `#pragma omp parallel for` render
    loop), and PyRenderer::render() (module/blender_module.cpp) holds the GIL
    for the whole call. A worker thread's gil_scoped_acquire deadlocks
    against the calling thread, which is blocked in the implicit end-of-
    parallel-region barrier while still holding the GIL — this hangs any CPU
    addon render with 2+ tiles (device_mode='cpu' at >16px, tileSize=16).

    Called from configure_backend() at every point CPU mode is actually
    selected (explicit device_mode='cpu', or an auto/gpu fallback to CPU) —
    NOT from register(), so an OpenMP-enabled dev build can still register
    and render on GPU without being blocked; only the CPU path it would
    actually deadlock is refused.

    build_blender_addon.py always passes -DASTRORAY_DISABLE_OPENMP=ON, so a
    properly-packaged addon build never hits this. This guard catches ad-hoc
    dev builds (e.g. a raw `cmake --build` or configure_and_build.bat run)
    that get dropped into the addon directory without going through the
    packaging script.
    """
    if not RAYTRACER_AVAILABLE:
        return
    if bool(astroray.__features__.get("openmp", False)):
        raise RuntimeError(
            f"\n{'='*70}\n"
            f"ASTRORAY REFUSING CPU RENDER — OpenMP-enabled build\n"
            f"{'='*70}\n"
            f"This astroray.pyd was compiled WITH OpenMP linked in. Rendering\n"
            f"with device_mode='cpu' at more than one tile (>16px) will hang\n"
            f"indefinitely: the render() progress callback is invoked from an\n"
            f"OpenMP worker thread and deadlocks against the GIL held by the\n"
            f"calling thread for the duration of the call.\n\n"
            f"Rebuild via scripts/build/build_blender_addon.py, which always\n"
            f"passes -DASTRORAY_DISABLE_OPENMP=ON for addon builds. Do not\n"
            f"install a .pyd built via a raw cmake/configure_and_build.bat\n"
            f"invocation into the Blender addon directory.\n"
            f"{'='*70}\n"
        )


def register():
    # pkg94: guard against stale loaded module (before any Renderer use)
    _check_build_integrity()

    # pkg176 Stage 2: adopt the explicit native Cycles panels first, so a missing
    # (renamed/removed) panel fails loudly before we register any of our own
    # classes rather than leaving a half-registered addon.
    _adopt_native_panels()

    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.custom_raytracer = PointerProperty(type=CustomRaytracerRenderSettings)
    bpy.types.Material.custom_raytracer = PointerProperty(type=CustomRaytracerMaterialSettings)
    # pkg195 Stage B: attach spectral-light settings only when bpy.types.Light
    # exists. CI runs register() under a bpy stub that omits Light (the same class
    # of stub gap the native shader nodes degrade around above); real Blender
    # always has it, so the headless-Blender path is unaffected.
    _light_type = getattr(bpy.types, 'Light', None)
    if _light_type is not None:
        _light_type.custom_raytracer = PointerProperty(type=CustomRaytracerLightSettings)
    else:
        print("Astroray spectral light settings unavailable: "
              "module 'bpy.types' has no attribute 'Light'")
    bpy.types.Object.astroray_black_hole = PointerProperty(type=AstrorayBlackHoleProperties)
    bpy.types.Object.astroray_object = PointerProperty(type=AstrorayObjectProperties)

    # pkg57: native shader nodes + per-material settings.
    if _ASTRORAY_NODES_AVAILABLE:
        try:
            astroray_nodes.register()
        except Exception as exc:  # pragma: no cover - defensive
            print(f"Astroray native shader nodes register() failed: {exc}")

    # Opt every compatible built-in panel into our engine.
    for panel in _iter_compat_panels():
        panel.COMPAT_ENGINES.add('CUSTOM_RAYTRACER')

    print("Astroray renderer addon registered")


def unregister():
    _release_native_panels()
    for panel in _iter_compat_panels():
        panel.COMPAT_ENGINES.discard('CUSTOM_RAYTRACER')

    if _ASTRORAY_NODES_AVAILABLE:
        try:
            astroray_nodes.unregister()
        except Exception as exc:  # pragma: no cover - defensive
            print(f"Astroray native shader nodes unregister() failed: {exc}")

    del bpy.types.Scene.custom_raytracer
    del bpy.types.Material.custom_raytracer
    _light_type = getattr(bpy.types, 'Light', None)
    if _light_type is not None and hasattr(_light_type, 'custom_raytracer'):
        del _light_type.custom_raytracer
    del bpy.types.Object.astroray_black_hole
    del bpy.types.Object.astroray_object
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    print("Astroray renderer addon unregistered")


if __name__ == "__main__":
    register()
