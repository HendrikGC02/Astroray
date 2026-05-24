#!/usr/bin/env python3
"""Dump Classroom .blend scene metadata to understand what Cycles parses.

This script extracts materials, lights, world settings, and camera parameters
to help identify the import fidelity gaps.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH_ROOT = ROOT / "benchmarks" / "cycles-parity"
SCENE_ROOT = BENCH_ROOT / "scenes"
CACHE = SCENE_ROOT / "cache" / "classroom"
BLEND = CACHE / "000_classroom.blend"


def dump_blend_metadata(blend_path: Path, output_json: Path):
    """Use Blender Python to dump scene metadata to JSON."""
    script = f"""
import bpy
import json

# Gather metadata
metadata = {{
    "camera": {{}},
    "world": {{}},
    "materials": [],
    "lights": [],
    "meshes": [],
}}

# Camera
if bpy.context.scene.camera:
    cam = bpy.context.scene.camera
    cam_data = cam.data
    metadata["camera"] = {{
        "name": cam.name,
        "type": cam_data.type,
        "lens": cam_data.lens,
        "sensor_width": cam_data.sensor_width,
        "sensor_height": cam_data.sensor_height,
        "location": list(cam.location),
        "rotation_euler": list(cam.rotation_euler),
    }}

# World
world = bpy.context.scene.world
if world:
    metadata["world"] = {{
        "name": world.name,
        "use_nodes": world.use_nodes,
    }}
    if world.use_nodes and world.node_tree:
        # Try to find background shader
        for node in world.node_tree.nodes:
            if node.type == 'BACKGROUND':
                metadata["world"]["background_node"] = {{
                    "color": list(node.inputs['Color'].default_value[:3]),
                    "strength": node.inputs['Strength'].default_value,
                }}
                break
        # Check if there's an environment texture
        for node in world.node_tree.nodes:
            if node.type == 'TEX_ENVIRONMENT':
                metadata["world"]["environment_texture"] = {{
                    "image": node.image.filepath if node.image else None,
                }}
                break
    else:
        # Legacy world color
        if hasattr(world, 'color'):
            metadata["world"]["color"] = list(world.color)

# Materials
for mat in bpy.data.materials:
    mat_info = {{
        "name": mat.name,
        "use_nodes": mat.use_nodes,
    }}
    if mat.use_nodes and mat.node_tree:
        # Find Principled BSDF
        for node in mat.node_tree.nodes:
            if node.type == 'BSDF_PRINCIPLED':
                mat_info["principled_bsdf"] = {{
                    "base_color": list(node.inputs['Base Color'].default_value[:3]),
                    "metallic": node.inputs['Metallic'].default_value,
                    "roughness": node.inputs['Roughness'].default_value,
                }}
                # Check for IOR
                if 'IOR' in node.inputs:
                    mat_info["principled_bsdf"]["ior"] = node.inputs['IOR'].default_value
                # Check for transmission
                if 'Transmission' in node.inputs:
                    mat_info["principled_bsdf"]["transmission"] = node.inputs['Transmission'].default_value
                # Check for specular
                if 'Specular' in node.inputs:
                    mat_info["principled_bsdf"]["specular"] = node.inputs['Specular'].default_value
                break
        # Check for image textures
        image_textures = []
        for node in mat.node_tree.nodes:
            if node.type == 'TEX_IMAGE' and node.image:
                image_textures.append({{
                    "image": node.image.filepath,
                    "connected_to": [link.to_socket.name for link in node.outputs[0].links],
                }})
        if image_textures:
            mat_info["image_textures"] = image_textures
    metadata["materials"].append(mat_info)

# Lights
for light_obj in bpy.data.objects:
    if light_obj.type == 'LIGHT':
        light_data = light_obj.data
        metadata["lights"].append({{
            "name": light_obj.name,
            "type": light_data.type,
            "energy": light_data.energy,
            "color": list(light_data.color),
            "location": list(light_obj.location),
        }})

# Meshes (counts only, not full geometry)
for mesh_obj in bpy.data.objects:
    if mesh_obj.type == 'MESH':
        mesh_data = mesh_obj.data
        metadata["meshes"].append({{
            "name": mesh_obj.name,
            "vertex_count": len(mesh_data.vertices),
            "polygon_count": len(mesh_data.polygons),
        }})

# Save to JSON
with open(r'{str(output_json)}', 'w') as f:
    json.dump(metadata, f, indent=2)
"""

    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as script_file:
        script_file.write(script)
        script_path = script_file.name

    try:
        blender = "blender"
        cmd = [blender, "-b", str(blend_path), "-P", script_path]
        print(f"Running Blender metadata dump: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            print(f"STDERR: {result.stderr}")
            raise RuntimeError(f"Blender dump failed with exit code {result.returncode}")
        print(f"Metadata dumped to {output_json}")
    finally:
        import os
        os.unlink(script_path)


def main():
    test_results = ROOT / "test_results"
    test_results.mkdir(parents=True, exist_ok=True)

    output_json = test_results / "pkg76-classroom-blend-metadata.json"

    print(f"Dumping metadata from: {BLEND}")
    dump_blend_metadata(BLEND, output_json)

    # Print summary
    with open(output_json) as f:
        metadata = json.load(f)

    print()
    print("=== Classroom .blend Metadata Summary ===")
    print(f"Camera: {metadata['camera']['name']} (lens={metadata['camera']['lens']}mm)")
    print(f"World: use_nodes={metadata['world']['use_nodes']}")
    if 'background_node' in metadata['world']:
        bg = metadata['world']['background_node']
        print(f"  Background: color={bg['color']}, strength={bg['strength']}")
    print(f"Materials: {len(metadata['materials'])} total")
    principled_count = sum(1 for m in metadata['materials'] if 'principled_bsdf' in m)
    print(f"  {principled_count} with Principled BSDF")
    print(f"Lights: {len(metadata['lights'])} total")
    for light in metadata['lights']:
        print(f"  {light['name']}: {light['type']}, energy={light['energy']}")
    print(f"Meshes: {len(metadata['meshes'])} total")
    total_verts = sum(m['vertex_count'] for m in metadata['meshes'])
    total_polys = sum(m['polygon_count'] for m in metadata['meshes'])
    print(f"  Total vertices: {total_verts}")
    print(f"  Total polygons: {total_polys}")
    print()
    print(f"Full metadata saved to: {output_json}")


if __name__ == "__main__":
    main()
