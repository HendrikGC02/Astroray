"""pkg74 showcase HTML index.

The index is intentionally self-contained: plots and contact sheets are
inlined as data URIs so the generated ``index.html`` can be opened from an
artifact zip without serving sibling image files.
"""

from __future__ import annotations

import argparse
import base64
import csv
import html
import io
import math
import re
import sys
from pathlib import Path

try:
    from . import stats
except ImportError:  # pragma: no cover - direct script execution
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    from benchmarks.showcase import stats


def _read_csv(csv_path: Path) -> tuple[list[str], list[list[str]]]:
    if not csv_path.exists():
        return [], []
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        return [], []
    header, *data = rows
    return header, data


def _cell(row: list[str], index: int) -> str:
    return row[index] if index < len(row) else ""


def _to_float(value: str) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _safe_id(label: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", label).strip("-").lower()
    return safe or "table"


def _image_data_uri(path: Path) -> str | None:
    if not path.exists():
        return None
    mime = "image/png"
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        mime = "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _render_table(header: list[str], data: list[list[str]],
                  columns: list[str], table_id: str) -> str:
    """Render a sortable sub-table for the given subset of columns."""
    if not header or not columns:
        return "<p><em>No data.</em></p>"
    indices = [header.index(c) for c in columns if c in header]
    if not indices:
        return "<p><em>No columns in this category.</em></p>"

    escaped_id = html.escape(table_id, quote=True)
    parts = [f'<table id="{escaped_id}" class="stat-table sortable">',
             "<thead><tr>"]
    for sort_col, source_index in enumerate(indices):
        label = html.escape(header[source_index])
        parts.append(
            "<th>"
            f'<button type="button" data-table="{escaped_id}" '
            f'data-column="{sort_col}" title="Sort by {label}">{label}</button>'
            "</th>")
    parts.append("</tr></thead><tbody>")
    for row in data:
        parts.append("<tr>")
        for source_index in indices:
            cell = _cell(row, source_index)
            parts.append(f"<td>{html.escape(str(cell))}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


def _category_sections(header: list[str], data: list[list[str]]) -> str:
    if not header:
        return "<p><em>stats_summary.csv not found or empty.</em></p>"

    buckets: dict[str, list[str]] = {}
    for col in header:
        cat = stats.column_category(col)
        buckets.setdefault(cat, []).append(col)

    canonical = ["meta", "geom", "mem", "time", "samp", "qual",
                 "spec", "gpu", "intstat"]
    extras = [c for c in buckets if c not in canonical]
    order = canonical + extras

    parts = []
    for cat in order:
        cols = buckets.get(cat, [])
        if not cols:
            continue
        label = stats.CATEGORY_LABELS.get(cat, cat)
        open_attr = " open" if cat == "meta" else ""
        table_id = f"stats-{_safe_id(cat)}"
        parts.append(
            f'<details{open_attr} class="stat-section">'
            f'<summary><strong>{html.escape(label)}</strong> '
            f'<span class="meta">({len(cols)} columns)</span></summary>'
            f'{_render_table(header, data, cols, table_id)}'
            f'</details>')
    return "\n".join(parts)


def _numeric_column(header: list[str], row: list[str], column: str) -> float | None:
    if column not in header:
        return None
    return _to_float(_cell(row, header.index(column)))


def _rmse_rows(header: list[str], data: list[list[str]]) -> dict[str, list[tuple[float, float, str]]]:
    if "scene" not in header:
        return {}
    scene_i = header.index("scene")
    label_i = header.index("integrator") if "integrator" in header else None

    grouped: dict[str, list[tuple[float, float, str]]] = {}
    for row in data:
        scene = _cell(row, scene_i)
        y = _numeric_column(header, row, "rmse_vs_in_run_reference")
        if y is None:
            y = _numeric_column(header, row, "qual_rmse_vs_reference")
        if y is None:
            continue
        x = _numeric_column(header, row, "samples_per_pixel")
        if x is None:
            x = _numeric_column(header, row, "samples")
        if x is None:
            x = float(len(grouped.get(scene, [])) + 1)
        label = _cell(row, label_i) if label_i is not None else scene
        grouped.setdefault(scene, []).append((x, y, label))
    return grouped


def _rmse_plot_data_uri(scene: str, points: list[tuple[float, float, str]]) -> str | None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return None

    ordered = sorted(points, key=lambda item: (item[2], item[0]))
    fig, ax = plt.subplots(figsize=(5.5, 3.0), dpi=130)
    by_label: dict[str, list[tuple[float, float]]] = {}
    for x, y, label in ordered:
        by_label.setdefault(label or scene, []).append((x, y))
    for label, series in by_label.items():
        xs = [x for x, _ in series]
        ys = [y for _, y in series]
        ax.plot(xs, ys, marker="o", linewidth=1.5, markersize=3.5, label=label)
    ax.set_title(scene)
    ax.set_xlabel("samples")
    ax.set_ylabel("RMSE")
    ax.grid(True, color="#d7dde8", linewidth=0.6)
    if len(by_label) > 1:
        ax.legend(fontsize=7)
    fig.tight_layout()
    png = io.BytesIO()
    fig.savefig(png, format="png")
    plt.close(fig)
    encoded = base64.b64encode(png.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _rmse_sections(header: list[str], data: list[list[str]]) -> str:
    grouped = _rmse_rows(header, data)
    if not grouped:
        return (
            '<details class="plot-section" open>'
            "<summary><strong>Per-scene RMSE plots</strong></summary>"
            "<p><em>No RMSE columns were produced for this run.</em></p>"
            "</details>")

    parts = [
        '<details class="plot-section" open>',
        f"<summary><strong>Per-scene RMSE plots</strong> "
        f'<span class="meta">({len(grouped)} scenes)</span></summary>',
        '<div class="plot-grid">',
    ]
    for scene in sorted(grouped):
        uri = _rmse_plot_data_uri(scene, grouped[scene])
        escaped_scene = html.escape(scene)
        if uri:
            parts.append(
                '<figure class="plot-card">'
                f'<img src="{uri}" alt="RMSE plot for {escaped_scene}">'
                f"<figcaption>{escaped_scene}</figcaption>"
                "</figure>")
        else:
            parts.append(
                '<div class="plot-card missing">'
                f"<strong>{escaped_scene}</strong>"
                "<p><em>matplotlib unavailable; plot not generated.</em></p>"
                "</div>")
    parts.append("</div></details>")
    return "\n".join(parts)


def _artefact_sections(output_dir: Path, artefacts: dict[str, str]) -> str:
    parts = ['<details class="gallery-section" open>',
             "<summary><strong>Run artefacts</strong></summary>",
             '<div class="gallery-grid">']
    for label, filename in artefacts.items():
        path = output_dir / filename
        uri = _image_data_uri(path)
        escaped_label = html.escape(label)
        escaped_filename = html.escape(filename)
        if uri:
            parts.append(
                '<figure class="artefact-card">'
                f'<img src="{uri}" alt="{escaped_label}" data-source="{escaped_filename}">'
                f"<figcaption><strong>{escaped_label}</strong><br>"
                f"<code>{escaped_filename}</code></figcaption>"
                "</figure>")
        else:
            parts.append(
                '<div class="artefact-card missing">'
                f"<strong>{escaped_label}</strong>"
                f"<p><code>{escaped_filename}</code> was not produced this run.</p>"
                "</div>")
    parts.append("</div></details>")
    return "\n".join(parts)


def _scene_filter(header: list[str], data: list[list[str]]) -> str:
    if "scene" not in header:
        return ""
    scene_i = header.index("scene")
    scenes = sorted({_cell(row, scene_i) for row in data if _cell(row, scene_i)})
    if not scenes:
        return ""
    items = "\n".join(
        f'<option value="{html.escape(scene)}">{html.escape(scene)}</option>'
        for scene in scenes)
    return (
        '<label class="scene-filter">Scene '
        '<select id="scene-filter" aria-label="Filter statistics by scene">'
        '<option value="">All scenes</option>'
        f"{items}"
        "</select></label>")


def _history_links(output_dir: Path) -> str:
    root = output_dir.parent
    if not root.exists():
        return ""
    runs: list[Path] = []
    for candidate in sorted(root.iterdir(), reverse=True):
        if candidate.is_dir() and (candidate / "stats_summary.csv").exists():
            runs.append(candidate)
    if len(runs) <= 1:
        return ""
    links = []
    for run in runs[:12]:
        rel = html.escape(str(Path("..") / run.name / "index.html"))
        label = html.escape(run.name)
        current = " <span class=\"meta\">current</span>" if run == output_dir else ""
        links.append(f'<li><a href="{rel}">{label}</a>{current}</li>')
    return (
        '<details class="history-section">'
        "<summary><strong>Run history</strong></summary>"
        f"<ol>{''.join(links)}</ol>"
        "</details>")


def _infer_metadata(output_dir: Path) -> tuple[str, str, str, dict[str, str]]:
    header, data = _read_csv(output_dir / "stats_summary.csv")
    first = data[0] if data else []

    def value(column: str, fallback: str) -> str:
        if column not in header:
            return fallback
        found = _cell(first, header.index(column))
        return found or fallback

    artefacts = {
        "Integrator timing": "integrator_compare_timing.png",
        "Integrator contact sheet": "integrator_compare_contact_sheet.png",
        "Convergence contact sheet": "convergence_grid_contact_sheet.png",
        "Convergence curve": "convergence_curve.png",
        "Material zoo contact sheet": "material_zoo_contact_sheet.png",
    }
    return (
        value("machine_id", "unknown-machine"),
        value("git_sha", "unknown"),
        value("timestamp_utc", output_dir.name),
        artefacts,
    )


def _stylesheet() -> str:
    return """
:root {
  color-scheme: light;
  --bg: #f7f7f4;
  --paper: #ffffff;
  --ink: #20242a;
  --muted: #667085;
  --line: #d8dee8;
  --accent: #2457a6;
  --accent-soft: #e8eef8;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: "Segoe UI", Arial, sans-serif;
  line-height: 1.45;
}
main {
  width: min(1180px, calc(100% - 32px));
  margin: 28px auto 48px;
}
header {
  border-bottom: 3px solid var(--accent);
  margin-bottom: 22px;
  padding-bottom: 14px;
}
h1 {
  font-family: Georgia, "Times New Roman", serif;
  font-size: 2.25rem;
  line-height: 1.1;
  margin: 0 0 10px;
}
h2 {
  font-family: Georgia, "Times New Roman", serif;
  font-size: 1.35rem;
  margin: 28px 0 10px;
}
.meta, figcaption, .scene-filter {
  color: var(--muted);
  font-size: 0.92rem;
}
code {
  background: #eef1f5;
  border: 1px solid #dde3ea;
  border-radius: 3px;
  padding: 0 0.25em;
}
details {
  background: var(--paper);
  border: 1px solid var(--line);
  margin: 12px 0;
  padding: 10px 12px;
}
summary {
  cursor: pointer;
  color: var(--accent);
}
details[open] > summary {
  margin-bottom: 10px;
}
.gallery-grid, .plot-grid {
  display: grid;
  gap: 14px;
  grid-template-columns: repeat(auto-fit, minmax(270px, 1fr));
}
figure, .artefact-card, .plot-card {
  margin: 0;
  background: #fbfcfe;
  border: 1px solid var(--line);
  padding: 10px;
}
img {
  display: block;
  height: auto;
  max-width: 100%;
}
.missing {
  min-height: 120px;
}
.table-tools {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin: 10px 0;
}
.scene-filter select {
  margin-left: 6px;
}
.table-wrap {
  overflow-x: auto;
}
table {
  border-collapse: collapse;
  font-size: 0.82rem;
  min-width: 620px;
  width: 100%;
}
th, td {
  border: 1px solid var(--line);
  padding: 5px 7px;
  text-align: left;
  vertical-align: top;
}
th {
  background: var(--accent-soft);
  position: sticky;
  top: 0;
}
th button {
  all: unset;
  color: var(--accent);
  cursor: pointer;
  font-weight: 700;
}
tr[hidden] {
  display: none;
}
ol {
  columns: 2 260px;
  padding-left: 1.25rem;
}
@media (max-width: 720px) {
  main { width: min(100% - 20px, 1180px); }
  h1 { font-size: 1.8rem; }
  .gallery-grid, .plot-grid { grid-template-columns: 1fr; }
}
"""


def _script() -> str:
    return """
(() => {
  const numeric = (value) => {
    const parsed = Number.parseFloat(value.replace(/,/g, ""));
    return Number.isFinite(parsed) ? parsed : null;
  };
  const sortTable = (table, column) => {
    const body = table.tBodies[0];
    const rows = Array.from(body.rows);
    const direction = table.dataset.sortColumn === String(column) &&
      table.dataset.sortDirection !== "desc" ? "desc" : "asc";
    rows.sort((a, b) => {
      const av = a.cells[column]?.textContent.trim() ?? "";
      const bv = b.cells[column]?.textContent.trim() ?? "";
      const an = numeric(av);
      const bn = numeric(bv);
      let result;
      if (an !== null && bn !== null) {
        result = an - bn;
      } else {
        result = av.localeCompare(bv, undefined, { numeric: true });
      }
      return direction === "asc" ? result : -result;
    });
    rows.forEach((row) => body.appendChild(row));
    table.dataset.sortColumn = String(column);
    table.dataset.sortDirection = direction;
  };
  document.querySelectorAll("[data-table][data-column]").forEach((button) => {
    button.addEventListener("click", () => {
      const table = document.getElementById(button.dataset.table);
      if (table) sortTable(table, Number.parseInt(button.dataset.column, 10));
    });
  });
  const filter = document.getElementById("scene-filter");
  if (filter) {
    filter.addEventListener("change", () => {
      const scene = filter.value;
      document.querySelectorAll("table.stat-table tbody tr").forEach((row) => {
        const firstCell = row.cells[0]?.textContent.trim() ?? "";
        const rowText = row.textContent;
        row.hidden = Boolean(scene) && firstCell !== scene && !rowText.includes(scene);
      });
    });
  }
})();
"""


def write_index(output_dir: Path,
                machine_id: str,
                git_sha: str,
                run_timestamp: str,
                artefacts: dict[str, str]) -> Path:
    """Write a self-contained ``index.html`` into ``output_dir``."""
    output_dir = Path(output_dir)
    header, data = _read_csv(output_dir / "stats_summary.csv")
    sections_html = _category_sections(header, data)
    scene_filter = _scene_filter(header, data)
    rmse_html = _rmse_sections(header, data)
    artefact_html = _artefact_sections(output_dir, artefacts)
    history_html = _history_links(output_dir)

    body = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Astroray Engine Showcase - {html.escape(run_timestamp)}</title>
<style>{_stylesheet()}</style>
</head>
<body>
<main>
<header>
<h1>Astroray Engine Showcase</h1>
<p class="meta">
  <strong>Run:</strong> {html.escape(run_timestamp)} &middot;
  <strong>Machine:</strong> {html.escape(machine_id)} &middot;
  <strong>Commit:</strong> <code>{html.escape(git_sha)}</code>
</p>
<p class="meta">Generated by <code>benchmarks/showcase/runner.py</code>
(pkg74). The page is self-contained for artifact review; source PNG and
CSV filenames remain embedded as metadata.</p>
</header>
{history_html}
{artefact_html}
<section>
<h2>RMSE</h2>
{rmse_html}
</section>
<section>
<h2>stats_summary.csv by category</h2>
<div class="table-tools">
<p class="meta">Click a column header to sort. Raw data:
<code>stats_summary.csv</code>.</p>
{scene_filter}
</div>
{sections_html}
</section>
</main>
<script>{_script()}</script>
</body>
</html>
"""
    out = output_dir / "index.html"
    out.write_text(body, encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate the self-contained pkg74 showcase index.")
    parser.add_argument("output_dir", type=Path,
                        help="Showcase run directory containing stats_summary.csv")
    args = parser.parse_args(argv)
    machine_id, git_sha, run_timestamp, artefacts = _infer_metadata(args.output_dir)
    write_index(args.output_dir, machine_id, git_sha, run_timestamp, artefacts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
