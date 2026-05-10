# NOTE: Blender 5.1+ uses blender_manifest.toml (see sibling file). bl_info is kept
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

addon_dir = os.path.dirname(__file__)
if addon_dir not in sys.path: sys.path.insert(0, addon_dir)

from shader_blending import blend_shader_specs, add_shader_specs

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
    samples: IntProperty(name="Samples", min=1, max=65536, default=2,
        description="Samples per pixel for final F12 renders")
    preview_samples: IntProperty(name="Viewport Samples", min=1, max=1024, default=1,
        description="Samples per pixel for rendered-shading viewport preview")
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
    max_bounces: IntProperty(name="Max Bounces", min=0, max=1024, default=10,
        description="Maximum path-trace depth — caps how many times a ray can scatter")
    diffuse_bounces: IntProperty(name="Diffuse", min=0, max=1024, default=4,
        description="Maximum diffuse bounce depth")
    glossy_bounces: IntProperty(name="Glossy", min=0, max=1024, default=4,
        description="Maximum glossy/specular bounce depth")
    transmission_bounces: IntProperty(name="Transmission", min=0, max=1024, default=12,
        description="Maximum transmission/refraction bounce depth")
    volume_bounces: IntProperty(name="Volume", min=0, max=1024, default=0,
        description="Maximum volume bounce depth")
    transparent_bounces: IntProperty(name="Transparent", min=0, max=1024, default=8,
        description="Maximum transparent bounce depth")
    use_adaptive_sampling: BoolProperty(name="Adaptive Sampling", default=True,
        description="Stop sampling pixels that have already converged")
    adaptive_threshold: FloatProperty(name="Noise Threshold", min=0.001, max=1.0, default=0.01)
    clamp_direct: FloatProperty(name="Clamp Direct", min=0.0, max=100.0, default=0.0,
        description="Clamp direct lighting contribution luminance (0 disables)")
    clamp_indirect: FloatProperty(name="Clamp Indirect", min=0.0, max=100.0, default=0.0,
        description="Clamp indirect lighting contribution luminance (0 disables)")
    filter_glossy: FloatProperty(name="Filter Glossy", min=0.0, max=10.0, default=0.0,
        description="Increase glossy roughness on secondary bounces to reduce noise")
    use_reflective_caustics: BoolProperty(name="Reflective Caustics", default=True,
        description="Enable reflective caustics from specular reflections after diffuse bounces")
    use_refractive_caustics: BoolProperty(name="Refractive Caustics", default=True,
        description="Enable refractive caustics from transmission after diffuse bounces")
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
    use_denoising: BoolProperty(name="Denoise", default=False,
        description="Apply OIDN denoiser as a post-process pass after rendering")
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


def _integrator_capabilities(name):
    try:
        return astroray.integrator_capabilities(name)
    except Exception as exc:
        return {
            "gpuSupported": False,
            "gpuFallbackReason": f"capability query failed: {exc}",
        }


def configure_backend(renderer, settings, reporter=None, integrator_name=None) -> str:
    """Apply device_mode to renderer. Returns 'gpu' or 'cpu'.

    Shared by final render and viewport render so both paths behave identically.
    """
    mode = getattr(settings, "device_mode", "auto")
    if mode == "cpu":
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
    if getattr(mat, "use_nodes", False) and getattr(mat, "node_tree", None):
        engine = CustomRaytracerRenderEngine()
        engine._volume_material_map = {}
        return engine.convert_node_material(mat, renderer)

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
    _viewport_texture = None
    _viewport_width = 0
    _viewport_height = 0
    # pkg52: persistent viewport state. The renderer is reused across draws
    # so we don't pay scene-rebuild cost on every camera nudge. The hash
    # detects camera/region changes from view_draw (Blender does not emit
    # a "camera changed" event in the viewport).
    _viewport_renderer = None
    _viewport_full_synced = False  # pkg56-C: True after first full sync
    _viewport_camera_hash = None
    _viewport_accum_pixels = None
    _viewport_current_spp = 0
    _viewport_target_spp = 0
    _viewport_accum_key = None
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
    _CRYPTOMATTE_PASS_SPECS = [
        ("CryptoObject00", "cryptomatte_object", "use_pass_cryptomatte_object"),
        ("CryptoMaterial00", "cryptomatte_material", "use_pass_cryptomatte_material"),
    ]

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
        for display_name, _, toggle_name in self._CRYPTOMATTE_PASS_SPECS:
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
        enabled = []
        for display_name, key, toggle_name in cls._CRYPTOMATTE_PASS_SPECS:
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
        settings = scene.custom_raytracer

        print(f"Rendering {width}x{height}, {settings.samples} samples")
        renderer = None
        try:
            renderer = astroray.Renderer()
            renderer.set_adaptive_sampling(settings.use_adaptive_sampling)
            self.convert_scene(depsgraph, renderer, width, height)

            integrator_name = _effective_integrator_name(settings)
            try:
                active_device = _configure_backend_for_context(renderer, settings, self.report, integrator_name)
            except RuntimeError:
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
            renderer.set_integrator(integrator_name)
            if settings.use_denoising and not is_outside_visible:
                denoise_pass = _resolve_denoiser_pass(settings)
                if denoise_pass is not None:
                    renderer.add_pass(denoise_pass)
            if is_outside_visible and settings.colourmap != 'grayscale':
                renderer.add_pass("colourmap_output")
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
            if renderer:
                try: renderer.clear()
                except: pass
            del renderer

    # ------------------------------------------------------------------ #
    # Viewport preview (rendered shading mode in 3D View)
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    # pkg52: persistent viewport session
    # ------------------------------------------------------------------ #

    def _get_viewport_renderer(self):
        """Lazy-init the persistent viewport Renderer. Reused across
        view_update and view_draw so we don't reconstruct on every nudge."""
        if getattr(self, '_viewport_renderer', None) is None:
            self._viewport_renderer = astroray.Renderer()
        return self._viewport_renderer

    def _reset_viewport_accumulation(self):
        self._viewport_accum_pixels = None
        self._viewport_current_spp = 0
        self._viewport_target_spp = 0
        self._viewport_accum_key = None

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

    def _update_viewport_status(self):
        try:
            self.update_stats(
                "Astroray",
                f"Viewport {self._viewport_current_spp}/{self._viewport_target_spp} spp"
            )
        except AttributeError:
            pass

    def _accumulate_viewport_pixels(self, pixels, chunk_spp):
        chunk = np.asarray(pixels, dtype=np.float32)
        if self._viewport_accum_pixels is None or self._viewport_current_spp <= 0:
            self._viewport_accum_pixels = chunk.copy()
            self._viewport_current_spp = int(chunk_spp)
        else:
            old_spp = int(self._viewport_current_spp)
            new_spp = old_spp + int(chunk_spp)
            self._viewport_accum_pixels = (
                (self._viewport_accum_pixels * old_spp + chunk * int(chunk_spp))
                / float(new_spp)
            )
            self._viewport_current_spp = new_spp
        self._update_viewport_status()
        return self._viewport_accum_pixels

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

    # ------------------------------------------------------------------ #
    # pkg56 Phase C — depsgraph-driven dispatch
    # ------------------------------------------------------------------ #
    # `_apply_depsgraph_updates` reads `bpy.types.Depsgraph.updates` and
    # routes only the matching Phase B uploaders. Mirrors Cycles
    # `BlenderSync::sync_recalc` (intern/cycles/blender/sync.cpp,
    # Apache-2.0): collect into typed buckets, dispatch in fixed order.
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
            return {'accumulation_only': True}
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
        """Bucket `depsgraph.updates` into domains, dispatch only the
        matching Phase B uploader(s). Returns one of:

          - 'fallback'   : caller must run `_sync_viewport_scene`
                           (unrecognised update id or .updates absent).
          - 'idle'       : zero domain edits — caller skips upload AND
                           render. This is the ≤5 ms idle-frame path.
          - 'dispatched' : one or more uploaders ran — caller renders.

        Dispatch order (env → materials → lights → geometry → transforms)
        matches Cycles `BlenderSync::sync_data()` so the device-state
        result is order-independent of Blender's iteration order over
        depsgraph.updates (research note §3.2, §8 risk 5).
        """
        updates = getattr(depsgraph, 'updates', None)
        if updates is None:
            return 'fallback'

        env = materials = lights = geometry = False
        transforms = []  # list of (obj_id, mat16) for transform-only edits
        accumulation_only = False

        for upd in updates:
            kind = self._classify_depsgraph_update(upd)
            if kind is None:
                # Unrecognised id type (skin modifier, particle system,
                # grease pencil, …). Spec §C non-goals: fall back to
                # full sync rather than guess. Mirrors Cycles'
                # has_updates_=true default.
                return 'fallback'
            if kind.get('environment'): env = True
            if kind.get('lights'):      lights = True
            if kind.get('materials'):   materials = True
            if kind.get('geometry'):    geometry = True
            if kind.get('accumulation_only'):
                accumulation_only = True
            if kind.get('transform_only') and not kind.get('geometry'):
                obj_id = self._renderer_object_id_for(upd.id)
                if obj_id is None:
                    # No Blender-Object → renderer-primitive-id mapping
                    # cached. Promote to a geometry rebuild so the BVH
                    # picks up the new transform — same cost as
                    # update_object_transform on the single-level BVH
                    # we ship today (research note §4.1; the two-level
                    # BVH refit win lands in a follow-up package).
                    geometry = True
                else:
                    try:
                        m = list(upd.id.matrix_world)
                        if m and hasattr(m[0], '__iter__'):
                            m = [float(x) for row in m for x in row]
                        transforms.append((obj_id, m))
                    except Exception:
                        geometry = True

        any_domain = env or materials or lights or geometry or bool(transforms)
        if not any_domain:
            if accumulation_only:
                # Frame/Scene tick — image is unchanged but the user
                # may want a fresh accumulation. Reset and skip render.
                self._reset_viewport_accumulation()
            return 'idle'

        if env:       renderer.upload_environment()
        if materials: renderer.upload_materials()
        if lights:    renderer.upload_lights()
        if geometry:  renderer.upload_geometry()
        elif transforms:
            for obj_id, mat16 in transforms:
                try:
                    renderer.update_object_transform(obj_id, mat16)
                except (RuntimeError, AttributeError, TypeError):
                    # Stale id (object removed) — skip; the next full
                    # sync will pick the new state up.
                    pass
        # Any image-changing dispatch resets accumulation (Phase C key
        # design 4: a single reset per frame, not per update).
        self._reset_viewport_accumulation()
        return 'dispatched'

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
        """Push the depsgraph state into the renderer. Called from view_update
        only — view_draw skips this and just re-renders with a new camera.

        pkg56-A: per-stage timers feed `astroray.record_viewport_stage`
        for the no-change-frame baseline. Pure measurement, zero behaviour
        change — the helper is a no-op when the binding isn't present.
        """
        renderer.set_adaptive_sampling(settings.use_adaptive_sampling)
        renderer.clear()
        renderer.set_clamp_direct(settings.clamp_direct)
        renderer.set_clamp_indirect(settings.clamp_indirect)
        renderer.set_filter_glossy(settings.filter_glossy)
        renderer.set_use_reflective_caustics(settings.use_reflective_caustics)
        renderer.set_use_refractive_caustics(settings.use_refractive_caustics)

        t0 = time.perf_counter()
        material_map = self.convert_materials(depsgraph, renderer)
        _viewport_perf_record("materials", t0)

        t0 = time.perf_counter()
        self.convert_objects(depsgraph, renderer, material_map)
        _viewport_perf_record("geometry", t0)

        t0 = time.perf_counter()
        self.convert_lights(depsgraph, renderer)
        _viewport_perf_record("lights", t0)

        t0 = time.perf_counter()
        self.setup_world(depsgraph.scene, renderer)
        _viewport_perf_record("environment", t0)

        _configure_backend_for_context(renderer, settings, self.report, _effective_integrator_name(settings))
        # pkg56-C: mark that the renderer holds a coherent full snapshot of
        # the scene. Subsequent view_update ticks may dispatch incrementally.
        self._viewport_full_synced = True

    def _render_viewport_frame(self, renderer, context, settings, region,
                               reset_accumulation=False):
        """Set up the camera, run a render, update the cached GPU texture.

        Honors pkg62's `viewport_display_pass` selector and `viewport_oidn`
        toggle: registers the right AOV pass / denoiser before render, and
        for compositor-only passes (Cycles-style direct/indirect channels)
        fetches the per-pass buffer after render via
        `renderer.get_render_pass_buffer(name)`.
        """
        width = max(1, region.width)
        height = max(1, region.height)
        render_key = self._viewport_render_key(context, settings, region)
        if reset_accumulation or render_key != getattr(self, '_viewport_accum_key', None):
            self._reset_viewport_accumulation()
            self._viewport_accum_key = render_key

        self._viewport_target_spp = self._viewport_target_samples(settings)
        if self._viewport_current_spp >= self._viewport_target_spp:
            return False

        self._setup_viewport_camera(renderer, context, width, height)

        # Wavelength + integrator policy must match the final-render path.
        lmin, lmax = _wavelength_range_from_settings(settings)
        renderer.set_wavelength_range(lmin, lmax)
        is_outside_visible = (lmax > 780.0 or lmin < 380.0)
        if is_outside_visible:
            renderer.set_output_mode("luminance")
        renderer.set_integrator(_effective_integrator_name(settings))

        # pkg62: viewport pass selector + viewport OIDN toggle.
        try:
            renderer.clear_passes()
        except AttributeError:
            pass
        viewport_display_pass = getattr(settings, "viewport_display_pass", "combined")
        if viewport_display_pass == "albedo":
            renderer.add_pass("albedo_aov")
        elif viewport_display_pass == "normal":
            renderer.add_pass("normal_aov")
        elif viewport_display_pass == "depth":
            renderer.add_pass("depth_aov")
        if getattr(settings, "viewport_oidn", False) and not is_outside_visible:
            denoise_pass = _resolve_denoiser_pass(settings)
            if denoise_pass is not None:
                renderer.add_pass(denoise_pass)

        samples = self._viewport_chunk_samples(settings, self._viewport_current_spp)
        if samples <= 0:
            return False
        depth = max(2, settings.max_bounces // 2)
        pixels = renderer.render(
            samples, depth, None, False,
            min(settings.diffuse_bounces, depth),
            min(settings.glossy_bounces, depth),
            min(settings.transmission_bounces, depth),
            min(settings.volume_bounces, depth),
            min(settings.transparent_bounces, depth)
        )
        if pixels is None:
            return

        # pkg62: for compositor-style passes (diffuse/glossy direct/indirect,
        # emission, environment, ao, shadow), the renderer keeps Combined as
        # its primary buffer and we have to fetch the named per-pass buffer.
        # Albedo/Normal/Depth use the corresponding AOV plugin which writes
        # into the primary buffer, so they reuse `pixels` directly.
        pixels_to_display = pixels
        if viewport_display_pass not in {"combined", "albedo", "normal", "depth"}:
            try:
                pixels_to_display = renderer.get_render_pass_buffer(viewport_display_pass)
            except Exception:
                pixels_to_display = pixels
        pixels_to_display = self._accumulate_viewport_pixels(pixels_to_display, samples)
        self._update_viewport_texture(pixels_to_display, width, height)
        return True

    def view_update(self, context, depsgraph):
        """Called when the scene or viewport changes. Re-syncs the scene into
        the persistent viewport renderer and renders one frame.

        Camera-only changes (pan/zoom/orbit) are NOT routed through here by
        Blender — they don't fire a depsgraph update. view_draw owns those.
        """
        if not RAYTRACER_AVAILABLE:
            return
        scene = depsgraph.scene
        settings = scene.custom_raytracer
        region = context.region

        try:
            renderer = self._get_viewport_renderer()

            # pkg56-C: depsgraph-driven dispatch. The first view_update
            # (no full snapshot yet) and any unrecognised update fall
            # back to the full sync path — same has_updates_=true safety
            # net Cycles uses (sync.cpp). Subsequent ticks route only
            # the matching Phase B uploaders.
            if not getattr(self, '_viewport_full_synced', False):
                dispatch = 'fallback'
            else:
                dispatch = self._apply_depsgraph_updates(
                    renderer, depsgraph, settings)
            if dispatch == 'fallback':
                self._sync_viewport_scene(renderer, depsgraph, settings)
                dispatch = 'dispatched'
            if dispatch == 'idle':
                # No domain edits this tick — skip both upload and
                # render. This is the ≤5 ms idle-frame gate.
                _viewport_perf_frame_complete()
                self._viewport_camera_hash = self._camera_state_hash(context, region)
                return
            t0 = time.perf_counter()
            self._render_viewport_frame(renderer, context, settings, region,
                                        reset_accumulation=True)
            _viewport_perf_record("render", t0)
            # pkg56-A: close the frame so its stage totals enter the ring
            # buffer that astroray.viewport_perf_stats() reads.
            _viewport_perf_frame_complete()
            # Stamp the camera hash so view_draw doesn't re-render until the
            # camera actually changes.
            self._viewport_camera_hash = self._camera_state_hash(context, region)
            if self._viewport_current_spp < self._viewport_target_spp:
                self._request_viewport_redraw()
        except Exception as e:
            print(f"Astroray viewport preview error: {e}")
            traceback.print_exc()

    def view_draw(self, context, depsgraph):
        """Called every frame inside rendered-shading mode. Detects camera
        changes (pan/zoom/orbit, including CAMERA-view zoom and offset) and
        re-renders without touching scene state. Otherwise just blits the
        cached texture.
        """
        if not RAYTRACER_AVAILABLE:
            return
        try:
            region = context.region
            scene = depsgraph.scene
            settings = scene.custom_raytracer

            # Camera-change detection — fixes the project-owner-reported
            # "panning/zooming the viewport doesn't update the render" bug.
            new_hash = self._camera_state_hash(context, region)
            target_spp = self._viewport_target_samples(settings)
            render_key = self._viewport_render_key(context, settings, region)
            camera_changed = (
                new_hash is not None
                and new_hash != getattr(self, '_viewport_camera_hash', None)
            )
            needs_progress = int(getattr(self, '_viewport_current_spp', 0)) < target_spp
            settings_changed = render_key != getattr(self, '_viewport_accum_key', None)
            if camera_changed or needs_progress or settings_changed or not getattr(self, '_viewport_texture', None):
                renderer = self._get_viewport_renderer()
                # If the user opened rendered-shading mode without ever
                # firing view_update (rare), the renderer has no scene yet.
                # Fall back to a full sync.
                if not getattr(self, '_viewport_texture', None):
                    self._sync_viewport_scene(renderer, depsgraph, settings)
                self._render_viewport_frame(
                    renderer, context, settings, region,
                    reset_accumulation=(camera_changed or settings_changed)
                )
                self._viewport_camera_hash = new_hash
                if self._viewport_current_spp < self._viewport_target_spp:
                    self._request_viewport_redraw()

            if self._viewport_texture is None:
                return

            import gpu
            from gpu_extras.presets import draw_texture_2d
            # Cycles/Eevee wrap the draw in bind_display_space_shader so the
            # viewport color management pipeline is applied. We do the same —
            # the raytracer outputs linear scene-referred values and Blender
            # applies the view/display transform here.
            self.bind_display_space_shader(scene)
            draw_texture_2d(self._viewport_texture, (0, 0), region.width, region.height)
            self.unbind_display_space_shader()
        except Exception as e:
            print(f"Astroray view_draw error: {e}")
            traceback.print_exc()

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

        - In CAMERA view (numpad 0): use the scene camera, then apply the
          viewport-only `view_camera_zoom` and `view_camera_offset` so
          wheel-zoom and pan actually change the rendered framing.
        - In PERSP / ORTHO view: derive position + direction from
          `rv3d.view_matrix.inverted()` and use `space_data.lens` for vfov.
        """
        rv3d = context.region_data
        space = context.space_data

        if rv3d is not None and rv3d.view_perspective == 'CAMERA' and context.scene.camera:
            zoom_scale = self._camera_view_zoom_scale(getattr(rv3d, 'view_camera_zoom', 0.0))
            offset = getattr(rv3d, 'view_camera_offset', (0.0, 0.0))
            self._apply_camera(renderer, context.scene.camera, width, height,
                               vfov_scale=zoom_scale,
                               viewport_shift=(float(offset[0]), float(offset[1])))
            return

        view_inv = rv3d.view_matrix.inverted()
        loc = view_inv.translation
        rot = view_inv.to_3x3()
        forward = rot @ mathutils.Vector((0.0, 0.0, -1.0))
        up      = rot @ mathutils.Vector((0.0, 1.0,  0.0))

        look_from = [loc.x, loc.y, loc.z]
        look_at   = [loc.x + forward.x, loc.y + forward.y, loc.z + forward.z]
        vup       = [up.x, up.y, up.z]

        # Blender's viewport uses a fixed 32mm sensor width and exposes the
        # effective focal length via space_data.lens (in mm).
        sensor_width = 32.0
        lens = getattr(space, 'lens', 50.0)
        aspect = width / max(1, height)
        hfov = 2.0 * math.atan(sensor_width / (2.0 * lens))
        vfov_rad = 2.0 * math.atan(math.tan(hfov / 2.0) / aspect)
        vfov = math.degrees(vfov_rad)

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
        self._viewport_texture = gpu.types.GPUTexture(
            (width, height), format='RGBA16F', data=buf)
        self._viewport_width = width
        self._viewport_height = height

    def convert_scene(self, depsgraph, renderer, width, height):
        scene = depsgraph.scene
        renderer.clear()
        settings = scene.custom_raytracer
        renderer.set_clamp_direct(settings.clamp_direct)
        renderer.set_clamp_indirect(settings.clamp_indirect)
        renderer.set_filter_glossy(settings.filter_glossy)
        renderer.set_use_reflective_caustics(settings.use_reflective_caustics)
        renderer.set_use_refractive_caustics(settings.use_refractive_caustics)
        cycles = getattr(scene, 'cycles', None)
        render_settings = getattr(scene, 'render', None)
        exposure = float(getattr(cycles, 'film_exposure', 1.0)) if cycles else 1.0
        renderer.set_film_exposure(exposure)
        use_transparent_film = bool(getattr(render_settings, 'film_transparent', False)) if render_settings else False
        transparent_glass = bool(getattr(cycles, 'film_transparent_glass', False)) if cycles else False
        renderer.set_use_transparent_film(use_transparent_film)
        renderer.set_transparent_glass(transparent_glass)
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
        self.setup_camera(scene, renderer, width, height)
        material_map = self.convert_materials(depsgraph, renderer)
        self.convert_objects(depsgraph, renderer, material_map)
        self.convert_lights(depsgraph, renderer)
        self.setup_world(scene, renderer)

    def setup_camera(self, scene, renderer, width, height):
        cam_obj = scene.camera
        if not cam_obj: return
        self._apply_camera(renderer, cam_obj, width, height)

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
                      viewport_shift=(0.0, 0.0)):
        """Extract lookFrom/lookAt/vup from a Blender camera object and push
        it to the renderer. Blender cameras point along their local -Z and
        use local +Y as 'up'; we rotate those unit vectors by the camera's
        world rotation to get world-space directions.

        `vfov_scale` (default 1.0) shrinks the effective image plane. Used by
        viewport CAMERA-view wheel-zoom to narrow the FOV without changing
        the scene camera (pkg52). 1.0 = no change; <1.0 = zoom in.

        `viewport_shift` is the CAMERA-view pan offset from RegionView3D. It
        is added to the camera datablock's own shift and passed as an
        image-plane shift to the C++ camera.
        """
        matrix = cam_obj.matrix_world
        loc, rot_quat, _scale = matrix.decompose()

        forward = rot_quat @ mathutils.Vector((0.0, 0.0, -1.0))
        up      = rot_quat @ mathutils.Vector((0.0, 1.0,  0.0))

        look_from = [loc.x, loc.y, loc.z]
        look_at   = [loc.x + forward.x, loc.y + forward.y, loc.z + forward.z]
        vup       = [up.x, up.y, up.z]

        camera = cam_obj.data
        vfov = self._compute_vfov_degrees(camera, width, height)

        # Apply viewport zoom by scaling the image plane → tighter FOV.
        if vfov_scale != 1.0 and vfov_scale > 0.0:
            half = math.radians(vfov) / 2.0
            vfov = math.degrees(2.0 * math.atan(math.tan(half) * vfov_scale))

        aperture, focus_dist = 0.0, 10.0
        if camera.dof.use_dof:
            if camera.dof.aperture_fstop > 0:
                aperture = 1.0 / (2 * camera.dof.aperture_fstop)
            if camera.dof.focus_object:
                focus_dist = (loc - camera.dof.focus_object.matrix_world.translation).length
            else:
                focus_dist = camera.dof.focus_distance

        shift_x = float(getattr(camera, "shift_x", 0.0)) + float(viewport_shift[0])
        shift_y = float(getattr(camera, "shift_y", 0.0)) + float(viewport_shift[1])

        renderer.setup_camera(look_from, look_at, vup, vfov,
                              width / max(1, height),
                              aperture, focus_dist, width, height,
                              shift_x, shift_y)

    def convert_materials(self, depsgraph, renderer):
        # In Blender 5.0+ every material is node-based (use_nodes is deprecated
        # and always True), so we always go through the node tree conversion.
        material_map = {}
        self._volume_material_map = {}
        for mat in bpy.data.materials:
            material_map[mat.name] = self.convert_node_material(mat, renderer)
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

        inlined = None
        try:
            inlined = mat.inline_shader_nodes()
            node_tree = inlined.node_tree
        except (AttributeError, RuntimeError):
            # Pre-5.0 Blender: fall back to direct access
            node_tree = getattr(mat, 'node_tree', None)
        if node_tree is None:
            return _apply_spectral_profile(renderer.create_material('disney', [0.8, 0.8, 0.8], {}))

        # pkg57 pre-check: if an AstrorayOutputNode is present anywhere in the
        # flattened tree, take the Astroray-native path. The original
        # OUTPUT_MATERIAL (if any) is left wired so Cycles continues to render
        # the same material correctly. See blender-shader-nodes-research.md §2.
        astroray_out = next(
            (n for n in node_tree.nodes if getattr(n, 'bl_idname', None) == 'AstrorayOutputNode'),
            None,
        )
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
        bl_idname = getattr(wired, 'bl_idname', '')

        if bl_idname == 'AstrorayShaderNodeSellmeierGlass':
            return self._create_astroray_material(
                self._astroray_sellmeier_spec(wired, mat), renderer, node_tree)
        if bl_idname == 'AstrorayShaderNodeIrUvResponse':
            return self._create_astroray_material(
                self._astroray_ir_uv_spec(wired, mat), renderer, node_tree)
        if bl_idname == 'AstrorayShaderNodeNrcHint':
            return self._create_astroray_material(
                self._astroray_nrc_hint_spec(wired, mat, renderer), renderer, node_tree)
        if bl_idname == 'AstrorayShaderNodeSpectralProfile':
            # A bare spectral-profile node wired to Surface produces a neutral
            # diffuse that the spectral profile multiplies — matches pkg58.
            return self._create_astroray_material(
                {'kind': 'astroray_spectral_only',
                 'profile': self._astroray_read_profile(wired, mat)},
                renderer, node_tree)
        # Cycles / standalone fallback: dispatch through the existing path.
        return self.convert_shader_node(wired, renderer, node_tree)

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

    def _astroray_ir_uv_spec(self, node, mat):
        """IR/UV response wraps a base BSDF (its Surface input). For now we
        promote the wrapper itself to a Disney with the band reflectance
        applied as a tint — a full multi-band response material is pkg-future
        work; this keeps the node functional without inventing a closure."""
        base_node = None
        surface_in = node.inputs.get('Surface')
        if surface_in is not None and surface_in.is_linked:
            base_node = surface_in.links[0].from_node
        return {
            'kind': 'astroray_ir_uv',
            'band': getattr(node, 'band', 'ir'),
            'reflectance': float(getattr(node, 'reflectance', 0.5)),
            'profile': self._astroray_read_profile(node, mat) if False else '',
            'base_bl_idname': getattr(base_node, 'bl_idname', '') if base_node else '',
        }

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

        if kind == 'astroray_ir_uv':
            # Promote to a neutral Disney; the IR/UV reflectance is exposed as
            # the base color for the chosen band. Spectral-aware multi-band
            # closures live in the integrator layer (pkg58/60) and are picked
            # up automatically via the spectral_profile path when set.
            r = float(spec.get('reflectance', 0.5))
            return renderer.create_material('disney', [r, r, r], {'roughness': 0.5})

        if kind == 'astroray_passthrough':
            inner = spec.get('inner')
            if inner is None:
                return renderer.create_material('disney', [0.8, 0.8, 0.8], {})
            return self.convert_shader_node(inner, renderer, node_tree)

        if kind == 'astroray_spectral_only':
            # Profile is applied via _apply_spectral_profile in the caller.
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
    def _resolve_vector_input(vector_socket, depth=0):
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

        Limit chain depth to avoid pathological node graphs (Mapping → Mapping
        → Mapping…).
        """
        coord_mode = "UV"
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
                CustomRaytracerRenderEngine._resolve_vector_input(inner_socket, depth + 1)
            return inner_coord, scale, offset, rotation, inner_layer

        if ntype == 'TEX_COORD':
            if src_socket_name == 'Generated':
                return "GENERATED", scale, offset, rotation, uv_layer_name
            if src_socket_name == 'Object':
                return "OBJECT", scale, offset, rotation, uv_layer_name
            if src_socket_name == 'UV':
                return "UV", scale, offset, rotation, getattr(src, 'uv_map', '') or ""
            # 'UV' (default), 'Camera', 'Window', 'Reflection', 'Normal' →
            # fall through to "UV". A future package can extend this.
            return "UV", scale, offset, rotation, uv_layer_name

        if ntype == 'UVMAP':
            return "UV", scale, offset, rotation, getattr(src, 'uv_map', '') or ""

        return coord_mode, scale, offset, rotation, uv_layer_name

    @staticmethod
    def _is_default_uv_transform(coord_mode, scale, offset, rotation, uv_layer_name=""):
        return (coord_mode == "UV"
                and abs(scale[0] - 1.0) < 1e-6 and abs(scale[1] - 1.0) < 1e-6
                and abs(offset[0]) < 1e-6 and abs(offset[1]) < 1e-6
                and abs(rotation) < 1e-6
                and not uv_layer_name)

    @staticmethod
    def _texture_variant_key(base_name, coord_mode, scale, offset, rotation, uv_layer_name=""):
        """Cache key that distinguishes the same image used with different
        Mapping or coord-mode wiring across materials."""
        if CustomRaytracerRenderEngine._is_default_uv_transform(
                coord_mode, scale, offset, rotation, uv_layer_name):
            return base_name
        return (f"{base_name}::{coord_mode}::"
                f"{scale[0]:.4f},{scale[1]:.4f},"
                f"{offset[0]:.4f},{offset[1]:.4f},"
                f"{rotation:.4f}::{uv_layer_name}")

    def _apply_texture_transform(self, renderer, tex_name, coord_mode,
                                 scale, offset, rotation, uv_layer_name=""):
        """Push coord_mode + UV transform to the C++ side (no-ops if default)."""
        try:
            if coord_mode != "UV":
                renderer.set_texture_coord_mode(tex_name, coord_mode)
            if uv_layer_name and hasattr(renderer, "set_texture_uv_layer"):
                renderer.set_texture_uv_layer(tex_name, uv_layer_name)
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
        coord_mode, uv_scale, offset, rotation, uv_layer_name = self._resolve_vector_input(vector_input)
        cache_key = self._texture_variant_key(bpy_image.name, coord_mode, uv_scale, offset, rotation, uv_layer_name)

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
            self._apply_texture_transform(renderer, cache_key, coord_mode, uv_scale, offset, rotation, uv_layer_name)
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
        coord_mode, uv_scale, offset, rotation, uv_layer_name = self._resolve_vector_input(vector_input)
        cache_key = self._texture_variant_key(f"_proc_{id(node)}", coord_mode, uv_scale, offset, rotation, uv_layer_name)
        if cache_key in cache:
            return cache[cache_key]
        node_id = id(node)

        ntype = node.type
        tex_name = None
        try:
            if ntype == 'TEX_NOISE':
                scale = float(node.inputs['Scale'].default_value) if node.inputs.get('Scale') else 5.0
                tex_name = f"_proc_noise_{node_id}"
                renderer.create_procedural_texture(tex_name, 'noise', [scale])
            elif ntype == 'TEX_CHECKER':
                scale = float(node.inputs['Scale'].default_value) if node.inputs.get('Scale') else 5.0
                c1 = list(node.inputs['Color1'].default_value[:3]) if node.inputs.get('Color1') else [1,1,1]
                c2 = list(node.inputs['Color2'].default_value[:3]) if node.inputs.get('Color2') else [0,0,0]
                tex_name = f"_proc_checker_{node_id}"
                renderer.create_procedural_texture(tex_name, 'checker',
                    c1 + c2 + [scale])
            elif ntype == 'TEX_VORONOI':
                scale = float(node.inputs['Scale'].default_value) if node.inputs.get('Scale') else 5.0
                randomness = float(node.inputs['Randomness'].default_value) if node.inputs.get('Randomness') else 1.0
                smoothness = float(node.inputs.get('Smoothness', type(None) or type(0)).default_value) if node.inputs.get('Smoothness') else 1.0
                dist_map = {'EUCLIDEAN': 0, 'MANHATTAN': 1, 'CHEBYCHEV': 2, 'MINKOWSKI': 3}
                feat_map = {'F1': 0, 'F2': 1, 'F1_F2': 2, 'SMOOTH_F1': 4, 'DISTANCE_TO_EDGE': 3}
                dm = dist_map.get(getattr(node, 'distance', 'EUCLIDEAN'), 0)
                feat = feat_map.get(getattr(node, 'feature', 'F1'), 0)
                tex_name = f"_proc_voronoi_{node_id}"
                renderer.create_procedural_texture(tex_name, 'voronoi',
                    [scale, randomness, float(dm), float(feat), smoothness, 0,0,0, 1,1,1])
            elif ntype == 'TEX_WAVE':
                scale = float(node.inputs['Scale'].default_value) if node.inputs.get('Scale') else 5.0
                dist = float(node.inputs['Distortion'].default_value) if node.inputs.get('Distortion') else 0.0
                detail = float(node.inputs['Detail'].default_value) if node.inputs.get('Detail') else 2.0
                rough = float(node.inputs['Detail Roughness'].default_value or node.inputs.get('Roughness', type(0)).default_value) \
                    if node.inputs.get('Detail Roughness') else 0.5
                lac = float(node.inputs['Detail Scale'].default_value) if node.inputs.get('Detail Scale') else 2.0
                bd = 1 if getattr(node, 'wave_type', 'BANDS') == 'RINGS' else 0
                profile_map = {'SINE': 0, 'SAW': 1, 'TRIANGLE': 2}
                prof = profile_map.get(getattr(node, 'bands_direction', 'SINE'), 0)
                tex_name = f"_proc_wave_{node_id}"
                renderer.create_procedural_texture(tex_name, 'wave',
                    [float(bd), float(prof), scale, dist, detail, rough, lac, 0,0,0, 1,1,1])
            elif ntype == 'TEX_MAGIC':
                depth = int(node.turbulence_depth) if hasattr(node, 'turbulence_depth') else 2
                scale = float(node.inputs['Scale'].default_value) if node.inputs.get('Scale') else 5.0
                dist = float(node.inputs['Distortion'].default_value) if node.inputs.get('Distortion') else 1.0
                tex_name = f"_proc_magic_{node_id}"
                renderer.create_procedural_texture(tex_name, 'magic',
                    [float(depth), scale, dist, 0,0,0, 1,1,1])
            elif ntype == 'TEX_BRICK':
                scale = float(node.inputs['Scale'].default_value) if node.inputs.get('Scale') else 5.0
                mortar = float(node.inputs['Mortar Size'].default_value) if node.inputs.get('Mortar Size') else 0.02
                offset = float(node.inputs['Offset'].default_value) if node.inputs.get('Offset') else 0.5
                c_brick = list(node.inputs['Color1'].default_value[:3]) if node.inputs.get('Color1') else [0.7, 0.35, 0.2]
                c_mortar = list(node.inputs['Color3'].default_value[:3]) if node.inputs.get('Color3') else [0.9, 0.9, 0.9]
                bw = float(node.inputs['Brick Width'].default_value) if node.inputs.get('Brick Width') else 0.5
                bh = float(node.inputs['Row Height'].default_value) if node.inputs.get('Row Height') else 0.25
                tex_name = f"_proc_brick_{node_id}"
                renderer.create_procedural_texture(tex_name, 'brick',
                    c_brick + c_mortar + [bw, bh, mortar, offset, scale])
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

    def _warn_shader_fallback(self, node_type, message):
        key = f"{node_type}:{message}"
        warned = getattr(self, '_shader_fallback_warnings', None)
        if warned is None:
            warned = set()
            self._shader_fallback_warnings = warned
        if key in warned:
            return
        warned.add(key)
        text = f"Astroray: {node_type} fallback: {message}"
        try:
            self.report({'WARNING'}, text)
        except (AttributeError, RuntimeError, TypeError) as exc:
            print(f"Astroray: could not forward warning to Blender UI ({exc})")
        print(text)

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
        if emission_strength > 0.0 and any(c > 0 for c in emission_color):
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

        return renderer.create_material('disney', base_color, params)

    def convert_objects(self, depsgraph, renderer, material_map):
        tri_count = 0
        obj_count = 0
        is_render = getattr(depsgraph, 'mode', 'VIEWPORT') == 'RENDER'
        active_view_layer = getattr(depsgraph, "view_layer", None)
        for obj_instance in depsgraph.object_instances:
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
                        renderer.add_black_hole(
                            [mw.translation.x, mw.translation.y, mw.translation.z],
                            bh.mass,
                            bh.influence_radius,
                            {
                                'disk_outer':     bh.disk_outer,
                                'accretion_rate': bh.accretion_rate,
                                'inclination':    bh.inclination,
                            }
                        )
                    except Exception as e:
                        print(f"Black hole conversion error: {e}")
                continue

            if obj.type != 'MESH':
                continue

            mesh = obj.data
            if mesh is None:
                continue
            matrix = obj_instance.matrix_world
            obj_count += 1

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

            # Flip the caustic-caster flag on every renderer object the
            # current Blender object contributed (one Blender mesh →
            # many add_triangle calls).
            if is_caustic_caster and hasattr(renderer, "set_object_caustic_caster"):
                scene_count_after = renderer.scene_object_count()
                for oid in range(scene_count_before, scene_count_after):
                    renderer.set_object_caustic_caster(oid, True)

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

        for obj in depsgraph.objects:
            if obj.type != 'LIGHT': continue
            light = obj.data
            matrix = obj.matrix_world
            position = list(matrix.translation)
            mat_id = renderer.create_material('light', list(light.color), {'intensity': float(light.energy)})
            ies_path = _resolve_ies_path(light)

            if light.type == 'POINT':
                direction = matrix.to_3x3() @ mathutils.Vector((0, 0, -1))
                if direction.length_squared > 0.0:
                    direction.normalize()
                else:
                    direction = mathutils.Vector((0.0, -1.0, 0.0))
                renderer.add_sphere(
                    position, 0.1, mat_id, [direction.x, direction.y, direction.z], ies_path,
                    int(getattr(obj, "pass_index", 0)), 0
                )
            elif light.type == 'SUN':
                direction = matrix.to_3x3() @ mathutils.Vector((0, 0, -1))
                angle = float(getattr(light, 'angle', 0.0))
                renderer.add_sun_light(
                    [direction.x, direction.y, direction.z], angle, mat_id,
                    int(getattr(obj, "pass_index", 0)), 0
                )
            elif light.type == 'AREA':
                basis = matrix.to_3x3()
                axis_u = list((basis @ mathutils.Vector((1, 0, 0))).normalized())
                axis_v = list((basis @ mathutils.Vector((0, 1, 0))).normalized())
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
                renderer.add_area_light(
                    position, axis_u, axis_v, size_x, size_y,
                    shape_map.get(shape, 'RECTANGLE'), mat_id, spread,
                    int(getattr(obj, "pass_index", 0)), 0
                )
            elif light.type == 'SPOT':
                direction = (matrix.to_3x3() @ mathutils.Vector((0, 0, -1))).normalized()
                radius = float(max(getattr(light, 'shadow_soft_size', 0.0), 0.0))
                renderer.add_spot_light(
                    position,
                    [direction.x, direction.y, direction.z],
                    radius,
                    mat_id,
                    float(light.spot_size),
                    float(light.spot_blend),
                    ies_path,
                    int(getattr(obj, "pass_index", 0)),
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

        # Apply world bounce limit (Cycles: world.light_settings.max_bounces)
        world_settings = getattr(world, 'light_settings', None)
        world_max_bounces = int(getattr(world_settings, 'max_bounces', 1024)) if world_settings else 1024
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

        # Fallback: solid background color
        if bg_color and strength > 0.01:
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

            for display_name, key in self._enabled_cryptomatte_pass_specs(view_layer):
                target_pass = layer.passes.get(display_name)
                if target_pass is None:
                    continue
                try:
                    if key == "cryptomatte_object":
                        crypto = np.asarray(renderer.get_cryptomatte_object_buffer(), dtype=np.float32)
                    else:
                        crypto = np.asarray(renderer.get_cryptomatte_material_buffer(), dtype=np.float32)
                except Exception:
                    continue
                pass_rgba = np.ascontiguousarray(crypto[::-1])
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

        col = layout.column(align=True)
        col.prop(settings, "samples", text="Render")
        col.prop(settings, "preview_samples", text="Viewport")

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


class RENDER_PT_custom_raytracer_light_paths(AstrorayPanelBase, Panel):
    bl_label = "Light Paths"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "render"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        settings = context.scene.custom_raytracer

        col = layout.column(align=True)
        col.prop(settings, "max_bounces", text="Total")
        col.prop(settings, "diffuse_bounces")
        col.prop(settings, "glossy_bounces")
        col.prop(settings, "transmission_bounces")
        col.prop(settings, "volume_bounces")
        col.prop(settings, "transparent_bounces")
        col.prop(settings, "clamp_direct")
        col.prop(settings, "clamp_indirect")
        layout.separator()
        caustics = layout.box()
        caustics.label(text="Caustics")
        caustics.prop(settings, "filter_glossy")
        row = caustics.row(align=True)
        row.prop(settings, "use_reflective_caustics")
        row.prop(settings, "use_refractive_caustics")


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
        try:
            feats = astroray.__features__
            active = [k for k, v in feats.items() if v]
            inactive = [k for k, v in feats.items() if not v]
            col.label(text="Features:")
            col.label(text="  On:  " + (", ".join(active) if active else "none"))
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
            for feat, enabled in astroray.__features__.items():
                box.label(text=f"  {feat.replace('_', ' ').title()}", icon='CHECKBOX_HLT' if enabled else 'CHECKBOX_DEHLT')
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
    disk_outer: FloatProperty(name="Disk Outer Radius (M)", min=6.0, max=1000.0, default=30.0,
                               description="Accretion disk outer radius in units of M")
    accretion_rate: FloatProperty(name="Accretion Rate", min=0.01, max=100.0, default=1.0,
                                   description="Dimensionless accretion rate (sets disk brightness)")
    inclination: FloatProperty(name="Inclination (\u00b0)", min=0.0, max=90.0, default=75.0,
                                description="Observer inclination from the spin axis")
    show_disk: BoolProperty(name="Show Accretion Disk", default=True)


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
        col.separator()
        col.prop(bh, "disk_outer")
        col.prop(bh, "accretion_rate")
        col.prop(bh, "inclination")
        col.prop(bh, "show_disk")


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


classes = [
    CustomRaytracerRenderSettings, CustomRaytracerMaterialSettings,
    AstrorayObjectProperties,
    AstrorayBlackHoleProperties,
    CustomRaytracerRenderEngine,
    RENDER_PT_custom_raytracer_sampling,
    RENDER_PT_custom_raytracer_light_paths,
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


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.custom_raytracer = PointerProperty(type=CustomRaytracerRenderSettings)
    bpy.types.Material.custom_raytracer = PointerProperty(type=CustomRaytracerMaterialSettings)
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
    for panel in _iter_compat_panels():
        panel.COMPAT_ENGINES.discard('CUSTOM_RAYTRACER')

    if _ASTRORAY_NODES_AVAILABLE:
        try:
            astroray_nodes.unregister()
        except Exception as exc:  # pragma: no cover - defensive
            print(f"Astroray native shader nodes unregister() failed: {exc}")

    del bpy.types.Scene.custom_raytracer
    del bpy.types.Material.custom_raytracer
    del bpy.types.Object.astroray_black_hole
    del bpy.types.Object.astroray_object
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    print("Astroray renderer addon unregistered")


if __name__ == "__main__":
    register()
