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
    for row in db.execute("SELECT key, num, title, status FROM packages ORDER BY num"):
        nodes.append({"id": row[0], "label": row[1], "title": row[3] and row[3][:40], "status": row[3] or "", "group": "package"})
    for row in db.execute("SELECT key, num, depends FROM packages"):
        key, _, dep_str = row
        for d in (dep_str.split(",") if dep_str else []):
            edges.append({"from": key, "to": d, "kind": "depends"})
    for row in db.execute("SELECT package_key, path FROM package_files"):
        edges.append({"from": row[0], "to": row[1], "kind": "file"})
    for row in db.execute("SELECT file, title FROM docs"):
        nodes.append({"id": row[0], "label": row[0].split("/")[-1][:40], "title": row[1][:60], "group": "doc"})

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
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Astroray node tree</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>body{{margin:0;font-family:ui-sans-serif,system-ui}}#net{{width:100vw;height:100vh}}</style>
</head><body><div id="net"></div>
<script>const data={data};const g={{
  packages:{{shape:'box',color:'#4f8cff'}},docs:{{shape:'ellipse',color:'#7ddc6f'}}}};
data.nodes.forEach(n=>{{n.color=g[n.group]?.color;n.font={{size:12}}}});
new vis.Network(document.getElementById('net'),data,{{nodes:{{scaling:{{label:{{enabled:true}}}}}},
  edges:{{arrows:'to',smooth:{{enabled:false}}}},physics:{{barnesHut:{{springLength:80}}}}}});
</script></body></html>"""


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
