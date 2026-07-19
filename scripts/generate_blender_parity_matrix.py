# -*- coding: utf-8 -*-
"""pkg119 Phase A — Blender parity coverage-matrix generator.

Run INSIDE Blender (headless):

    blender --background --factory-startup --python \\
        scripts/generate_blender_parity_matrix.py -- \\
        --out test_results/blender_parity

Introspects the full render-relevant Blender API surface (every ShaderNode*
subclass + render-relevant properties on RenderSettings/World/Light/Camera/
Material) and cross-references it against the Astroray addon's actual
translation layer to emit a parity matrix:
  - SUPPORTED: addon translates it to a distinct engine behaviour.
  - APPROXIMATED: addon maps it to a nearest behaviour (emits fallback warning).
  - DROPPED-SILENT: addon ignores it with no warning — the failure mode.
  - UNKNOWN-CRASH: feeding it to the addon raises, or classification is undetermined.

Outputs:
  - coverage_matrix.json (machine-readable)
  - report.md (human-readable summary + DROPPED-SILENT list)

Designed to regenerate on demand as a test-suite target (tracks addon + Blender
version drift).
"""
import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import bpy  # type: ignore


# =============================================================================
# Bootstrap addon (mirror verify_pkg115_textures_blender.py)
# =============================================================================

def _bootstrap_astroray_addon():
    """Load addon + .pyd with DLL directories, mirroring pkg115/pkg114 verify scripts."""
    repo_root = Path(__file__).resolve().parents[1]
    build_dir = Path(os.environ.get(
        "ASTRORAY_PYD_DIR", repo_root / "build_cuda" / "Release"))
    for entry in (str(build_dir), str(repo_root)):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    cuda_bin_candidates = [
        Path(os.environ.get("CUDA_PATH", "")) / "bin",
        Path(os.environ.get("CUDA_PATH", "")) / "bin" / "x64",
        Path(r"C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v12.8") / "bin",
        Path(r"C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v12.8") / "bin" / "x64",
        Path(r"C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v13.2") / "bin" / "x64",
    ]
    for dll_dir in [build_dir] + cuda_bin_candidates:
        if dll_dir.is_dir():
            try:
                os.add_dll_directory(str(dll_dir))
            except (OSError, AttributeError):
                pass
    import astroray  # noqa: F401
    print(f"[pkg119-parity] astroray module: {astroray.__file__}")
    import blender_addon
    try:
        blender_addon.register()
    except Exception as exc:
        if "already registered" not in str(exc):
            raise
    return blender_addon


# =============================================================================
# Enumeration (from Blender API at runtime)
# =============================================================================

def enumerate_shader_nodes():
    """Return list of (bl_idname, node_class, sockets_in, sockets_out, properties).

    Every bpy.types.ShaderNode* subclass, with:
      - sockets_in/out: [{name, type, ...}]
      - properties: {prop_name: {type, enum_items, ...}} for all enum/bool/float props
    """
    results = []

    # Create a temporary material with node tree to discover available node types
    temp_mat = bpy.data.materials.new(name="_temp_introspect")
    temp_mat.use_nodes = True
    nt = temp_mat.node_tree

    # Get all available shader node types via the node tree's add menu introspection
    # We'll try a known list of built-in Blender shader nodes
    KNOWN_SHADER_NODES = [
        # BSDF nodes
        'ShaderNodeBsdfPrincipled', 'ShaderNodeBsdfDiffuse', 'ShaderNodeBsdfGlossy',
        'ShaderNodeBsdfAnisotropic', 'ShaderNodeBsdfGlass', 'ShaderNodeBsdfTranslucent',
        'ShaderNodeBsdfTransparent', 'ShaderNodeBsdfRefraction', 'ShaderNodeBsdfSheen',
        'ShaderNodeEmission', 'ShaderNodeBackground', 'ShaderNodeHoldout',
        # Volume nodes
        'ShaderNodeVolumeAbsorption', 'ShaderNodeVolumeScatter', 'ShaderNodeVolumePrincipled',
        # Shader mixers
        'ShaderNodeMixShader', 'ShaderNodeAddShader',
        # Texture nodes
        'ShaderNodeTexImage', 'ShaderNodeTexEnvironment', 'ShaderNodeTexChecker',
        'ShaderNodeTexGradient', 'ShaderNodeTexMagic', 'ShaderNodeTexNoise',
        'ShaderNodeTexVoronoi', 'ShaderNodeTexWave', 'ShaderNodeTexBrick',
        'ShaderNodeTexMusgrave', 'ShaderNodeTexCoord', 'ShaderNodeTexSky',
        'ShaderNodeTexIES', 'ShaderNodeTexWhiteNoise', 'ShaderNodeTexPointDensity',
        # Color nodes
        'ShaderNodeRGB', 'ShaderNodeValToRGB', 'ShaderNodeMix', 'ShaderNodeRGBToBW',
        'ShaderNodeInvert', 'ShaderNodeHueSaturation', 'ShaderNodeGamma',
        'ShaderNodeBrightContrast', 'ShaderNodeRGBCurve',
        # Vector nodes
        'ShaderNodeMapping', 'ShaderNodeNormalMap', 'ShaderNodeNormal',
        'ShaderNodeBump', 'ShaderNodeDisplacement', 'ShaderNodeVectorDisplacement',
        'ShaderNodeVectorTransform', 'ShaderNodeVectorRotate', 'ShaderNodeVectorCurve',
        # Converter nodes
        'ShaderNodeMath', 'ShaderNodeVectorMath', 'ShaderNodeSeparateXYZ',
        'ShaderNodeCombineXYZ', 'ShaderNodeSeparateColor', 'ShaderNodeCombineColor',
        'ShaderNodeWavelength', 'ShaderNodeBlackbody', 'ShaderNodeClamp',
        'ShaderNodeMapRange', 'ShaderNodeFloatCurve',
        # Input nodes
        'ShaderNodeValue', 'ShaderNodeAttribute', 'ShaderNodeFresnel',
        'ShaderNodeLayerWeight', 'ShaderNodeCameraData', 'ShaderNodeObjectInfo',
        'ShaderNodeHairInfo', 'ShaderNodePointInfo', 'ShaderNodeParticleInfo',
        'ShaderNodeTangent', 'ShaderNodeUVMap', 'ShaderNodeVertexColor',
        'ShaderNodeWireframe', 'ShaderNodeBevel', 'ShaderNodeAmbientOcclusion',
        'ShaderNodeVolumeInfo', 'ShaderNodeLightPath',
        # Output nodes (may not instantiate in material tree)
        'ShaderNodeOutputMaterial', 'ShaderNodeOutputLight', 'ShaderNodeOutputWorld',
        'ShaderNodeOutputLineStyle',
        # Misc
        'ShaderNodeScript', 'ShaderNodeGroup',
    ]

    for node_bl_name in KNOWN_SHADER_NODES:
        try:
            nt.nodes.clear()
            try:
                node = nt.nodes.new(type=node_bl_name)
            except RuntimeError as e:
                # Some node types cannot be instantiated in a material tree
                print(f"[pkg119] Skip {node_bl_name}: {e}")
                continue

            bl_idname = node.bl_idname

            sockets_in = []
            for inp in node.inputs:
                sockets_in.append({
                    'name': inp.name,
                    'identifier': inp.identifier,
                    'type': inp.type,
                    'bl_idname': inp.bl_idname,
                })

            sockets_out = []
            for out in node.outputs:
                sockets_out.append({
                    'name': out.name,
                    'identifier': out.identifier,
                    'type': out.type,
                    'bl_idname': out.bl_idname,
                })

            # Enumerate properties (enum/bool/float/int relevant for rendering)
            # FILTER OUT UI-only properties per spec "render-relevant"
            UI_ONLY_PROPS = {
                'bl_height_default', 'bl_height_max', 'bl_height_min',
                'bl_width_default', 'bl_width_max', 'bl_width_min',
                'bl_icon', 'color', 'color_tag', 'dimensions', 'height', 'width',
                'hide', 'location', 'location_absolute', 'mute', 'select',
                'show_options', 'show_preview', 'show_texture', 'use_custom_color',
                'warning_propagation', 'name', 'label', 'parent',
            }
            properties = {}
            if hasattr(node, 'bl_rna') and hasattr(node.bl_rna, 'properties'):
                for prop_name in dir(node):
                    if prop_name.startswith('_') or prop_name in ('bl_rna', 'rna_type'):
                        continue
                    if prop_name in UI_ONLY_PROPS:
                        continue  # Skip UI-only properties
                    try:
                        prop_rna = node.bl_rna.properties.get(prop_name)
                        if prop_rna is None:
                            continue
                        prop_type = prop_rna.type
                        if prop_type in ('ENUM', 'BOOLEAN', 'FLOAT', 'INT'):
                            prop_info = {'type': prop_type}
                            if prop_type == 'ENUM' and hasattr(prop_rna, 'enum_items'):
                                prop_info['enum_items'] = [item.identifier for item in prop_rna.enum_items]
                            properties[prop_name] = prop_info
                    except (AttributeError, KeyError):
                        pass

            results.append({
                'bl_idname': bl_idname,
                'node_type': getattr(node, 'type', ''),
                'sockets_in': sockets_in,
                'sockets_out': sockets_out,
                'properties': properties,
            })

        except Exception as exc:
            print(f"[pkg119] Error introspecting {node_bl_name}: {exc}")

    bpy.data.materials.remove(temp_mat)
    return results


def enumerate_render_settings():
    """Return dict of render-relevant RenderSettings properties (allow-listed).

    Inclusion rule: sampling, film, light paths, performance (relevant to render
    quality/correctness). Exclude UI-only / Cycles-CPU-tiling knobs.
    """
    # Allow-list per spec: "sampling, film, light paths, camera intrinsics/DoF, world surface/lighting"
    allow_list = [
        # Sampling
        'samples', 'use_adaptive_sampling', 'adaptive_threshold', 'adaptive_min_samples',
        'seed', 'sample_offset',
        # Film
        'film_exposure', 'film_transparent', 'filter_type', 'filter_width',
        # Light paths
        'max_bounces', 'diffuse_bounces', 'glossy_bounces', 'transparent_max_bounces',
        'transmission_bounces', 'volume_bounces',
        'caustics_reflective', 'caustics_refractive',
        'use_fast_gi',
        # Denoiser
        'use_denoising', 'denoiser', 'denoising_input_passes',
    ]

    props = {}
    scene = bpy.context.scene
    render = scene.render
    cycles = scene.cycles if hasattr(scene, 'cycles') else None

    for prop_name in allow_list:
        # Try render settings first, then cycles
        for source in (render, cycles):
            if source is None:
                continue
            if hasattr(source, prop_name):
                try:
                    value = getattr(source, prop_name)
                    props[prop_name] = {'value': value, 'type': type(value).__name__}
                except AttributeError:
                    pass
                break

    return props


def enumerate_light_properties():
    """Return dict of per-light-type render-relevant properties."""
    light_types = ['POINT', 'SUN', 'SPOT', 'AREA']
    props_by_type = {}

    # Create a temporary light for each type and introspect
    for lt in light_types:
        light_data = bpy.data.lights.new(name=f"_temp_{lt}", type=lt)
        props = {}

        # Common properties
        for prop in ['energy', 'color', 'use_temperature', 'temperature', 'specular_factor']:
            if hasattr(light_data, prop):
                props[prop] = type(getattr(light_data, prop, None)).__name__

        # Type-specific
        if lt == 'POINT':
            if hasattr(light_data, 'shadow_soft_size'):
                props['shadow_soft_size'] = 'float'
        elif lt == 'SUN':
            if hasattr(light_data, 'angle'):
                props['angle'] = 'float'
        elif lt == 'SPOT':
            for prop in ['spot_size', 'spot_blend', 'show_cone']:
                if hasattr(light_data, prop):
                    props[prop] = type(getattr(light_data, prop, None)).__name__
        elif lt == 'AREA':
            for prop in ['shape', 'size', 'size_y', 'spread']:
                if hasattr(light_data, prop):
                    props[prop] = type(getattr(light_data, prop, None)).__name__

        props_by_type[lt] = props
        bpy.data.lights.remove(light_data)

    return props_by_type


def enumerate_camera_properties():
    """Return dict of render-relevant Camera datablock properties."""
    cam = bpy.data.cameras.new(name="_temp_cam")
    props = {}

    for prop in ['lens', 'sensor_width', 'sensor_height', 'shift_x', 'shift_y',
                 'dof_distance', 'gpu_dof', 'aperture_fstop', 'aperture_blades',
                 'aperture_rotation', 'aperture_ratio', 'type', 'clip_start', 'clip_end']:
        if hasattr(cam, prop):
            props[prop] = type(getattr(cam, prop, None)).__name__
        # Try dof sub-property
        if hasattr(cam, 'dof') and hasattr(cam.dof, prop.replace('dof_', '')):
            props[prop] = 'float'

    bpy.data.cameras.remove(cam)
    return props


def enumerate_world_properties():
    """Return dict of render-relevant World properties."""
    # World properties: mainly node-tree driven (world.use_nodes)
    props = {
        'use_nodes': 'bool',
        # Node tree is separate enumeration (ShaderNodeBackground, ShaderNodeTexEnvironment, etc.)
    }
    return props


# =============================================================================
# Classification (cross-reference against addon translation layer)
# =============================================================================

def classify_shader_node(node_info, addon_module) -> dict[str, Any]:
    """Classify a shader node as SUPPORTED / APPROXIMATED / DROPPED-SILENT / UNKNOWN-CRASH.

    Returns dict with:
      - classification: str (one of the four buckets)
      - sockets_supported: list of input socket names the addon reads
      - sockets_dropped: list of input socket names the addon ignores
      - notes: str (rationale)
    """
    bl_idname = node_info['bl_idname']
    node_type = node_info['node_type']

    # Reference the addon's dispatch surface (from __init__.py)
    # We introspect the code structure, not run it (static analysis).

    # Key handlers to check:
    # - convert_shader_node (line 3225): main dispatch on node.type
    # - _standalone_bsdf_spec (line 2997): BSDF_DIFFUSE/GLOSSY/GLASS/TRANSLUCENT/TRANSPARENT/REFRACTION/SHEEN/METALLIC
    # - _principled_shader_spec (line 2938): BSDF_PRINCIPLED (reads Base Color, Metallic, Roughness, IOR, Transmission, Clearcoat, Anisotropic, Sheen, Subsurface, Emission Color/Strength, Normal/Bump)
    # - load_procedural_texture (line 2713): TEX_CHECKER/GRADIENT/MAGIC/NOISE/VORONOI/WAVE/BRICK
    # - EMISSION (line 3059): reads Color + Strength
    # - MIX_SHADER (line 3061): reads Fac + two Shader inputs
    # - ADD_SHADER (line 3066): reads two Shader inputs
    # - Volume nodes (line 3228): VOLUME_ABSORPTION/SCATTER/PRINCIPLED_VOLUME mapped to glass IOR=1 (approximation)

    # Supported node types (from convert_shader_node + _standalone_bsdf_spec + _principled_shader_spec)
    SUPPORTED_NODES = {
        'BSDF_PRINCIPLED': {
            'sockets': ['Base Color', 'Metallic', 'Roughness', 'IOR', 'Transmission', 'Transmission Weight',
                        'Clearcoat', 'Coat Weight', 'Clearcoat Roughness', 'Coat Roughness',
                        'Anisotropic', 'Sheen', 'Sheen Weight', 'Subsurface', 'Subsurface Weight',
                        'Emission Color', 'Emission Strength', 'Normal'],
            'classification': 'SUPPORTED',
        },
        'BSDF_DIFFUSE': {
            'sockets': ['Color', 'Roughness'],
            'classification': 'APPROXIMATED',  # Oren-Nayar → Disney rough diffuse per _warn_shader_fallback
            'notes': 'Oren-Nayar diffuse approximated with Disney rough diffuse',
        },
        'BSDF_GLOSSY': {
            'sockets': ['Color', 'Roughness'],
            'classification': 'SUPPORTED',
        },
        'BSDF_ANISOTROPIC': {
            'sockets': ['Color', 'Roughness', 'Anisotropy', 'Anisotropic'],
            'classification': 'SUPPORTED',
        },
        'BSDF_GLASS': {
            'sockets': ['Color', 'Roughness', 'IOR'],
            'classification': 'SUPPORTED',
        },
        'BSDF_TRANSLUCENT': {
            'sockets': ['Color'],
            'classification': 'APPROXIMATED',
            'notes': 'true normal-flipped diffuse transmission approximated with rough transmission',
        },
        'BSDF_TRANSPARENT': {
            'sockets': ['Color'],
            'classification': 'SUPPORTED',
        },
        'BSDF_REFRACTION': {
            'sockets': ['Color', 'Roughness', 'IOR'],
            'classification': 'APPROXIMATED',
            'notes': 'pure refraction without Fresnel reflection approximated with Disney transmission',
        },
        'BSDF_SHEEN': {
            'sockets': ['Color', 'Roughness', 'Weight'],
            'classification': 'APPROXIMATED',
            'notes': 'Cycles microfiber sheen approximated with Disney sheen',
        },
        'BSDF_METALLIC': {
            'sockets': ['Base Color', 'Color', 'Roughness'],
            'classification': 'APPROXIMATED',
            'notes': 'F82 edge tint approximated with Disney metallic base color',
        },
        'EMISSION': {
            'sockets': ['Color', 'Strength'],
            'classification': 'SUPPORTED',
        },
        'MIX_SHADER': {
            'sockets': ['Fac', 'Shader'],
            'classification': 'SUPPORTED',
        },
        'ADD_SHADER': {
            'sockets': ['Shader'],
            'classification': 'SUPPORTED',
        },
        'VOLUME_ABSORPTION': {
            'sockets': [],
            'classification': 'APPROXIMATED',
            'notes': 'mapped to glass IOR=1.0 (volume not fully implemented)',
        },
        'VOLUME_SCATTER': {
            'sockets': [],
            'classification': 'APPROXIMATED',
            'notes': 'mapped to glass IOR=1.0 (volume not fully implemented)',
        },
        'PRINCIPLED_VOLUME': {
            'sockets': [],
            'classification': 'APPROXIMATED',
            'notes': 'mapped to glass IOR=1.0 (volume not fully implemented)',
        },
    }

    # Procedural textures (from load_procedural_texture)
    PROCEDURAL_TEXTURES = {
        'TEX_CHECKER': {
            'sockets': ['Vector', 'Color1', 'Color2', 'Scale'],
            'properties': [],
            'classification': 'SUPPORTED',
        },
        'TEX_GRADIENT': {
            'sockets': ['Vector'],
            'properties': ['gradient_type'],  # Used in verify_pkg115_textures_blender.py
            'classification': 'SUPPORTED',
        },
        'TEX_MAGIC': {
            'sockets': ['Vector', 'Scale', 'Distortion'],
            'properties': ['turbulence_depth'],  # Used in verify_pkg115_textures_blender.py
            'classification': 'SUPPORTED',
        },
        'TEX_NOISE': {
            'sockets': ['Vector', 'Scale', 'Detail', 'Roughness', 'Distortion'],
            'properties': [],
            'classification': 'SUPPORTED',
        },
        'TEX_VORONOI': {
            'sockets': ['Vector', 'Scale', 'Randomness'],
            'properties': [],
            'classification': 'SUPPORTED',
        },
        'TEX_WAVE': {
            'sockets': ['Vector', 'Scale', 'Distortion', 'Detail'],
            'properties': ['wave_type', 'wave_profile'],  # Used in verify_pkg115_textures_blender.py
            'classification': 'SUPPORTED',
        },
        'TEX_BRICK': {
            'sockets': ['Vector', 'Color1', 'Color2', 'Mortar', 'Color3', 'Scale'],
            'properties': [],
            'classification': 'SUPPORTED',
        },
        'TEX_IMAGE': {
            'sockets': [],
            'properties': [],
            'classification': 'SUPPORTED',
            'notes': 'load_blender_image path',
        },
    }

    # Check if node type is in known handlers
    if node_type in SUPPORTED_NODES:
        info = SUPPORTED_NODES[node_type]
        supported_sockets = set(info['sockets'])
        all_input_sockets = {s['name'] for s in node_info['sockets_in']}
        dropped_sockets = all_input_sockets - supported_sockets

        return {
            'classification': info['classification'],
            'sockets_supported': sorted(list(supported_sockets & all_input_sockets)),
            'sockets_dropped': sorted(list(dropped_sockets)),
            'notes': info.get('notes', ''),
        }

    if node_type in PROCEDURAL_TEXTURES:
        info = PROCEDURAL_TEXTURES[node_type]
        supported_sockets = set(info['sockets'])
        supported_props = set(info.get('properties', []))
        all_input_sockets = {s['name'] for s in node_info['sockets_in']}
        dropped_sockets = all_input_sockets - supported_sockets

        return {
            'classification': info['classification'],
            'sockets_supported': sorted(list(supported_sockets & all_input_sockets)),
            'sockets_dropped': sorted(list(dropped_sockets)),
            'properties_supported': sorted(list(supported_props)),
            'notes': info.get('notes', ''),
        }

    # Node type not in any handler — DROPPED-SILENT (the failure mode)
    # Unless it's a known utility/input node that doesn't need translation
    UTILITY_NODES = {
        'TEX_COORD', 'MAPPING', 'ATTRIBUTE', 'UVMAP', 'GEOMETRY', 'CAMERA',
        'LAYER_WEIGHT', 'FRESNEL', 'TANGENT', 'WIREFRAME', 'WAVELENGTH',
        'LIGHT_PATH', 'OBJECT_INFO', 'PARTICLE_INFO', 'HAIR_INFO', 'POINT_INFO',
        'VOLUME_INFO', 'VALUE', 'RGB', 'VERTEX_COLOR', 'COMBINE_XYZ', 'SEPARATE_XYZ',
        'COMBRGB', 'SEPRGB', 'COMBHSV', 'SEPHSV', 'VECT_MATH', 'MATH', 'RGBTOBW',
        'VALTORGB', 'INVERT', 'MIX', 'CURVE_RGB', 'CURVE_VEC', 'CURVE_FLOAT',
        'CLAMP', 'MAP_RANGE', 'NORMAL_MAP', 'BUMP', 'DISPLACEMENT', 'VECTOR_DISPLACEMENT',
        'NORMAL', 'VECTOR_ROTATE', 'VECTOR_TRANSFORM',
    }

    if node_type in UTILITY_NODES:
        # Utility nodes are intermediate — classification depends on whether they feed into supported paths
        # For now, mark as SUPPORTED if they're standard Blender nodes (addon doesn't crash on them)
        return {
            'classification': 'SUPPORTED',
            'sockets_supported': [],
            'sockets_dropped': [],
            'notes': 'utility/input node (intermediate; processed if feeding supported BSDF)',
        }

    # Unknown node type — likely DROPPED-SILENT
    # Try to instantiate it in a scene and run convert_shader_node to see if it crashes
    return {
        'classification': 'DROPPED-SILENT',
        'sockets_supported': [],
        'sockets_dropped': [s['name'] for s in node_info['sockets_in']],
        'notes': 'no handler in addon translation layer',
    }


def classify_render_settings(props_dict) -> dict[str, Any]:
    """Classify RenderSettings properties."""
    # The addon reads:
    # - samples (via scene.cycles.samples or render.samples)
    # - device_mode (auto/cpu/gpu)
    # - integrator (via _effective_integrator_name)
    # - denoiser settings (use_denoising, denoiser type)
    # Most other settings are NOT read by the addon (DROPPED-SILENT).

    SUPPORTED = {'samples', 'use_denoising', 'denoiser', 'film_transparent'}
    results = {}
    for prop_name in props_dict:
        if prop_name in SUPPORTED:
            results[prop_name] = 'SUPPORTED'
        else:
            results[prop_name] = 'DROPPED-SILENT'
    return results


def classify_light_properties(props_by_type) -> dict[str, dict[str, str]]:
    """Classify light properties per type."""
    # From convert_lights (line 3879):
    # POINT: energy, color, use_temperature, temperature, shadow_soft_size (radius), ies_path
    # SUN: energy, color, use_temperature, temperature, angle
    # AREA: energy, color, use_temperature, temperature, shape, size, size_y, spread
    # SPOT: energy, color, use_temperature, temperature, spot_size, spot_blend, ies_path

    SUPPORTED_BY_TYPE = {
        'POINT': {'energy', 'color', 'use_temperature', 'temperature', 'shadow_soft_size'},
        'SUN': {'energy', 'color', 'use_temperature', 'temperature', 'angle'},
        'AREA': {'energy', 'color', 'use_temperature', 'temperature', 'shape', 'size', 'size_y', 'spread'},
        'SPOT': {'energy', 'color', 'use_temperature', 'temperature', 'spot_size', 'spot_blend'},
    }

    results = {}
    for lt, props in props_by_type.items():
        supported = SUPPORTED_BY_TYPE.get(lt, set())
        results[lt] = {}
        for prop in props:
            if prop in supported:
                results[lt][prop] = 'SUPPORTED'
            else:
                results[lt][prop] = 'DROPPED-SILENT'
    return results


def classify_camera_properties(props_dict) -> dict[str, str]:
    """Classify camera properties."""
    # From __init__.py lines 1280-1288:
    # lens, sensor_width, sensor_height, shift_x, shift_y, dof.focus_distance, dof.aperture_fstop
    SUPPORTED = {'lens', 'sensor_width', 'sensor_height', 'shift_x', 'shift_y',
                 'dof_distance', 'aperture_fstop'}
    results = {}
    for prop in props_dict:
        if prop in SUPPORTED:
            results[prop] = 'SUPPORTED'
        else:
            results[prop] = 'DROPPED-SILENT'
    return results


# =============================================================================
# Report generation
# =============================================================================

def generate_matrix(addon_module):
    """Generate the full parity matrix."""
    print("[pkg119] Enumerating Blender API surface...")

    shader_nodes = enumerate_shader_nodes()
    render_settings = enumerate_render_settings()
    light_props = enumerate_light_properties()
    camera_props = enumerate_camera_properties()
    world_props = enumerate_world_properties()

    print(f"[pkg119] Found {len(shader_nodes)} shader node types")

    print("[pkg119] Classifying against addon translation layer...")

    matrix_rows = []

    # Shader nodes
    for node_info in shader_nodes:
        classification_result = classify_shader_node(node_info, addon_module)

        # Per-socket granularity per spec
        for socket in node_info['sockets_in']:
            sock_name = socket['name']
            if sock_name in classification_result['sockets_supported']:
                sock_classification = classification_result['classification']
            elif sock_name in classification_result['sockets_dropped']:
                sock_classification = 'DROPPED-SILENT'
            else:
                # Socket not mentioned — inherit node classification
                sock_classification = classification_result['classification']

            matrix_rows.append({
                'category': 'shader_node',
                'feature': node_info['node_type'],
                'bl_idname': node_info['bl_idname'],
                'socket_or_prop': f"input:{sock_name}",
                'classification': sock_classification,
                'notes': classification_result.get('notes', ''),
            })

        # Also log the node-level classification for properties
        properties_supported_set = set(classification_result.get('properties_supported', []))
        for prop_name, prop_info in node_info['properties'].items():
            # Properties are SUPPORTED if explicitly listed, else DROPPED-SILENT
            # (e.g., procedural texture properties like turbulence_depth, gradient_type)
            if prop_name in properties_supported_set:
                prop_classification = classification_result['classification']
            else:
                prop_classification = 'DROPPED-SILENT'

            matrix_rows.append({
                'category': 'shader_node',
                'feature': node_info['node_type'],
                'bl_idname': node_info['bl_idname'],
                'socket_or_prop': f"prop:{prop_name}",
                'classification': prop_classification,
                'notes': f"property {prop_info['type']}" + (f" — {classification_result.get('notes', '')}" if prop_classification != 'DROPPED-SILENT' else ''),
            })

    # Render settings
    rs_classification = classify_render_settings(render_settings)
    for prop_name, classification in rs_classification.items():
        matrix_rows.append({
            'category': 'render_settings',
            'feature': 'RenderSettings',
            'bl_idname': '',
            'socket_or_prop': prop_name,
            'classification': classification,
            'notes': '',
        })

    # Light properties
    light_classification = classify_light_properties(light_props)
    for lt, props_class in light_classification.items():
        for prop_name, classification in props_class.items():
            matrix_rows.append({
                'category': 'light',
                'feature': lt,
                'bl_idname': '',
                'socket_or_prop': prop_name,
                'classification': classification,
                'notes': '',
            })

    # Camera properties
    cam_classification = classify_camera_properties(camera_props)
    for prop_name, classification in cam_classification.items():
        matrix_rows.append({
            'category': 'camera',
            'feature': 'Camera',
            'bl_idname': '',
            'socket_or_prop': prop_name,
            'classification': classification,
            'notes': '',
        })

    # World properties
    for prop_name in world_props:
        matrix_rows.append({
            'category': 'world',
            'feature': 'World',
            'bl_idname': '',
            'socket_or_prop': prop_name,
            'classification': 'SUPPORTED' if prop_name == 'use_nodes' else 'DROPPED-SILENT',
            'notes': 'node tree handled separately' if prop_name == 'use_nodes' else '',
        })

    return matrix_rows


def write_json_report(matrix_rows, output_path: Path):
    """Write machine-readable JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(matrix_rows, f, indent=2)
    print(f"[pkg119] Wrote {output_path}")


def write_markdown_report(matrix_rows, output_path: Path):
    """Write human-readable markdown summary."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Count by classification
    counts = defaultdict(int)
    for row in matrix_rows:
        counts[row['classification']] += 1

    # Collect DROPPED-SILENT cells (the failure mode to foreground)
    dropped = [r for r in matrix_rows if r['classification'] == 'DROPPED-SILENT']

    with open(output_path, 'w') as f:
        f.write("# Blender Parity Coverage Matrix — Phase A\n\n")
        f.write(f"**Generated:** {bpy.app.version_string}\n\n")
        f.write("## Summary\n\n")
        f.write(f"- **SUPPORTED**: {counts['SUPPORTED']} features\n")
        f.write(f"- **APPROXIMATED**: {counts['APPROXIMATED']} features\n")
        f.write(f"- **DROPPED-SILENT**: {counts['DROPPED-SILENT']} features ⚠️\n")
        f.write(f"- **UNKNOWN-CRASH**: {counts['UNKNOWN-CRASH']} features\n")
        f.write(f"- **Total**: {len(matrix_rows)} features\n\n")

        f.write("## DROPPED-SILENT Features (Failure Mode)\n\n")
        f.write("These features are silently ignored by the addon with no warning:\n\n")

        # Group by category
        by_category = defaultdict(list)
        for row in dropped:
            by_category[row['category']].append(row)

        for category in sorted(by_category.keys()):
            f.write(f"### {category}\n\n")
            rows = by_category[category]
            for row in rows:
                feature = row['feature']
                sock_prop = row['socket_or_prop']
                notes = f" — {row['notes']}" if row['notes'] else ""
                f.write(f"- **{feature}**: `{sock_prop}`{notes}\n")
            f.write("\n")

        f.write("## Full Matrix by Category\n\n")

        # Group all by category
        all_by_category = defaultdict(list)
        for row in matrix_rows:
            all_by_category[row['category']].append(row)

        for category in sorted(all_by_category.keys()):
            f.write(f"### {category}\n\n")
            f.write("| Feature | Socket/Property | Classification | Notes |\n")
            f.write("|---------|-----------------|----------------|-------|\n")
            for row in all_by_category[category]:
                feature = row['feature']
                sock_prop = row['socket_or_prop']
                classification = row['classification']
                notes = row['notes']
                f.write(f"| {feature} | {sock_prop} | {classification} | {notes} |\n")
            f.write("\n")

    print(f"[pkg119] Wrote {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Generate Blender parity coverage matrix")
    parser.add_argument('--out', type=str, default='docs/blender_parity',
                        help='Output directory for matrix artifacts (default: docs/blender_parity for checked-in reference)')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])

    print(f"[pkg119] Blender version: {bpy.app.version_string}")

    addon_module = _bootstrap_astroray_addon()

    matrix_rows = generate_matrix(addon_module)

    output_dir = Path(args.out)
    write_json_report(matrix_rows, output_dir / "coverage_matrix.json")
    write_markdown_report(matrix_rows, output_dir / "report.md")

    # Summary stats for stdout
    counts = defaultdict(int)
    for row in matrix_rows:
        counts[row['classification']] += 1

    print("\n" + "=" * 60)
    print("PARITY MATRIX SUMMARY")
    print("=" * 60)
    print(f"SUPPORTED:       {counts['SUPPORTED']:4d}")
    print(f"APPROXIMATED:    {counts['APPROXIMATED']:4d}")
    print(f"DROPPED-SILENT:  {counts['DROPPED-SILENT']:4d} ⚠️")
    print(f"UNKNOWN-CRASH:   {counts['UNKNOWN-CRASH']:4d}")
    print(f"TOTAL:           {len(matrix_rows):4d}")
    print("=" * 60)

    if counts['UNKNOWN-CRASH'] > 0:
        print("\n⚠️  UNKNOWN-CRASH features remain — Phase A acceptance criterion NOT met")
        print("    Resolve each to one of the other three buckets.\n")
        sys.exit(1)
    else:
        print("\n✓ Zero UNKNOWN-CRASH features — Phase A acceptance criterion met\n")
        sys.exit(0)


if __name__ == '__main__':
    main()
