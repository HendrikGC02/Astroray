#!/usr/bin/env python3
"""Quick test: verify that image texture loading works for Classroom materials."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from blend_import.reader import BlendFile
from blend_import.scene_builder import _ImportContext, _material_base_color

BLEND = ROOT / "benchmarks" / "cycles-parity" / "scenes" / "cache" / "classroom" / "000_classroom.blend"


class _FakeRenderer:
    """Stub renderer for testing the importer without GPU."""
    def __init__(self):
        self.materials = []

    def create_material(self, mat_type, rgb, params):
        mat_id = len(self.materials)
        self.materials.append({"type": mat_type, "rgb": rgb, "params": params})
        return mat_id


def main():
    print(f"Loading {BLEND}...")
    blend = BlendFile.from_path(BLEND)
    print(f"Blend file loaded. Path stored: {blend.path}")

    renderer = _FakeRenderer()
    ctx = _ImportContext(
        blend=blend,
        renderer=renderer,
        strict=False,
        on_warning=lambda m: print(f"  WARN: {m}"),
        material_ids={},
    )

    # Test all materials
    print()
    print("Testing material color extraction:")
    print("-" * 60)

    mat_blocks = blend.by_code.get("MA", [])
    print(f"Found {len(mat_blocks)} materials")

    for i, blk in enumerate(mat_blocks[:10]):  # Test first 10 materials
        rgb = _material_base_color(ctx, blk)
        print(f"Material {i:2d} (block {blk.old:x}) -> RGB {rgb}")

    print("-" * 60)
    print()
    print(f"Total materials in scene: {len(blend.by_code.get('MA', []))}")
    print("If RGB values are NOT all white/gray (e.g., [1.0, 1.0, 1.0]), texture loading worked!")


if __name__ == "__main__":
    main()
