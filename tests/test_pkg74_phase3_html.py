"""Phase 3 gate for pkg74 showcase HTML.

The generated index must be a single self-contained artifact with
collapsible sections, inlined plots/images, sortable stats tables, and
every scene from stats_summary.csv visible in the page.
"""
from __future__ import annotations

import csv
from html.parser import HTMLParser
from pathlib import Path

import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray  # noqa: F401
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")


class _SeenTags(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.add(tag)


def test_phase3_html_is_self_contained_and_lists_all_scenes(tmp_path: Path) -> None:
    from benchmarks.showcase import runner

    out_dir = runner.run(
        quick=True,
        output_root=tmp_path,
        resolution=32,
        samples=2,
        spp_series=[1, 4],
        max_depth=3,
        seed=0x74,
    )

    html_path = out_dir / "index.html"
    assert html_path.exists(), f"missing {html_path}"
    body = html_path.read_text(encoding="utf-8")

    parser = _SeenTags()
    parser.feed(body)
    assert {"html", "details", "table", "script", "img"}.issubset(parser.tags)

    assert "data:image/png;base64," in body
    assert "class=\"stat-table sortable\"" in body
    assert "Per-scene RMSE plots" in body

    with (out_dir / "stats_summary.csv").open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    expected_scenes = {row["scene"] for row in rows if row.get("scene")}
    assert expected_scenes, "stats_summary.csv did not contain scene names"
    for scene in expected_scenes:
        assert scene in body, f"scene {scene!r} missing from index.html"
