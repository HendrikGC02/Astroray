#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Map changed source files -> impacted test files (differential selection).

pytest-testmon does NOT work here: it fingerprints Python bytecode and is blind
to changes inside the compiled astroray.pyd (native .cu/.cuh/.cpp/.h). This
script fills that gap with an explicit, maintainable src-path -> test-file map
(open-model-research-2026-08 latency lever 6).

It is a *fix-loop accelerator*, not a merge gate. Native changes rebuild the
whole .pyd, so a change to a widely-included core header intentionally falls
back to "all GPU tests". The full split suite (scripts/test/run_split.py) is
still what runs at closeout.

Usage:
    python scripts/test/select_impacted.py --base origin/main      # diff vs a ref
    python scripts/test/select_impacted.py --changed src/gpu/photon_emission.cu ...
    git diff --name-only HEAD | python scripts/test/select_impacted.py --stdin

    # pipe straight into the split runner:
    python scripts/test/run_split.py -- $(python scripts/test/select_impacted.py --base origin/main)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = REPO_ROOT / "tests"

# Native headers so widely included that a change can perturb almost any
# native-backed test. A hit here selects the whole GPU suite (the safe superset).
CORE_WILDCARD_FILES = {
    "raytracer.h", "gpu_renderer.h", "gpu_types.h", "gpu_materials.h",
    "cuda_renderer.cu", "integrator.h", "gpu_scene_upload.h", "spectrum.h",
    "material.h", "material_closure.h", "scene.h",
}

# topic token -> substrings that select a test file when found in its name.
# Deliberately broad: over-selecting a few extra fast tests is cheap; missing
# an impacted test wastes a fix-loop cycle. Keep alphabetized by key.
KEYWORD_MAP: dict[str, tuple[str, ...]] = {
    "accretion":   ("accretion", "adaf", "slim_disk", "emission"),
    "caustic":     ("caustic", "photon", "sms", "prism", "glass"),
    "closure":     ("closure", "material", "disney", "metal", "spectral", "bsdf"),
    "cryptomatte": ("cryptomatte",),
    "denois":      ("denois", "oidn", "optix"),
    "dispersion":  ("dispersion", "sellmeier", "prism", "spectral", "ior"),
    "emission":    ("emission", "synchrotron", "accretion", "spectral"),
    "energy":      ("energy", "furnace", "metal", "compensation"),
    "envmap":      ("envmap", "hdri", "world", "environment"),
    "firefly":     ("firefly", "clamp"),
    "ggx":         ("ggx", "metal", "disney", "roughness", "furnace"),
    "glass":       ("glass", "dielectric", "refract", "caustic", "furnace"),
    "integrator":  ("integrator", "default_integrator", "path_trace", "restir"),
    "light":       ("light", "restir", "nee", "area_light", "distant"),
    "light_tree":  ("light_tree", "light_sampler", "restir", "nee"),
    "material":    ("material", "closure", "disney", "metal", "spectral", "texture"),
    "mnee":        ("mnee", "caustic", "sms"),
    "motion":      ("motion_blur", "tlas", "deform"),
    "photon":      ("photon", "caustic", "sms"),
    "restir":      ("restir",),
    "spectral":    ("spectral", "spectrum", "dispersion", "profile", "upsample", "colorspace"),
    "spectrum":    ("spectral", "spectrum", "upsample", "colorspace"),
    "subsurface":  ("subsurface",),
    "texture":     ("texture", "procedural", "noise", "voronoi", "wave_brick"),
    "tlas":        ("tlas", "instanc", "refit", "blas", "bulk"),
    "wavefront":   ("wavefront", "pkg55", "megakernel", "gpu"),
}


def _changed_from_git(base: str) -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", base], cwd=str(REPO_ROOT),
        capture_output=True, text=True,
    )
    return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]


def _all_test_files() -> list[str]:
    return sorted(
        str(p.relative_to(REPO_ROOT)).replace("\\", "/")
        for p in TESTS_DIR.rglob("test_*.py")
    )


def _tokens(stem: str) -> set[str]:
    return {t for t in stem.lower().replace("-", "_").split("_") if len(t) >= 3}


def select(changed: list[str]) -> tuple[set[str], bool]:
    """Return (impacted test relpaths, broad_fallback_triggered)."""
    all_tests = _all_test_files()
    test_by_name = {Path(t).name: t for t in all_tests}
    impacted: set[str] = set()
    broad = False

    for raw in changed:
        rel = raw.replace("\\", "/")
        p = Path(rel)
        name = p.name

        # A changed test file selects itself.
        if name.startswith("test_") and name.endswith(".py") and name in test_by_name:
            impacted.add(test_by_name[name])
            continue

        # Blender addon Python -> the addon/blender test families.
        if rel.startswith("blender_addon/") and name.endswith(".py"):
            impacted.update(t for t in all_tests
                            if any(k in Path(t).name for k in ("blender", "addon", "blend_")))
            continue

        # Core widely-included native header/source -> whole GPU suite.
        if name in CORE_WILDCARD_FILES:
            broad = True
            continue

        # Native / plugin source -> map by topic tokens (filename + parent dir).
        if p.suffix in (".cu", ".cuh", ".cpp", ".cc", ".h", ".hpp", ".c"):
            toks = _tokens(p.stem) | _tokens(p.parent.name)
            substrings: set[str] = set()
            for key, subs in KEYWORD_MAP.items():
                if key in toks or any(key in t for t in toks):
                    substrings.update(subs)
            substrings.update(t for t in toks if len(t) >= 4)  # raw stem tokens too
            for t in all_tests:
                tn = Path(t).name.lower()
                if any(s in tn for s in substrings):
                    impacted.add(t)

    return impacted, broad


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", help="git ref to diff against (e.g. origin/main)")
    ap.add_argument("--changed", nargs="*", default=[], help="explicit changed file paths")
    ap.add_argument("--stdin", action="store_true", help="read changed paths from stdin (one per line)")
    args = ap.parse_args()

    changed = list(args.changed)
    if args.base:
        changed += _changed_from_git(args.base)
    if args.stdin:
        changed += [ln.strip() for ln in sys.stdin if ln.strip()]

    if not changed:
        print("select_impacted: no changed files given "
              "(use --base, --changed, or --stdin)", file=sys.stderr)
        return 2

    impacted, broad = select(changed)

    if broad:
        # Import lazily so this script stays usable without the tests package.
        sys.path.insert(0, str(TESTS_DIR))
        from _gpu_classification import classify_tree
        gpu_tests = {f"tests/{k}" for k, v in classify_tree(TESTS_DIR).items() if v == "gpu"}
        impacted |= gpu_tests
        print("select_impacted: core header changed -> adding full GPU suite",
              file=sys.stderr)

    for t in sorted(impacted):
        print(t)
    print(f"select_impacted: {len(impacted)} impacted test file(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
