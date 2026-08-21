"""Tests for scripts/project_index.py — pkg215 query/coverage/freshness overhaul.

Pure-Python; drives the CLI via subprocess against the live repo so the tests
can't rot (they discover the packages/paths they assert on from the built DB).
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "project_index.py"
DB_PATH = ROOT / ".astroray_plan" / ".project-index.db"
PACKAGES_DIR = ROOT / ".astroray_plan" / "packages"
README = ROOT / "scripts" / "README.md"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


@pytest.fixture(scope="module")
def built_db():
    r = run("build")
    assert r.returncode == 0, r.stderr
    assert DB_PATH.exists()
    yield DB_PATH


def _connect():
    return sqlite3.connect(DB_PATH)


# --- 1. Scannable query -----------------------------------------------------

def test_query_is_scannable_single_line(built_db):
    r = run("query", "TRANSMISSION lobe CREATES")
    assert r.returncode == 0, r.stderr
    pkg_lines = [ln for ln in r.stdout.splitlines() if ln.strip().startswith("pkg169")]
    assert len(pkg_lines) == 1, f"pkg169 should be one line, got {pkg_lines}"
    line = pkg_lines[0]
    assert "[done]" in line
    # NOT the full multi-paragraph post-mortem.
    assert "PBRT-v4" not in line and "furnace after fix" not in line.lower()


def test_no_query_line_exceeds_120_chars(built_db):
    r = run("query", "glass")
    assert r.returncode == 0, r.stderr
    for ln in r.stdout.splitlines():
        assert len(ln) <= 120, f"line too long ({len(ln)}): {ln}"
    # one line per matching spec, none repeated. (A single pkg *number* may own
    # several distinct spec files — e.g. pkg64 has four — so the invariant is
    # "no duplicate hit line", not "unique pkg number".)
    hits = [ln for ln in r.stdout.splitlines() if ln.strip().startswith("pkg")]
    assert len(hits) == len(set(hits))


# --- 2. Body / file-path search --------------------------------------------

def test_query_matches_file_path_not_in_title(built_db):
    """A term present only in a Files-to-modify path must return the package."""
    con = _connect()
    # Find a (package, path-token) where the token is absent from title/status/pillar.
    chosen = None
    for key, path in con.execute("SELECT package_key, path FROM package_files"):
        title, status, pillar = con.execute(
            "SELECT title, status, pillar FROM packages WHERE key = ?", (key,)
        ).fetchone()
        blob = f"{title} {status} {pillar}".lower()
        # a distinctive filename stem token
        stem = re.split(r"[\\/]", path)[-1]
        token = re.sub(r"\.[a-z0-9]+$", "", stem).lower()
        if len(token) >= 6 and token not in blob and token.isidentifier() is False:
            # prefer a token with an underscore/dash (clearly a path fragment)
            if "_" in token or "-" in token:
                chosen = (key, token)
                break
    assert chosen, "expected at least one file-path-only token in the repo"
    key, token = chosen
    con.close()
    r = run("query", token)
    assert r.returncode == 0, r.stderr
    num = key  # package hit lines print num; num is a prefix of key
    assert any(token_line_matches(ln, key) for ln in r.stdout.splitlines()), \
        f"query {token!r} should return {key}; got:\n{r.stdout}"


def token_line_matches(line: str, key: str) -> bool:
    line = line.strip()
    if not line.startswith("pkg"):
        return False
    num = line.split()[0]
    return key.startswith(num)


# --- 3. owns ----------------------------------------------------------------

def test_owns_hit(built_db):
    con = _connect()
    key, path, action = con.execute(
        "SELECT package_key, path, action FROM package_files LIMIT 1"
    ).fetchone()
    con.close()
    base = re.split(r"[\\/]", path)[-1]
    r = run("owns", base)
    assert r.returncode == 0, r.stderr
    assert key in r.stdout, f"owns {base!r} should list {key}:\n{r.stdout}"


def test_owns_miss_exits_zero(built_db):
    r = run("owns", "nonexistent/path.xyz")
    assert r.returncode == 0
    assert "no package records touching nonexistent/path.xyz" in r.stdout


# --- 4. script --------------------------------------------------------------

def _readme_table_rows_matching(substr: str) -> int:
    substr = substr.lower()
    count = 0
    in_table = False
    for line in README.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("## "):
            in_table = s.lower().startswith("## canonical script per task")
            continue
        if not in_table or not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 2 or not cells[0] or cells[0] == "Task" or cells[0].startswith("---"):
            continue
        if substr in cells[0].lower():
            count += 1
    return count


def test_script_lookup_contact_sheet(built_db):
    r = run("script", "contact sheet")
    assert r.returncode == 0, r.stderr
    assert "benchmarks/showcase/runner.py" in r.stdout
    printed_rows = [ln for ln in r.stdout.splitlines() if " -> " in ln]
    assert len(printed_rows) == _readme_table_rows_matching("contact sheet")


# --- 5. whatis --------------------------------------------------------------

def test_whatis_pkg214(built_db):
    r = run("whatis", "pkg214")
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "pkg214" in out
    assert "status :" in out
    assert "track" in out
    assert "depends on:" in out
    assert "owned files" in out


# --- 6. Read-time freshness -------------------------------------------------

def test_freshness_autorebuild_on_stale(built_db):
    # Ensure DB exists and is current.
    run("build")
    token = f"freshprobe{int(time.time())}zzz"
    probe = PACKAGES_DIR / "pkg998-freshness-probe.md"
    probe.write_text(
        f"# pkg998 - freshness probe\n\n**Status:** open.\n\nbody term {token}\n",
        encoding="utf-8",
    )
    try:
        # Make the probe unambiguously newer than the DB.
        future = time.time() + 20
        os.utime(probe, (future, future))
        r = run("query", token)
        assert r.returncode == 0, r.stderr
        assert "(index rebuilt)" in r.stderr, f"expected rebuild note; stderr={r.stderr!r}"
        assert any(ln.strip().startswith("pkg998") for ln in r.stdout.splitlines()), \
            f"new spec content not reflected:\n{r.stdout}"
    finally:
        probe.unlink()
        run("build")  # restore a clean DB without the probe


# --- 7. No regression -------------------------------------------------------

def test_build_deps_graph_still_work(built_db, tmp_path):
    r = run("build")
    assert r.returncode == 0
    assert "indexed" in r.stdout and "packages" in r.stdout

    r = run("deps", "pkg214")
    assert r.returncode == 0, r.stderr
    assert "depends on:" in r.stdout
    assert "depended on by" in r.stdout

    out_json = tmp_path / "g.json"
    r = run("graph", "--json", str(out_json))
    assert r.returncode == 0, r.stderr
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert "nodes" in payload and "edges" in payload
    assert len(payload["nodes"]) > 0 and len(payload["edges"]) > 0


def test_graph_html_is_wellformed(built_db, tmp_path):
    out_html = tmp_path / "g.html"
    r = run("graph", "--html", str(out_html))
    assert r.returncode == 0, r.stderr
    html = out_html.read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>")
    assert html.rstrip().endswith("</html>")
    assert "3d-force-graph" in html
    assert "__DATA__" not in html  # template placeholder was substituted
