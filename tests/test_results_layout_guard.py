"""Guard for the test_results layout (.astroray_plan/docs/test-results-conventions.md).

Pure Python (no astroray, no GPU, no rendering): checks the tracked curated
tree, that no code builds a test_results path outside results_layout, that
results_path validates and stays under _runs/, and that index.html is fresh.
"""

from __future__ import annotations

import ast
import re
import struct
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import results_layout as rl  # noqa: E402

ROOT = rl.ROOT
REGEN = "python tests/results_layout.py index"

# Code allowed to spell "test_results": the layout module itself, the temp-dir
# scratch in runtime_setup, this guard, and the product-code material preview
# (blender_addon writes a cwd-relative preview; product code, follow-up filed).
ALLOW_LITERAL_FILES = {
    "tests/results_layout.py",
    "tests/runtime_setup.py",
    "tests/test_results_layout_guard.py",
}
ALLOW_LITERAL_LINES = {("blender_addon/__init__.py", "test_results")}
SCAN_DIRS = ("tests", "scripts", "benchmarks", "blender_addon")
_PATHLIKE = re.compile(r"^(?:[^\s]*[/\\])?test_results(?:[/\\][^\s]*)?$")


def _tracked():
    try:
        out = subprocess.run(["git", "ls-files", "test_results"], cwd=ROOT, text=True,
                             capture_output=True, timeout=60, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        pytest.skip("git not available")
    return [p for p in out.splitlines() if p]


def _png_width(path: Path) -> int:
    head = path.read_bytes()[:24]
    return struct.unpack(">I", head[16:20])[0] if head[:8] == b"\x89PNG\r\n\x1a\n" else 0


def curated_violations(paths, root: Path = ROOT):
    bad = []
    for rel in paths:
        parts = rel.split("/")[1:]  # drop leading test_results
        if len(parts) == 1:
            if parts[0] not in ("index.html", "README.md"):
                bad.append(f"{rel}: only index.html/README.md allowed at top level")
            continue
        if len(parts) != 3:
            bad.append(f"{rel}: expected test_results/<area>/<feature>/<artifact>")
            continue
        area, feature, name = parts
        if area not in rl.AREAS:
            bad.append(f"{rel}: unknown area {area!r}")
        if not rl.FEATURE_RE.match(feature):
            bad.append(f"{rel}: feature slug {feature!r} must match {rl.FEATURE_RE.pattern}")
        for label, comp in (("feature", feature), ("artifact", name)):
            tok = rl.banned_token(comp)
            if tok:
                bad.append(f"{rel}: banned token {tok!r} in {label}")
        suffix = Path(name).suffix.lower()
        if name != "README.md":
            if not rl.NAME_RE.match(name):
                bad.append(f"{rel}: artifact name must match {rl.NAME_RE.pattern}")
            if suffix not in rl.CURATED_EXTS:
                bad.append(f"{rel}: extension {suffix!r} not allowed (png svg json csv blend, README.md)")
        f = root / rel
        if f.is_file():
            size = f.stat().st_size
            if suffix == ".blend" and size > rl.MAX_BLEND_BYTES:
                bad.append(f"{rel}: .blend {size} B > {rl.MAX_BLEND_BYTES}")
            elif suffix != ".blend" and size > rl.MAX_IMAGE_BYTES:
                bad.append(f"{rel}: {size} B > {rl.MAX_IMAGE_BYTES}")
            if suffix == ".png" and _png_width(f) > rl.MAX_IMAGE_WIDTH:
                bad.append(f"{rel}: PNG wider than {rl.MAX_IMAGE_WIDTH} px")
            if name == "README.md" and len(f.read_text(encoding="utf-8").splitlines()) > 15:
                bad.append(f"{rel}: README longer than 15 lines")
    return bad


def test_tracked_test_results_conform():
    bad = curated_violations(_tracked())
    assert not bad, "test_results layout violations:\n  " + "\n  ".join(bad)


def _literal_hits(root: Path = ROOT):
    hits = []
    for d in SCAN_DIRS:
        base = root / d
        if not base.is_dir():
            continue
        for py in base.rglob("*.py"):
            rel = py.relative_to(root).as_posix()
            if rel in ALLOW_LITERAL_FILES:
                continue
            try:
                tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                        and _PATHLIKE.match(node.value)
                        and (rel, node.value) not in ALLOW_LITERAL_LINES):
                    hits.append(f"{rel}:{node.lineno}: {node.value!r}")
    return hits


def test_no_direct_test_results_paths_in_code():
    hits = _literal_hits()
    assert not hits, ("build output paths with tests/results_layout.results_path(area, feature, name), "
                      "not a test_results literal:\n  " + "\n  ".join(hits))


def _source_files(root: Path = ROOT):
    for d in SCAN_DIRS:
        base = root / d
        if base.is_dir():
            for py in base.rglob("*.py"):
                if py.relative_to(root).as_posix() not in ALLOW_LITERAL_FILES:
                    yield py, ast.parse(py.read_text(encoding="utf-8", errors="replace"))


def _static_arg_violations(root: Path = ROOT):
    """Validate literal arguments of results_path/results_dir calls and
    module-level `_AREA, _FEATURE = "area", "feature"` constants."""
    bad = []
    for py, tree in _source_files(root):
        rel = py.relative_to(root).as_posix()
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) in (
                    "results_path", "results_dir"):
                for i, a in enumerate(n.args[:3]):
                    parts = ([a.value] if isinstance(a, ast.Constant) and isinstance(a.value, str) else
                             [p.value for p in a.values if isinstance(p, ast.Constant)]
                             if isinstance(a, ast.JoinedStr) else [])
                    for v in parts:
                        tok = rl.banned_token(v)
                        if tok:
                            bad.append(f"{rel}:{n.lineno}: banned token {tok!r} in {v!r}")
                    if isinstance(a, ast.Constant) and isinstance(a.value, str):
                        if i == 0 and a.value not in rl.AREAS:
                            bad.append(f"{rel}:{n.lineno}: unknown area {a.value!r}")
                        if i == 1 and not rl.FEATURE_RE.match(a.value):
                            bad.append(f"{rel}:{n.lineno}: bad feature slug {a.value!r}")
                        if i == 2 and not rl.NAME_RE.match(a.value):
                            bad.append(f"{rel}:{n.lineno}: bad artifact name {a.value!r}")
            if (isinstance(n, ast.Assign) and isinstance(n.value, ast.Tuple) and len(n.targets) == 1
                    and isinstance(n.targets[0], ast.Tuple)
                    and [getattr(t, "id", "") for t in n.targets[0].elts] == ["_AREA", "_FEATURE"]):
                area, feat = (getattr(e, "value", "") for e in n.value.elts)
                if area not in rl.AREAS or not rl.FEATURE_RE.match(feat) or rl.banned_token(feat):
                    bad.append(f"{rel}:{n.lineno}: bad _AREA/_FEATURE {area!r}, {feat!r}")
    return bad


def test_literal_results_path_arguments_are_valid():
    bad = _static_arg_violations()
    assert not bad, "invalid results_path arguments:\n  " + "\n  ".join(bad)


@pytest.fixture
def layout_root(tmp_path, monkeypatch):
    monkeypatch.setattr(rl, "RESULTS", tmp_path)
    return tmp_path


def test_results_path_resolves_under_runs(layout_root):
    p = rl.results_path("materials", "principled-alpha-shadow", "alpha_gpu_sheet.png")
    assert p == layout_root / "_runs" / "materials" / "principled-alpha-shadow" / "alpha_gpu_sheet.png"
    assert p.parent.is_dir()
    assert rl.results_dir("volumes", "hetero-smoke-grid", create=False) == \
        layout_root / "_runs" / "volumes" / "hetero-smoke-grid"


@pytest.mark.parametrize("area,feature,name", [
    ("nonsense", "good-feature", "a.png"),                 # unknown area
    ("materials", "Bad_Feature", "a.png"),                 # slug chars
    ("materials", "ab", "a.png"),                          # too short
    ("materials", "../escape", "a.png"),                   # traversal
    ("materials", "good-feature", "../a.png"),             # traversal in name
    ("materials", "good-feature", "Has-Caps.png"),         # name regex
    ("materials", "good-feature", "noext"),
    ("materials", "batch-k-volumes", "a.png"),             # banned tokens
    ("materials", "lane-work", "a.png"),
    ("materials", "hotfix-glass", "a.png"),
    ("materials", "storm-commit", "a.png"),
    ("materials", "round-trip", "a.png"),
    ("materials", "session-notes", "a.png"),
    ("materials", "glass-2026-09-19", "a.png"),
    ("materials", "pkg268-cube", "a.png"),
    ("materials", "issue818-checker", "a.png"),
    ("materials", "good-feature", "pkg253_alpha.png"),
    ("materials", "good-feature", "issue799_shadow.png"),
    ("materials", "good-feature", "lead_sheet.png"),
])
def test_results_path_rejects_bad_input(layout_root, area, feature, name):
    with pytest.raises(ValueError):
        rl.results_path(area, feature, name)
    assert not (layout_root / "_runs").exists() or not any((layout_root / "_runs").rglob("*.png"))


def test_areas_match_conventions_doc():
    doc = (ROOT / ".astroray_plan" / "docs" / "test-results-conventions.md").read_text(encoding="utf-8")
    documented = tuple(re.findall(r"^\| `([a-z-]+)` \|", doc, re.M))
    assert documented == rl.AREAS


def test_index_html_is_fresh():
    idx = ROOT / "test_results" / "index.html"
    assert idx.is_file(), f"test_results/index.html missing; regenerate with: {REGEN}"
    fresh = rl.render_index(rl.RESULTS)
    have = idx.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert have == fresh, f"test_results/index.html is stale; regenerate with: {REGEN}"
