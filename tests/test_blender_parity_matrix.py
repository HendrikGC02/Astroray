# -*- coding: utf-8 -*-
"""pkg119 Phase A — pytest wrapper for Blender parity coverage-matrix generator.

Runs the headless-Blender introspection script and asserts zero UNKNOWN-CRASH
classifications (Phase A acceptance criterion). Skips cleanly when Blender is
absent.

Usage:
    pytest tests/test_blender_parity_matrix.py -v
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def _find_blender():
    """Locate Blender executable (env var override or default install path)."""
    blender_exe = os.environ.get('BLENDER_EXE', '')
    if blender_exe and Path(blender_exe).is_file():
        return Path(blender_exe)

    # Default install paths (Windows)
    candidates = [
        Path(r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"),
        Path(r"C:\Program Files\Blender Foundation\Blender 5.0\blender.exe"),
        Path(r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate

    return None


BLENDER_EXE = _find_blender()
SKIP_REASON = "Blender not found (set BLENDER_EXE or install at default path)"


@pytest.mark.skipif(BLENDER_EXE is None, reason=SKIP_REASON)
def test_blender_parity_matrix_generation():
    """Generate the parity matrix and assert zero UNKNOWN-CRASH classifications.

    Note: The checked-in reference copy is in docs/blender_parity/ (regenerate manually
    with `--out docs/blender_parity` when addon changes). This test uses test_results/
    for ephemeral test output."""
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "generate_blender_parity_matrix.py"
    output_dir = repo_root / "test_results" / "blender_parity"

    # Clean output dir for fresh run
    if output_dir.exists():
        shutil.rmtree(output_dir)

    # Set up environment
    env = os.environ.copy()
    # Point to canonical test build (OpenMP OFF per spec: "headless-Blender legs need -DASTRORAY_DISABLE_OPENMP=ON")
    # For Phase A we don't render, so OpenMP doesn't matter, but for consistency with future Phase B:
    # Try worktree build first, then main checkout (for worktree execution).
    # Ninja (single-config, 2026-08) emits the pyd at build_cuda/ root; legacy
    # multi-config builds used build_cuda/Release — accept whichever holds a pyd.
    def _pyd_dir(root):
        for cand in (root / "build_cuda", root / "build_cuda" / "Release"):
            if list(cand.glob("astroray*.pyd")):
                return cand
        return None

    build_dir = _pyd_dir(repo_root) or _pyd_dir(repo_root.parent / "Astroray")
    if build_dir is None:
        pytest.skip(f"No astroray pyd found under {repo_root} or {repo_root.parent / 'Astroray'}")

    env['ASTRORAY_PYD_DIR'] = str(build_dir)
    env['ASTRORAY_BUILD_DIR'] = str(repo_root / "build_cuda")

    # Run headless Blender
    cmd = [
        str(BLENDER_EXE),
        '--background',
        '--factory-startup',
        '--python', str(script),
        '--',
        '--out', str(output_dir),
    ]

    print(f"\n[test_blender_parity_matrix] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120)

    # Print output for debugging
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr, file=sys.stderr)

    # The script exits with code 0 if zero UNKNOWN-CRASH, else 1
    assert result.returncode == 0, \
        "Parity matrix generation failed or UNKNOWN-CRASH features remain (see output above)"

    # Verify artifacts exist
    json_path = output_dir / "coverage_matrix.json"
    md_path = output_dir / "report.md"

    assert json_path.is_file(), f"Expected JSON artifact at {json_path}"
    assert md_path.is_file(), f"Expected Markdown artifact at {md_path}"

    # Load JSON and verify structure
    with open(json_path) as f:
        matrix_rows = json.load(f)

    assert isinstance(matrix_rows, list), "Matrix should be a list of rows"
    assert len(matrix_rows) > 0, "Matrix should not be empty"

    # Verify each row has required fields
    for row in matrix_rows:
        assert 'category' in row
        assert 'feature' in row
        assert 'socket_or_prop' in row
        assert 'classification' in row
        assert row['classification'] in {'SUPPORTED', 'APPROXIMATED', 'DROPPED-SILENT', 'UNKNOWN-CRASH'}

    # Assert zero UNKNOWN-CRASH (Phase A acceptance criterion)
    unknown_crashes = [r for r in matrix_rows if r['classification'] == 'UNKNOWN-CRASH']
    assert len(unknown_crashes) == 0, \
        f"Phase A acceptance NOT met: {len(unknown_crashes)} UNKNOWN-CRASH features remain"

    # Print summary
    from collections import defaultdict
    counts = defaultdict(int)
    for row in matrix_rows:
        counts[row['classification']] += 1

    print("\n" + "=" * 60)
    print("PARITY MATRIX ACCEPTANCE")
    print("=" * 60)
    print(f"SUPPORTED:       {counts['SUPPORTED']:4d}")
    print(f"APPROXIMATED:    {counts['APPROXIMATED']:4d}")
    print(f"DROPPED-SILENT:  {counts['DROPPED-SILENT']:4d}")
    print(f"UNKNOWN-CRASH:   {counts['UNKNOWN-CRASH']:4d}")
    print(f"TOTAL:           {len(matrix_rows):4d}")
    print("=" * 60)
    print(f"[OK] Matrix generated: {len(matrix_rows)} features classified")
    print(f"[OK] Zero UNKNOWN-CRASH features (Phase A acceptance met)")
    print(f"[OK] Artifacts: {json_path}, {md_path}")
    print("=" * 60 + "\n")


if __name__ == '__main__':
    # Allow running standalone: pytest tests/test_blender_parity_matrix.py
    pytest.main([__file__, '-v'])
