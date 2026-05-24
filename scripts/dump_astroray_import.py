#!/usr/bin/env python3
"""Dump what Astroray actually imports from the Classroom .blend file."""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Ensure astroray is importable
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "build_cuda" / "Release"))

BLEND = ROOT / "benchmarks" / "cycles-parity" / "scenes" / "cache" / "classroom" / "000_classroom.blend"
OUTPUT = ROOT / "test_results" / "pkg76-classroom-astroray-import.json"

def main():
    import astroray

    print(f"Importing {BLEND}...")
    scene_data = astroray.import_blend(str(BLEND))

    # Extract what was imported
    metadata = {
        "camera": None,
        "world": None,
        "materials": [],
        "lights": [],
        "meshes": [],
    }

    # Camera
    if hasattr(scene_data, 'camera_transform'):
        metadata["camera"] = {
            "fov": getattr(scene_data, 'camera_fov', None),
            "transform": str(getattr(scene_data, 'camera_transform', None)),
        }

    # World/background
    if hasattr(scene_data, 'world_color'):
        metadata["world"] = {
            "color": list(getattr(scene_data, 'world_color', [0, 0, 0])),
        }

    # Materials
    if hasattr(scene_data, 'materials'):
        for i, mat in enumerate(scene_data.materials):
            mat_info = {
                "index": i,
                "name": getattr(mat, 'name', f"mat_{i}"),
            }
            # Check what properties are available
            for attr in dir(mat):
                if not attr.startswith('_'):
                    val = getattr(mat, attr)
                    if not callable(val):
                        mat_info[attr] = str(val) if not isinstance(val, (int, float, bool, type(None))) else val
            metadata["materials"].append(mat_info)

    # Lights
    if hasattr(scene_data, 'lights'):
        for i, light in enumerate(scene_data.lights):
            light_info = {
                "index": i,
                "name": getattr(light, 'name', f"light_{i}"),
            }
            # Check what properties are available
            for attr in dir(light):
                if not attr.startswith('_'):
                    val = getattr(light, attr)
                    if not callable(val):
                        light_info[attr] = str(val) if not isinstance(val, (int, float, bool, type(None))) else val
            metadata["lights"].append(light_info)

    # Meshes
    if hasattr(scene_data, 'meshes'):
        for i, mesh in enumerate(scene_data.meshes):
            mesh_info = {
                "index": i,
                "name": getattr(mesh, 'name', f"mesh_{i}"),
                "vertex_count": len(getattr(mesh, 'vertices', [])) if hasattr(mesh, 'vertices') else 0,
            }
            metadata["meshes"].append(mesh_info)

    # Save
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, 'w') as f:
        json.dump(metadata, f, indent=2)

    # Print summary
    print()
    print("=== Astroray Import Summary ===")
    print(f"Camera: {metadata['camera']}")
    print(f"World: {metadata['world']}")
    print(f"Materials: {len(metadata['materials'])} imported")
    if metadata['materials']:
        print(f"  Sample material 0: {metadata['materials'][0]}")
    print(f"Lights: {len(metadata['lights'])} imported")
    for light in metadata['lights']:
        print(f"  {light.get('name', light.get('index'))}: {light}")
    print(f"Meshes: {len(metadata['meshes'])} imported")
    print()
    print(f"Full dump saved to: {OUTPUT}")


if __name__ == "__main__":
    main()
