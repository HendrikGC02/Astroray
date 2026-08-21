#!/usr/bin/env python3
"""Astroray project index — a lightweight SQLite knowledge graph over the repo.

Parses .astroray_plan/packages/*.md (Pillar/Track/Status/Depends on frontmatter),
.astroray_plan/docs/*.md (research notes), and tests/*.py into queryable tables,
plus optional GitHub issue/PR sync via the gh CLI.

Why SQLite and not a vector DB: the docs are already well-structured markdown;
the genuinely grep-hostile queries are cross-references (which package touches
which file, which packages depend on each other, which issue maps to which
package) — exactly what a relational index answers, without embedding cost or
staleness amplification.

Usage:
  python -m project_index build              # (re)build the index (default)
  python -m project_index query "pixel filter"
  python -m project_index deps pkg203        # dependencies + reverse deps
  python -m project_index graph --json out.json   # nodes/edges for the viz
  python -m project_index graph --html graph.html # self-contained node tree
  python -m project_index gh-sync            # pull issues/PRs via gh CLI (network)

The DB is written to .astroray_plan/.project-index.db (gitignored).
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / ".astroray_plan"
DB_PATH = PLAN / ".project-index.db"

PKG_ID_RE = re.compile(r"^pkg(\d+[a-z]?)", re.IGNORECASE)
DEP_RE = re.compile(r"pkg\d+[a-z]?", re.IGNORECASE)


def _pkg_files() -> list[Path]:
    return sorted(p for p in (PLAN / "packages").glob("*.md") if p.name != "TEMPLATE.md")


def _parse_package(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    key = path.stem
    m = PKG_ID_RE.match(key)
    num = m.group(0).lower() if m else key

    def field(label: str) -> str:
        mm = re.search(rf"\*\*{label}:\*\*\s*(.+)", text)
        return mm.group(1).strip() if mm else ""

    def field_line(label: str) -> str:
        # Some older specs use "**Track:** A" all on one line; match to end of line.
        for line in text.splitlines():
            if line.strip().startswith(f"**{label}:**"):
                return line.split("**", 3)[-1].strip()
        return ""

    title = ""
    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break

    depends = sorted({d.lower() for d in DEP_RE.findall(field_line("Depends on"))})

    # Files-to-create / Files-to-modify tables.
    files: list[tuple[str, str]] = []
    section = None
    for line in text.splitlines():
        if line.strip().startswith("### Files to create"):
            section = "create"
            continue
        if line.strip().startswith("### Files to modify"):
            section = "modify"
            continue
        if line.strip().startswith("##"):
            section = None
            continue
        if section and line.strip().startswith("|"):
            cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
            if cells and cells[0] and not cells[0].startswith("---") and cells[0] != "File":
                files.append((cells[0], section))

    return {
        "key": key,
        "num": num,
        "title": title,
        "pillar": field_line("Pillar"),
        "track": field_line("Track"),
        "status": field_line("Status"),
        "effort": field_line("Estimated effort"),
        "depends": depends,
        "files": files,
    }


def _parse_docs() -> list[dict]:
    out = []
    for path in sorted((PLAN / "docs").rglob("*.md")):
        rel = str(path.relative_to(PLAN))
        if "/archive/" in rel or "\\archive\\" in rel:
            continue
        title = ""
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
        out.append({"file": rel, "title": title})
    return out


def _parse_tests() -> list[dict]:
    out = []
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        text = path.read_text(encoding="utf-8", errors="replace")
        names = re.findall(r"^def (test_\w+)\(", text, re.MULTILINE)
        out.append({"file": rel, "count": len(names), "names": names})
    return out


def build(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        DROP TABLE IF EXISTS packages;
        DROP TABLE IF EXISTS package_files;
        DROP TABLE IF EXISTS docs;
        DROP TABLE IF EXISTS tests;
        DROP TABLE IF EXISTS issues;
        CREATE TABLE packages (
            key TEXT PRIMARY KEY, num TEXT, title TEXT, pillar TEXT,
            track TEXT, status TEXT, effort TEXT, depends TEXT
        );
        CREATE TABLE package_files (package_key TEXT, path TEXT, action TEXT);
        CREATE TABLE docs (file TEXT PRIMARY KEY, title TEXT);
        CREATE TABLE tests (file TEXT PRIMARY KEY, count INTEGER, names TEXT);
        CREATE TABLE issues (kind TEXT, number INTEGER, title TEXT, state TEXT, url TEXT);
        """
    )
    for p in _pkg_files():
        d = _parse_package(p)
        db.execute(
            "INSERT OR REPLACE INTO packages VALUES (?,?,?,?,?,?,?,?)",
            (d["key"], d["num"], d["title"], d["pillar"], d["track"], d["status"], d["effort"], ",".join(d["depends"])),
        )
        for fpath, action in d["files"]:
            db.execute("INSERT INTO package_files VALUES (?,?,?)", (d["key"], fpath, action))
    for d in _parse_docs():
        db.execute("INSERT OR REPLACE INTO docs VALUES (?,?)", (d["file"], d["title"]))
    for t in _parse_tests():
        db.execute("INSERT INTO tests VALUES (?,?,?)", (t["file"], t["count"], json.dumps(t["names"])))
    db.commit()


def gh_sync(db: sqlite3.Connection) -> None:
    """Pull open+closed issues and PRs via `gh`. Optional; skips cleanly if gh fails."""
    def _run(args):
        try:
            return subprocess.run(
                ["gh"] + args, capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace"
            ).stdout
        except Exception:
            return ""

    rows = []
    for kind, query in (("issue", "--state all"), ("pr", "--state all")):
        raw = _run([kind, "list", query, "--limit", "500", "--json", "number,title,state,url"])
        try:
            for item in json.loads(raw):
                rows.append((kind, item["number"], item["title"], item["state"], item["url"]))
        except json.JSONDecodeError:
            pass
    db.executescript("DELETE FROM issues;")
    db.executemany("INSERT INTO issues VALUES (?,?,?,?,?)", rows)
    db.commit()


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def query(db: sqlite3.Connection, text: str) -> None:
    words = re.findall(r"[\w]+", text)
    like = "%" + "%".join(words) + "%"
    print(f"== packages matching {text!r}")
    for row in db.execute(
        "SELECT num, title, status, pillar FROM packages WHERE title LIKE ? OR status LIKE ? OR pillar LIKE ? ORDER BY num",
        (like, like, like),
    ):
        print(f"  {row[0]:>8}  [{row[2]}] {row[1]}")
    print(f"== docs matching {text!r}")
    for row in db.execute("SELECT file, title FROM docs WHERE title LIKE ? OR file LIKE ? ORDER BY file", (like, like)):
        print(f"  {row[0]:<50} {row[1]}")


def deps(db: sqlite3.Connection, num: str) -> None:
    num = num.lower()
    row = db.execute("SELECT key, num, title, status, depends FROM packages WHERE num = ?", (num,)).fetchone()
    if not row:
        print(f"no package with num {num}")
        return
    key, _, title, status, dep_str = row
    print(f"{key}  [{status}] {title}")
    deps_list = dep_str.split(",") if dep_str else []
    print(f"  depends on: {', '.join(deps_list) or '(none)'}")
    rev = db.execute("SELECT key FROM packages WHERE depends LIKE ?", (f"%{num}%",)).fetchall()
    rev = [r[0] for r in rev if r[0] != key]
    print(f"  depended on by ({len(rev)}): {', '.join(rev) or '(none)'}")


def graph(db: sqlite3.Connection, json_out: str | None, html_out: str | None) -> None:
    nodes = []
    edges = []

    # Resolve dependency tokens ("pkg201") to real node ids (full filename stems),
    # which fixes the previously-dropped dependency edges.
    num_to_keys: dict[str, list[str]] = {}
    for row in db.execute("SELECT key, num, title, status FROM packages ORDER BY num"):
        num_to_keys.setdefault(row[1], []).append(row[0])
        nodes.append({
            "id": row[0], "label": row[1], "num": row[1],
            "title": (row[2] or "")[:80], "status": row[3] or "", "group": "package",
        })
    for row in db.execute("SELECT key, depends FROM packages"):
        key, dep_str = row
        for d in (dep_str.split(",") if dep_str else []):
            for k in num_to_keys.get(d, []):
                if k != key:
                    edges.append({"source": key, "target": k, "kind": "depends"})

    # File nodes + package -> file edges.
    file_ids: set[str] = set()
    for pkg, path in db.execute("SELECT package_key, path FROM package_files"):
        fid = path.replace("\\", "/")
        file_ids.add(fid)
        edges.append({"source": pkg, "target": fid, "kind": "file"})
    for fid in sorted(file_ids):
        nodes.append({"id": fid, "label": fid.split("/")[-1], "title": fid, "status": "", "group": "file"})

    doc_rows = db.execute("SELECT file, title FROM docs").fetchall()
    for row in doc_rows:
        nodes.append({"id": row[0], "label": row[0].split("/")[-1], "title": (row[1] or "")[:80], "status": "", "group": "doc"})

    # Doc <-> package edges: research docs otherwise float disconnected.
    # Heuristic (both directions, since citation style varies):
    #   - doc body mentions a pkgNNN token -> link doc to that package
    #   - a package spec body mentions the doc's filename stem -> link them
    pkg_texts = {p.stem: p.read_text(encoding="utf-8", errors="replace") for p in _pkg_files()}
    doc_edges: set[tuple[str, str]] = set()
    for doc_file, _doc_title in doc_rows:
        doc_path = PLAN / doc_file
        try:
            doc_text = doc_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            doc_text = ""
        for tok in {m.lower() for m in DEP_RE.findall(doc_text)}:
            for k in num_to_keys.get(tok, []):
                doc_edges.add((doc_file, k))
        doc_stem = Path(doc_file).stem.lower()
        if doc_stem:
            for key, text in pkg_texts.items():
                if doc_stem in text.lower():
                    doc_edges.add((doc_file, key))
    for doc_file, pkg_key in doc_edges:
        edges.append({"source": doc_file, "target": pkg_key, "kind": "doc"})

    payload = {"nodes": nodes, "edges": edges}
    if json_out:
        Path(json_out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"wrote {json_out} ({len(nodes)} nodes, {len(edges)} edges)")
    if html_out:
        Path(html_out).write_text(_html(payload), encoding="utf-8")
        print(f"wrote {html_out}")
    if not json_out and not html_out:
        print(json.dumps(payload))


def _html(payload: dict) -> str:
    data = json.dumps(payload).replace("</", "<\\/")
    return _HTML_TEMPLATE.replace("__DATA__", data)


_HTML_TEMPLATE = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>Astroray knowledge graph</title>
<style>
  html,body{margin:0;height:100%;overflow:hidden;background:#0d1117;color:#e6edf3;
    font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,sans-serif}
  #3d-graph{position:fixed;inset:0}
  #panel{position:fixed;top:14px;left:14px;z-index:10;background:rgba(13,17,23,.92);
    border:1px solid #30363d;border-radius:10px;padding:14px 16px;width:280px;font-size:13px;
    box-shadow:0 8px 24px rgba(0,0,0,.4)}
  #panel h1{margin:0 0 10px;font-size:14px;font-weight:600;letter-spacing:.2px}
  .row{display:flex;align-items:center;gap:8px;margin:5px 0}
  .sw{width:11px;height:11px;border-radius:50%;display:inline-block;flex:none;box-shadow:0 0 0 1px rgba(255,255,255,.15)}
  .sw.box{border-radius:3px}
  hr{border:none;border-top:1px solid #30363d;margin:10px 0}
  label{cursor:pointer;user-select:none;color:#c9d1d9}
  input[type=checkbox]{accent-color:#58a6ff}
  #hint{position:fixed;bottom:12px;right:14px;z-index:10;color:#8b949e;font-size:12px}
  .section{font-size:11px;text-transform:uppercase;letter-spacing:.8px;color:#8b949e;margin:8px 0 4px}
</style>
<script src="https://unpkg.com/three@0.150.1/build/three.min.js"></script>
<script src="https://unpkg.com/3d-force-graph@1.73.3/dist/3d-force-graph.min.js"></script>
</head><body>
<div id="3d-graph"></div>
<div id="panel">
  <h1>Astroray knowledge graph</h1>
  <div class="section">Packages</div>
  <div class="row"><span class="sw" style="background:#58a6ff"></span><label>open</label></div>
  <div class="row"><span class="sw" style="background:#d29922"></span><label>in-progress / in-review</label></div>
  <div class="row"><span class="sw" style="background:#3fb950"></span><label>done</label></div>
  <div class="row"><span class="sw" style="background:#8b949e"></span><label>other / research</label></div>
  <div class="section">Other nodes</div>
  <div class="row"><span class="sw box" style="background:#bc8cff"></span><label>research doc</label></div>
  <div class="row"><span class="sw box" style="background:#2ea043"></span><label>file (source / test)</label></div>
  <hr>
  <div class="section">Layers</div>
  <div class="row"><input type="checkbox" id="t-package" checked><label for="t-package">Packages</label></div>
  <div class="row"><input type="checkbox" id="t-doc" checked><label for="t-doc">Docs</label></div>
  <div class="row"><input type="checkbox" id="t-file"><label for="t-file">Files</label></div>
  <div class="row"><input type="checkbox" id="t-dep" checked><label for="t-dep">Dependency edges</label></div>
  <div class="row"><input type="checkbox" id="t-dedge" checked><label for="t-dedge">Doc edges</label></div>
  <div class="row"><input type="checkbox" id="t-fedge"><label for="t-fedge">File edges</label></div>
  <hr>
  <div class="section">Layout</div>
  <div class="row"><input type="checkbox" id="t-2d"><label for="t-2d">2D layout</label></div>
</div>
<div id="hint">drag to rotate &middot; right-drag to pan &middot; scroll to zoom &middot; hover for label</div>
<script>
const DATA = __DATA__;
let graph;

function statusColor(s){ s = (s||'').toLowerCase();
  if(s.indexOf('done')>=0) return '#3fb950';
  if(s.indexOf('progress')>=0 || s.indexOf('review')>=0) return '#d29922';
  if(s.indexOf('open')>=0) return '#58a6ff';
  return '#8b949e'; }
function nodeColor(n){ if(n.group==='doc') return '#bc8cff'; if(n.group==='file') return '#2ea043'; return statusColor(n.status); }
function nodeSize(n){ return n.group==='package' ? 2.2 : n.group==='doc' ? 1.7 : 1.0; }

// Cache of last-known node positions/velocities, keyed by id, so toggling a
// layer on/off doesn't teleport survivors and reheat the whole simulation
// (previously caused disconnected components to repel to infinity).
const posCache = {};

function cachePositions(){
  if(!graph) return;
  graph.graphData().nodes.forEach(n => {
    posCache[n.id] = {x:n.x, y:n.y, z:n.z, vx:n.vx, vy:n.vy, vz:n.vz};
  });
}

function build(){
  const show = g => document.getElementById(g).checked;
  const nodes = DATA.nodes.filter(n => (n.group==='package'&&show('t-package'))
    || (n.group==='doc'&&show('t-doc')) || (n.group==='file'&&show('t-file')));
  const ids = new Set(nodes.map(n=>n.id));
  const links = DATA.edges.filter(e => {
    if(!ids.has(e.source) || !ids.has(e.target)) return false;
    if(e.kind==='depends') return show('t-dep');
    if(e.kind==='doc') return show('t-dedge');
    return show('t-fedge');
  });
  // Re-use prior positions for nodes that survive the filter, so rebuilding
  // graphData() doesn't reset (and reheat) the whole layout.
  nodes.forEach(n => {
    const p = posCache[n.id];
    if(p){ n.x=p.x; n.y=p.y; n.z=p.z; n.vx=p.vx; n.vy=p.vy; n.vz=p.vz; }
  });
  return {nodes, links};
}

function render(){
  cachePositions();
  const d = build();
  if(!graph){
    graph = ForceGraph3D()(document.getElementById('3d-graph'))
      .graphData(d)
      .nodeId('id')
      .nodeLabel(n => n.title || n.label)
      .nodeColor(nodeColor)
      .nodeVal(nodeSize)
      .nodeRelSize(4)
      .linkColor(l => l.kind==='depends' ? 'rgba(88,166,255,0.9)' : l.kind==='doc' ? 'rgba(188,140,255,0.85)' : 'rgba(46,160,67,0.55)')
      .linkWidth(l => l.kind==='depends' ? 1.6 : l.kind==='doc' ? 1.4 : 0.6)
      .linkDirectionalParticles(l => l.kind==='file' ? 0 : 2)
      .linkDirectionalParticleWidth(1.6)
      .linkDirectionalParticleSpeed(0.004)
      .linkDirectionalArrowLength(l => l.kind==='file' ? 0 : 3.5)
      .linkDirectionalArrowRelPos(1)
      .backgroundColor('#0d1117')
      .showNavInfo(false)
      .d3VelocityDecay(0.35)
      .warmupTicks(60)
      .cooldownTicks(200)
      .onNodeHover(n => { document.getElementById('3d-graph').style.cursor = n ? 'pointer' : 'default'; })
      .onNodeClick(n => {
        const dist = 28; const deg = graph.cameraPosition();
        graph.cameraPosition({x:n.x, y:n.y, z:n.z + dist}, {x:n.x, y:n.y, z:n.z}, 1200);
      });
    // Tune the force sim: bounded charge (repulsion decays past distanceMax so
    // disconnected components don't fly apart forever), a fixed link distance,
    // and a centering force so everything stays anchored near the origin.
    graph.d3Force('charge').strength(-140).distanceMax(450);
    graph.d3Force('link').distance(l => l.kind==='file' ? 16 : 42);
    if(graph.d3Force('center')) graph.d3Force('center').strength(1);
  } else {
    // Positions were preserved above, so only a light re-settle is needed —
    // NOT a full reheat, which is what caused the infinite-drift bug.
    graph.cooldownTicks(40);
    graph.graphData(d);
  }
}

function setDimensions(is2D){
  cachePositions();
  graph.numDimensions(is2D ? 2 : 3);
  if(is2D){
    // Flatten cached z so nodes don't have to fight their way back to a plane.
    Object.values(posCache).forEach(p => { p.z = 0; p.vz = 0; });
    graph.graphData().nodes.forEach(n => { n.z = 0; n.vz = 0; });
  }
  graph.cooldownTicks(120);
  graph.d3ReheatSimulation();
}

document.querySelectorAll('#panel input[type=checkbox]:not(#t-2d)').forEach(cb => cb.addEventListener('change', render));
document.getElementById('t-2d').addEventListener('change', e => setDimensions(e.target.checked));
render();
</script>
</body></html>"""


def main() -> None:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Astroray project index")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("build", help="build the index")
    p_q = sub.add_parser("query", help="search the index")
    p_q.add_argument("text")
    p_d = sub.add_parser("deps", help="show a package's dependencies")
    p_d.add_argument("num")
    p_g = sub.add_parser("graph", help="emit nodes/edges JSON or an HTML node tree")
    p_g.add_argument("--json", dest="json_out")
    p_g.add_argument("--html", dest="html_out")
    sub.add_parser("gh-sync", help="sync GitHub issues/PRs")

    args = ap.parse_args()
    if not DB_PATH.exists():
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    db = _connect()

    cmd = args.cmd or "build"
    if cmd == "build":
        build(db)
        print(f"indexed {db.execute('SELECT COUNT(*) FROM packages').fetchone()[0]} packages, "
              f"{db.execute('SELECT COUNT(*) FROM docs').fetchone()[0]} docs, "
              f"{db.execute('SELECT COUNT(*) FROM tests').fetchone()[0]} test files -> {DB_PATH}")
    elif cmd == "query":
        query(db, args.text)
    elif cmd == "deps":
        deps(db, args.num)
    elif cmd == "graph":
        graph(db, args.json_out, args.html_out)
    elif cmd == "gh-sync":
        gh_sync(db)
        print(f"synced {db.execute('SELECT COUNT(*) FROM issues').fetchone()[0]} issues/PRs")
    db.close()


if __name__ == "__main__":
    main()
