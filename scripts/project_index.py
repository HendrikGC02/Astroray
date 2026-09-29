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
  python -m project_index query "pixel filter"   # scannable title/body/file search
  python -m project_index deps pkg203        # dependencies + reverse deps
  python -m project_index owns include/gpu_materials.h  # which package owns a file
  python -m project_index script "contact sheet"        # canonical script for a task
  python -m project_index whatis pkg214      # compact card for one package
  python -m project_index graph --json out.json   # nodes/edges for the viz
  python -m project_index graph --html graph.html # self-contained node tree
  python -m project_index gh-sync            # pull issues/PRs via gh CLI (network)
  python -m project_index lint --all         # lint package specs against TEMPLATE v2

The DB is written to .astroray_plan/.project-index.db (gitignored). Read
commands (query/deps/owns/script/whatis) auto-rebuild it when a source file is
newer than the DB and print "(index rebuilt)" to stderr, so answers are never
silently stale.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / ".astroray_plan"
DB_PATH = PLAN / ".project-index.db"
README_PATH = ROOT / "scripts" / "README.md"

PKG_ID_RE = re.compile(r"^pkg(\d+[a-z]?)", re.IGNORECASE)
DEP_RE = re.compile(r"pkg\d+[a-z]?", re.IGNORECASE)

# TEMPLATE v2 vocabulary (see .astroray_plan/packages/TEMPLATE.md). Tried
# first by _status_token so a v2-compliant "done — PR #716" (or a legacy
# "**DONE — ...**" with a stray trailing "**") both reduce cleanly to "done"
# instead of falling into the legacy split below.
_V2_STATUS_PREFIX_RE = re.compile(
    r"^(open|in-progress|blocked|paused|done|superseded)\b", re.IGNORECASE
)


def _status_token(raw: str) -> str:
    """Reduce a Status line to a short scannable token.

    Tries the TEMPLATE v2 vocabulary first (case-insensitive prefix match).
    Falls back to the legacy heuristic: text up to the first of '(', em-dash,
    '.', ',', or newline, lower-cased and stripped. e.g. "done (PR #540, ...)"
    -> "done"; "open (filed 2026-08-21)." -> "open"; "Stage 2 done ..." ->
    "stage 2 done"; "done — PR #716" -> "done".
    """
    raw = raw.replace("**", "")
    m = _V2_STATUS_PREFIX_RE.match(raw.strip())
    if m:
        return m.group(1).lower()
    token = re.split(r"[(—.,\n]", raw, maxsplit=1)[0]
    return token.strip().lower()


# ── Spec lint (TEMPLATE v2) ─────────────────────────────────────────────
#
# See .astroray_plan/packages/TEMPLATE.md for the grammar these validate.

SPEC_FILENAME_RE = re.compile(r"^pkg(\d{1,3}[a-z]?)-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
TITLE_RE = re.compile(r"^# (pkg\d{1,3}[a-z]?) — \S.*$")
STATUS_RE = re.compile(
    r"^(open|in-progress|blocked|paused|done|superseded)(?: — \S.*)?$"
)
PILLAR_RE = re.compile(r"^[1-5]?$")
TRACK_RE = re.compile(r"^[A-D]$")
DEPENDS_RE = re.compile(r"^(none|TBD|pkg\d{1,3}[a-z]?(?:, pkg\d{1,3}[a-z]?)*)$")

H2_ORDER = [
    "Goal", "Context", "Evidence", "Reference", "Prerequisites",
    "Specification", "Acceptance criteria", "Non-goals", "Progress", "Lessons",
]
H2_OPTIONAL = {"Evidence"}
SPEC_H3_ORDER = ["Files to create", "Files to modify", "Key design decisions"]

TABLE_ROW_RE = re.compile(r"^\|\s*`[^`\s]+`\s*\|\s*\S.*\|\s*$")
TABLE_SEP_RE = re.compile(r"^\|\s*-{3,}\s*\|\s*-{3,}\s*\|$")

# Five duplicate package numbers grandfathered from before numbering
# discipline existed (pkg218 was renumbered to pkg218b on 2026-09-07, #730).
# Do not add new entries here; a NEW duplicate filename is always a lint error.
LEGACY_DUP_NUMS = {"pkg38", "pkg55", "pkg64", "pkg85", "pkg86"}

FIELD_LINE_RE = re.compile(r"^\*\*([A-Za-z][A-Za-z ]*):\*\*\s*(.*)$")
REQUIRED_HEADER_FIELDS = ["Pillar", "Track", "Status", "Estimated effort", "Depends on"]

DEFAULT_BASELINE_PATH = ROOT / "scripts" / "spec_lint_baseline.txt"


def _pkg_files() -> list[Path]:
    return sorted(p for p in (PLAN / "packages").glob("*.md") if p.name != "TEMPLATE.md")


def _header_value(text: str, label: str, fold: bool = False) -> str:
    """Extract a **label:** header value (first matching physical line).

    Transitional: legacy specs sometimes wrap a field's prose across several
    lines; the linter (see `lint`) forbids this for non-baseline files, so
    this is a tolerant reader for the pre-v2 corpus, not a grammar. With
    fold=True, up to 8 continuation lines (non-blank, not a new `**Field:**`,
    not `---`/`#`) are appended — use fold=True ONLY for Depends on, whose
    legacy prose continuations can otherwise hide dependency tokens from
    DEP_RE. fold=False (the default) matches only the first physical line,
    same as the old field_line() this replaces.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith(f"**{label}:**"):
            value = line.strip()[len(f"**{label}:**"):].strip()
            if fold:
                for j in range(i + 1, min(i + 9, len(lines))):
                    nxt = lines[j]
                    stripped = nxt.strip()
                    if not stripped or stripped.startswith(("**", "---", "#")):
                        break
                    value += " " + stripped
            return value
    return ""


def _parse_package(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    key = path.stem
    m = PKG_ID_RE.match(key)
    num = m.group(0).lower() if m else key

    title = ""
    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break

    depends = sorted({d.lower() for d in DEP_RE.findall(_header_value(text, "Depends on", fold=True))})

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

    status = _header_value(text, "Status")
    return {
        "key": key,
        "num": num,
        "title": title,
        "pillar": _header_value(text, "Pillar"),
        "track": _header_value(text, "Track"),
        "status": status,
        "status_short": _status_token(status),
        "effort": _header_value(text, "Estimated effort"),
        "depends": depends,
        "files": files,
        "body": text,
    }


def _build_id_index(files: list[Path]) -> dict[str, list[Path]]:
    """id ("pkg219") -> every spec file whose filename starts with that id."""
    idx: dict[str, list[Path]] = {}
    for p in files:
        m = PKG_ID_RE.match(p.stem)
        key = ("pkg" + m.group(1)).lower() if m else p.stem.lower()
        idx.setdefault(key, []).append(p)
    return idx


def _read_baseline(path: Path) -> set[str]:
    """Read scripts/spec_lint_baseline.txt: one filename per line, '#' comments ok."""
    if not path.exists():
        return set()
    names: set[str] = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            names.add(line)
    return names


def _lint_one(path: Path, id_index: dict[str, list[Path]]) -> list[tuple[int, str, str]]:
    """Lint one spec file against TEMPLATE v2. Returns (line_no, code, msg)."""
    findings: list[tuple[int, str, str]] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    fname_match = SPEC_FILENAME_RE.match(path.name)
    if not fname_match:
        findings.append((1, "E001", f"filename '{path.name}' does not match {SPEC_FILENAME_RE.pattern}"))

    title_idx = None
    title_id = None
    for i, line in enumerate(lines):
        if line.startswith("# "):
            title_idx = i
            m = TITLE_RE.match(line)
            if m:
                title_id = m.group(1).lower()
            else:
                findings.append((i + 1, "E002", "title line does not match '# pkgNNN — <text>'"))
            break
    if title_idx is None:
        findings.append((1, "E002", "no title line ('# ...') found"))
    elif title_id is not None and fname_match:
        fname_id = ("pkg" + fname_match.group(1)).lower()
        if title_id != fname_id:
            findings.append((title_idx + 1, "E002", f"title id '{title_id}' does not match filename id '{fname_id}'"))

    id_m = PKG_ID_RE.match(path.stem)
    pkg_id = ("pkg" + id_m.group(1)).lower() if id_m else None
    if pkg_id and len(id_index.get(pkg_id, [])) > 1 and pkg_id not in LEGACY_DUP_NUMS:
        others = sorted(p.name for p in id_index[pkg_id] if p.name != path.name)
        findings.append((1, "E018", f"duplicate package number '{pkg_id}', also used by: {', '.join(others)}"))

    if title_idx is None:
        return findings  # can't scope the header/sections without a title anchor

    # Header block: from just after the title to the line before the first
    # "---" or "## " (whichever comes first).
    header_end = len(lines)
    for i in range(title_idx + 1, len(lines)):
        if lines[i].strip() == "---" or lines[i].startswith("## "):
            header_end = i
            break

    field_hits: list[tuple[int, str, str]] = []  # (line_idx, label, value)
    for i in range(title_idx + 1, header_end):
        m = FIELD_LINE_RE.match(lines[i])
        if m:
            field_hits.append((i, m.group(1).strip(), m.group(2).strip()))

    counts: dict[str, int] = {}
    first_idx: dict[str, int] = {}
    first_val: dict[str, str] = {}
    for i, label, value in field_hits:
        counts[label] = counts.get(label, 0) + 1
        if label not in first_idx:
            first_idx[label] = i
            first_val[label] = value

    for req in REQUIRED_HEADER_FIELDS:
        c = counts.get(req, 0)
        if c == 0:
            findings.append((header_end, "E003", f"missing required header field '**{req}:**'"))
        elif c > 1:
            findings.append((first_idx[req] + 1, "E003", f"duplicate header field '**{req}:**' ({c} occurrences)"))

    for i, label, value in field_hits:
        if label not in REQUIRED_HEADER_FIELDS:
            findings.append((i + 1, "E012", f"unexpected header field '**{label}:**' (move prose into ## Context)"))

    for i, label, value in field_hits:
        if i + 1 < len(lines):
            nxt = lines[i + 1]
            if nxt.strip() != "" and not FIELD_LINE_RE.match(nxt) and nxt.strip() != "---":
                findings.append((i + 2, "E005", f"'**{label}:**' field spills onto the next line; must be one physical line"))

    if all(counts.get(f, 0) >= 1 for f in REQUIRED_HEADER_FIELDS):
        order_idxs = [first_idx[f] for f in REQUIRED_HEADER_FIELDS]
        if any(order_idxs[k + 1] != order_idxs[k] + 1 for k in range(len(order_idxs) - 1)):
            findings.append((title_idx + 2, "E004",
                              "header fields must be contiguous, one per line, in order: "
                              + ", ".join(REQUIRED_HEADER_FIELDS)))

    if counts.get("Pillar", 0) >= 1 and not PILLAR_RE.match(first_val["Pillar"]):
        findings.append((first_idx["Pillar"] + 1, "E006",
                          f"Pillar value '{first_val['Pillar']}' must be a bare integer 1-5, or empty for infrastructure"))

    if counts.get("Track", 0) >= 1 and not TRACK_RE.match(first_val["Track"]):
        findings.append((first_idx["Track"] + 1, "E007", f"Track value '{first_val['Track']}' must be a single letter A-D"))

    if counts.get("Status", 0) >= 1 and not STATUS_RE.match(first_val["Status"]):
        findings.append((first_idx["Status"] + 1, "E008",
                          f"Status value '{first_val['Status']}' must be one of "
                          "open|in-progress|blocked|paused|done|superseded, "
                          "optionally followed by ' — <free text>'"))

    if counts.get("Estimated effort", 0) >= 1 and first_val["Estimated effort"] == "":
        findings.append((first_idx["Estimated effort"] + 1, "E009", "Estimated effort must not be empty (use 'TBD' if unknown)"))

    if counts.get("Depends on", 0) >= 1:
        dep_val = first_val["Depends on"]
        dep_line = first_idx["Depends on"] + 1
        if not DEPENDS_RE.match(dep_val):
            findings.append((dep_line, "E010",
                              f"Depends on value '{dep_val}' must be 'none', 'TBD', or a comma-separated pkg list"))
        elif dep_val == "TBD":
            findings.append((dep_line, "W003", "Depends on: TBD"))
        elif dep_val != "none":
            for tok in (t.strip() for t in dep_val.split(",")):
                if not id_index.get(tok.lower()):
                    findings.append((dep_line, "E011", f"dependency '{tok}' has no matching spec file"))

    # ── Sections (## headings) ──
    h2_entries = [(i, line[3:].strip()) for i, line in enumerate(lines) if line.startswith("## ")]
    h2_names = [name for _, name in h2_entries]
    h2_name_set = set(h2_names)

    for name in H2_ORDER:
        if name not in H2_OPTIONAL and name not in h2_name_set:
            findings.append((header_end + 1, "E013", f"missing required section '## {name}'"))

    for i, name in h2_entries:
        if name not in H2_ORDER:
            findings.append((i + 1, "E015", f"unknown section '## {name}' (not in TEMPLATE v2)"))

    present_ordered = [name for name in h2_names if name in H2_ORDER]
    expected_ordered = [name for name in H2_ORDER if name in h2_name_set]
    if present_ordered != expected_ordered:
        bad_line = h2_entries[0][0] + 1 if h2_entries else header_end + 1
        findings.append((bad_line, "E014", "sections out of order; expected order: " + ", ".join(H2_ORDER)))

    # ── Specification: H3 order + Files tables ──
    spec_pos = next((k for k, (_, name) in enumerate(h2_entries) if name == "Specification"), None)
    if spec_pos is not None:
        spec_start = h2_entries[spec_pos][0] + 1
        spec_end = h2_entries[spec_pos + 1][0] if spec_pos + 1 < len(h2_entries) else len(lines)
        h3_entries = [(i, lines[i][4:].strip()) for i in range(spec_start, spec_end) if lines[i].startswith("### ")]
        h3_names = [name for _, name in h3_entries]
        if h3_names != SPEC_H3_ORDER:
            findings.append((spec_start + 1, "E016",
                              f"Specification H3 sections must be exactly {SPEC_H3_ORDER}, in order; got {h3_names}"))

        h3_ranges: dict[str, tuple[int, int]] = {}
        for k, (i, name) in enumerate(h3_entries):
            start = i + 1
            end = h3_entries[k + 1][0] if k + 1 < len(h3_entries) else spec_end
            h3_ranges[name] = (start, end)

        for table_name in ("Files to create", "Files to modify"):
            if table_name not in h3_ranges:
                continue
            start, end = h3_ranges[table_name]
            content = [(i, lines[i]) for i in range(start, end) if lines[i].strip() != ""]
            if len(content) == 1 and content[0][1].strip() == "None.":
                continue
            if len(content) >= 2 and TABLE_SEP_RE.match(content[1][1].strip()):
                for i, row in content[2:]:
                    if not TABLE_ROW_RE.match(row.strip()):
                        findings.append((i + 1, "E017", f"malformed table row in '### {table_name}': {row.strip()!r}"))
                    elif table_name == "Files to modify":
                        cell = row.strip().strip("|").split("|")[0].strip().strip("`")
                        if not (ROOT / cell).exists():
                            findings.append((i + 1, "W001", f"path '{cell}' does not exist in the repo"))
            else:
                findings.append((start + 1, "E017",
                                  f"'### {table_name}' must be either the single line 'None.' or a header+separator+rows table"))

    return findings


def lint(paths: list[Path], baseline: set[str] | None, quiet: bool = False) -> int:
    """Lint each path against TEMPLATE v2. Returns process exit code (0/1)."""
    id_index = _build_id_index(_pkg_files())
    baseline = baseline or set()
    had_error = False
    for path in paths:
        if not path.exists():
            print(f"{path}: file not found", file=sys.stderr)
            had_error = True
            continue
        if path.name == "TEMPLATE.md":
            continue
        is_baselined = path.name in baseline
        file_had_error = False
        for line_no, code, msg in _lint_one(path, id_index):
            is_err = code.startswith("E")
            if is_err:
                file_had_error = True
            prefix = "baseline: " if (is_err and is_baselined) else ""
            print(f"{prefix}{path}:{line_no}: {code} {msg}")
        if is_baselined and not file_had_error:
            print(f"{path}:1: W002 file lints clean; remove it from the baseline")
        if file_had_error and not is_baselined:
            had_error = True
    if not quiet and not had_error:
        print(f"lint OK: {len(paths)} file(s) checked, {len(baseline)} baselined")
    return 1 if had_error else 0


def _parse_docs() -> list[dict]:
    out = []
    for path in sorted((PLAN / "docs").rglob("*.md")):
        rel = path.relative_to(PLAN).as_posix()
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


def _parse_scripts_map() -> list[dict]:
    """Parse the "Canonical script per task" table from scripts/README.md.

    Serves the CLAUDE.md 5b no-duplicate-scripts gate: one (task, script) row
    per table row so `script <substring>` can answer "what's the canonical
    script for task X?".
    """
    out: list[dict] = []
    if not README_PATH.exists():
        return out
    in_table = False
    for line in README_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_table = stripped.lower().startswith("## canonical script per task")
            continue
        if not in_table or not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 2:
            continue
        task, script = cells[0], cells[1]
        if not task or task == "Task" or task.startswith("---"):
            continue
        out.append({"task": task, "script": script})
    return out


def _ensure_issue_schema(db: sqlite3.Connection) -> None:
    """issues/meta hold gh-sync data and survive `build` (never dropped)."""
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS issues (kind TEXT, number INTEGER, title TEXT, state TEXT, url TEXT);
        CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
        """
    )
    cols = {r[1] for r in db.execute("PRAGMA table_info(issues)")}
    for col in ("merged_at", "closed_at"):
        if col not in cols:
            db.execute(f"ALTER TABLE issues ADD COLUMN {col} TEXT")


def build(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        DROP TABLE IF EXISTS packages;
        DROP TABLE IF EXISTS package_files;
        DROP TABLE IF EXISTS docs;
        DROP TABLE IF EXISTS tests;
        DROP TABLE IF EXISTS scripts_map;
        CREATE TABLE packages (
            key TEXT PRIMARY KEY, num TEXT, title TEXT, pillar TEXT,
            track TEXT, status TEXT, status_short TEXT, effort TEXT,
            depends TEXT, body TEXT
        );
        CREATE TABLE package_files (package_key TEXT, path TEXT, action TEXT);
        CREATE TABLE docs (file TEXT PRIMARY KEY, title TEXT);
        CREATE TABLE tests (file TEXT PRIMARY KEY, count INTEGER, names TEXT);
        CREATE TABLE scripts_map (task TEXT, script TEXT);
        """
    )
    _ensure_issue_schema(db)
    for p in _pkg_files():
        d = _parse_package(p)
        db.execute(
            "INSERT OR REPLACE INTO packages VALUES (?,?,?,?,?,?,?,?,?,?)",
            (d["key"], d["num"], d["title"], d["pillar"], d["track"], d["status"],
             d["status_short"], d["effort"], ",".join(d["depends"]), d["body"]),
        )
        for fpath, action in d["files"]:
            db.execute("INSERT INTO package_files VALUES (?,?,?)", (d["key"], fpath, action))
    for d in _parse_docs():
        db.execute("INSERT OR REPLACE INTO docs VALUES (?,?)", (d["file"], d["title"]))
    for t in _parse_tests():
        db.execute("INSERT INTO tests VALUES (?,?,?)", (t["file"], t["count"], json.dumps(t["names"])))
    for s in _parse_scripts_map():
        db.execute("INSERT INTO scripts_map VALUES (?,?)", (s["task"], s["script"]))
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

    _ensure_issue_schema(db)
    rows = []
    for kind, fields in (("issue", "number,title,state,url,closedAt"),
                         ("pr", "number,title,state,url,closedAt,mergedAt")):
        raw = _run([kind, "list", "--state", "all", "--limit", "500", "--json", fields])
        try:
            for item in json.loads(raw):
                rows.append((kind, item["number"], item["title"], item["state"], item["url"],
                             item.get("mergedAt") or "", item.get("closedAt") or ""))
        except json.JSONDecodeError:
            pass
    if rows:  # a failed/offline fetch must not wipe previously synced data
        db.executescript("DELETE FROM issues;")
        db.executemany("INSERT INTO issues VALUES (?,?,?,?,?,?,?)", rows)
        db.execute("INSERT OR REPLACE INTO meta VALUES ('gh_synced_at', ?)",
                   (datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),))
    db.commit()


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def _freshness_sources() -> list[Path]:
    """Every source file whose change should invalidate the DB."""
    srcs: list[Path] = []
    srcs += (PLAN / "packages").glob("*.md")
    for p in (PLAN / "docs").rglob("*.md"):
        rel = str(p.relative_to(PLAN))
        if "/archive/" in rel or "\\archive\\" in rel:
            continue
        srcs.append(p)
    srcs += (ROOT / "tests").glob("test_*.py")
    if README_PATH.exists():
        srcs.append(README_PATH)
    return srcs


def _db_is_stale() -> bool:
    """True if the DB is missing or older than the newest source file."""
    if not DB_PATH.exists():
        return True
    db_mtime = DB_PATH.stat().st_mtime
    for p in _freshness_sources():
        try:
            if p.stat().st_mtime > db_mtime:
                return True
        except OSError:
            continue
    return False


def query(db: sqlite3.Connection, text: str) -> None:
    words = re.findall(r"[\w]+", text)
    like = "%" + "%".join(words) + "%"
    print(f"== packages matching {text!r}")
    seen: set[str] = set()
    for row in db.execute(
        "SELECT DISTINCT key, num, title, status_short FROM packages "
        "WHERE title LIKE ? OR body LIKE ? "
        "OR key IN (SELECT package_key FROM package_files WHERE path LIKE ?) "
        "ORDER BY num",
        (like, like, like),
    ):
        key, num, title, status_short = row
        if key in seen:
            continue
        seen.add(key)
        title = (title or "")[:80]
        # Cap the token too: a handful of specs jam narrative onto the Status
        # line with no early delimiter, so the raw token can be long. Keeps
        # every query line scannable (<=120 chars).
        tok = status_short if len(status_short) <= 24 else status_short[:22] + ".."
        print(f"  {num:>8}  [{tok}] {title}")
    print(f"== docs matching {text!r}")
    for row in db.execute("SELECT file, title FROM docs WHERE title LIKE ? OR file LIKE ? ORDER BY file", (like, like)):
        line = f"  {row[0]:<50} {row[1] or ''}"
        print(line[:118])


def owns(db: sqlite3.Connection, path: str) -> None:
    needle = "%" + path.replace("\\", "/").strip("/") + "%"
    print(f"== packages owning {path!r}")
    rows = db.execute(
        "SELECT f.package_key, p.status_short, f.action, f.path "
        "FROM package_files f JOIN packages p ON p.key = f.package_key "
        "WHERE REPLACE(f.path, '\\', '/') LIKE ? ORDER BY f.package_key",
        (needle,),
    ).fetchall()
    if not rows:
        print(f"  no package records touching {path}")
        return
    for key, status_short, action, fpath in rows:
        print(f"  {key:>10}  [{status_short}]  {action:<6}  {fpath}")


def script(db: sqlite3.Connection, task: str) -> None:
    needle = "%" + task.lower() + "%"
    print(f"== canonical scripts for task {task!r}")
    rows = db.execute(
        "SELECT task, script FROM scripts_map WHERE LOWER(task) LIKE ? ORDER BY task",
        (needle,),
    ).fetchall()
    if not rows:
        print(f"  no canonical script registered for {task}")
        return
    for t, s in rows:
        print(f"  {t} -> {s}")


def _rev_deps(db: sqlite3.Connection, num: str, key: str) -> list[str]:
    """Keys of packages whose Depends-on list contains `num` as an exact token."""
    return [k for k, d in db.execute("SELECT key, depends FROM packages ORDER BY key")
            if k != key and num in (d.split(",") if d else [])]


def whatis(db: sqlite3.Connection, num: str) -> None:
    num = num.lower()
    row = db.execute(
        "SELECT key, title, status, status_short, track, pillar, effort, depends FROM packages WHERE num = ?",
        (num,),
    ).fetchone()
    if not row:
        print(f"no package with num {num}")
        return
    key, title, status, status_short, track, pillar, effort, dep_str = row
    deps_list = dep_str.split(",") if dep_str else []
    rev = _rev_deps(db, num, key)
    files = db.execute(
        "SELECT action, path FROM package_files WHERE package_key = ? ORDER BY action, path", (key,)
    ).fetchall()
    print(f"{key}  [{status_short}] {title}")
    print(f"  status : {status}")
    print(f"  track  : {track or '(none)'}    pillar: {pillar or '(none)'}    effort: {effort or '(none)'}")
    print(f"  depends on: {', '.join(deps_list) or '(none)'}")
    print(f"  depended on by ({len(rev)}): {', '.join(rev) or '(none)'}")
    if files:
        print(f"  owned files ({len(files)}):")
        for action, fpath in files:
            print(f"    {action:<6}  {fpath}")
    else:
        print("  owned files (0): (none)")


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
    rev = _rev_deps(db, num, key)
    print(f"  depended on by ({len(rev)}): {', '.join(rev) or '(none)'}")


_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_PR_REF_RE = re.compile(r"#(\d+)")
HUB_DOC_THRESHOLD = 20  # docs linked to more packages than this are "hubs"


def _pkg_state(status_short: str) -> str:
    """Normalise a Status token to open|in-progress|blocked|paused|done|superseded|other.

    TEMPLATE v2 tokens map to themselves. Legacy tokens: unblocked/ready/proposed
    -> open; in review/wip -> in-progress; complete/implemented/resolved/closed
    -> done; a trailing " done" that is not a leading "done" ("stage 2 done",
    "phases a + b + c done") means only part has landed -> in-progress.
    """
    t = re.sub(r"^[^a-z0-9]+", "", status_short.lower())
    if t.startswith(("unblocked", "ready", "proposed", "open")):
        return "open"
    if t.startswith("blocked"):
        return "blocked"
    if t.startswith(("in-progress", "in progress", "in-review", "in review", "wip")):
        return "in-progress"
    if t.startswith(("done", "complete", "implemented", "resolved", "closed", "landed", "merged")):
        return "done"
    if t.endswith(" done"):
        return "in-progress"
    if t.startswith(("paused", "deferred", "on hold")):
        return "paused"
    if t.startswith("superseded"):
        return "superseded"
    return "other"


def _goal(body: str) -> str:
    m = re.search(r"^## Goal[ \t]*\n(.*?)(?=^## |\Z)", body.replace("\r\n", "\n"), re.MULTILINE | re.DOTALL)
    return " ".join(m.group(1).split())[:300] if m else ""


def _pkg_num(key: str) -> str:
    m = PKG_ID_RE.match(key)
    return m.group(0).lower() if m else key


def _git_out(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                              timeout=10, encoding="utf-8", errors="replace").stdout.strip()
    except Exception:
        return ""


def _repo_url() -> str:
    m = re.match(r"(?:git@github\.com:|https?://(?:[^@/]+@)?github\.com/)([^/]+/[^/]+?)(?:\.git)?/?$",
                 _git_out("remote", "get-url", "origin"))
    return f"https://github.com/{m.group(1)}" if m else ""


def _graph_payload(db: sqlite3.Connection) -> dict:
    """Nodes/edges (+meta) for the viz. Deterministic for a given DB/repo state."""
    _ensure_issue_schema(db)
    nodes: list[dict] = []
    edges: list[dict] = []

    pkg_rows = db.execute(
        "SELECT key, num, title, pillar, track, status, status_short, effort, depends, body "
        "FROM packages ORDER BY num, key"
    ).fetchall()
    # Resolve dependency tokens ("pkg201") to real node ids (full filename stems).
    num_to_keys: dict[str, list[str]] = {}
    for r in pkg_rows:
        num_to_keys.setdefault(r[1], []).append(r[0])
    nfiles = dict(db.execute("SELECT package_key, COUNT(DISTINCT path) FROM package_files GROUP BY package_key"))

    issue_rows = db.execute(
        "SELECT kind, number, title, state, url, merged_at, closed_at FROM issues ORDER BY kind, number"
    ).fetchall()
    merged_prs_by_num: dict[str, list[int]] = {}
    for kind, number, title, state, _url, merged_at, _c in issue_rows:
        if kind == "pr" and (merged_at or (state or "").upper() == "MERGED"):
            for tok in {t.lower() for t in DEP_RE.findall(title or "")}:
                merged_prs_by_num.setdefault(tok, []).append(number)

    pkg_prs: dict[int, list[str]] = {}  # PR/issue number -> package keys citing it in Status
    for key, num, title, pillar, track, status, status_short, effort, dep_str, body in pkg_rows:
        status = status.replace("**", "").strip()
        state = _pkg_state(status_short)
        dm = _DATE_RE.search(status)
        prs = sorted({int(n) for n in _PR_REF_RE.findall(status)})
        for n in prs:
            pkg_prs.setdefault(n, []).append(key)
        dep_list = dep_str.split(",") if dep_str else []
        nodes.append({
            "id": key, "label": num, "num": num, "title": (title or "")[:120], "status": status,
            "group": "package", "state": state,
            "pillar": pillar[0] if pillar and pillar[0].isdigit() else "",
            "track": track or "", "effort": effort or "", "date": dm.group(0) if dm else "",
            "prs": prs, "goal": _goal(body or ""), "path": f".astroray_plan/packages/{key}.md",
            "nfiles": nfiles.get(key, 0),
            "unresolved": [d for d in dep_list if d not in num_to_keys],
            "stale_prs": sorted(merged_prs_by_num.get(num, [])) if state in ("open", "in-progress") else [],
        })
        for d in dep_list:
            keys = num_to_keys.get(d, [])
            for k in keys:
                # No edges between members of the same legacy duplicate family.
                if k != key and _pkg_num(k) != num:
                    e = {"source": key, "target": k, "kind": "depends"}
                    if len(keys) > 1:
                        e["ambiguous"] = True
                    edges.append(e)

    # File nodes + package -> file edges.
    file_edges = {(pkg, path.replace("\\", "/"))
                  for pkg, path in db.execute("SELECT package_key, path FROM package_files")}
    for pkg, fid in sorted(file_edges):
        edges.append({"source": pkg, "target": fid, "kind": "file"})
    for fid in sorted({fid for _p, fid in file_edges}):
        nodes.append({"id": fid, "label": fid.split("/")[-1], "title": fid, "status": "",
                      "group": "file", "path": fid})

    doc_rows = db.execute("SELECT file, title FROM docs ORDER BY file").fetchall()
    # Doc <-> package edges: research docs otherwise float disconnected.
    # Heuristic (both directions, since citation style varies):
    #   - doc body mentions a pkgNNN token -> link doc to that package
    #   - a package spec body mentions the doc's filename stem -> link them
    # A token naming a duplicated legacy num links every spec of it, flagged ambiguous.
    pkg_texts = {p.stem: p.read_text(encoding="utf-8", errors="replace").lower() for p in _pkg_files()}
    doc_edges: dict[tuple[str, str], bool] = {}  # (doc, pkg) -> ambiguous
    for doc_file, _t in doc_rows:
        try:
            doc_text = (PLAN / doc_file).read_text(encoding="utf-8", errors="replace")
        except OSError:
            doc_text = ""
        for tok in {m.lower() for m in DEP_RE.findall(doc_text)}:
            keys = num_to_keys.get(tok, [])
            for k in keys:
                doc_edges[(doc_file, k)] = len(keys) > 1
        doc_stem = Path(doc_file).stem.lower()
        if doc_stem:
            for key, text in pkg_texts.items():
                if doc_stem in text:
                    doc_edges[(doc_file, key)] = False
    doc_degree: dict[str, int] = {}
    for doc_file, _k in doc_edges:
        doc_degree[doc_file] = doc_degree.get(doc_file, 0) + 1
    hubs = {d for d, n in doc_degree.items() if n > HUB_DOC_THRESHOLD}
    for doc_file, title in doc_rows:
        nodes.append({"id": doc_file, "label": doc_file.split("/")[-1], "title": (title or "")[:80],
                      "status": "", "group": "doc", "path": f".astroray_plan/{doc_file}",
                      "hub": doc_file in hubs})
    for (doc_file, key), amb in sorted(doc_edges.items()):
        e = {"source": doc_file, "target": key, "kind": "doc"}
        if amb:
            e["ambiguous"] = True
        if doc_file in hubs:
            e["hub"] = True
        edges.append(e)

    # Issue/PR nodes: only those linked to a package (title token, or cited in a Status).
    for kind, number, title, state, url, merged_at, closed_at in issue_rows:
        links: dict[str, bool] = {}
        for tok in {t.lower() for t in DEP_RE.findall(title or "")}:
            keys = num_to_keys.get(tok, [])
            for k in keys:
                links[k] = len(keys) > 1
        for k in pkg_prs.get(number, []):
            links[k] = False
        if not links:
            continue
        iid = f"{kind}#{number}"
        nodes.append({"id": iid, "label": f"#{number}", "title": (title or "")[:120], "status": "",
                      "group": "issue", "kind": kind, "gh_state": state or "", "url": url or "",
                      "merged": bool(merged_at or (state or "").upper() == "MERGED")})
        for k, amb in sorted(links.items()):
            e = {"source": iid, "target": k, "kind": "issue"}
            if amb:
                e["ambiguous"] = True
            edges.append(e)

    edges.sort(key=lambda e: (e["kind"], e["source"], e["target"]))
    row = db.execute("SELECT v FROM meta WHERE k = 'gh_synced_at'").fetchone()
    meta = {"repo": _repo_url(), "head": _git_out("rev-parse", "--short", "HEAD"),
            "gh_synced_at": row[0] if row else ""}
    return {"meta": meta, "nodes": nodes, "edges": edges}


def graph(db: sqlite3.Connection, json_out: str | None, html_out: str | None) -> None:
    payload = _graph_payload(db)
    nodes, edges = payload["nodes"], payload["edges"]
    if json_out:
        Path(json_out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"wrote {json_out} ({len(nodes)} nodes, {len(edges)} edges)")
    if html_out:
        Path(html_out).write_text(_html(payload), encoding="utf-8")
        print(f"wrote {html_out}")
    if not json_out and not html_out:
        print(json.dumps(payload))


def _html(payload: dict) -> str:
    meta = dict(payload.get("meta", {}),
                generated=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
    # "<" -> \u003c keeps the JSON safe inside a <script> element (valid in JSON strings).
    data = json.dumps(dict(payload, meta=meta), separators=(",", ":")).replace("<", "\\u003c")
    return _HTML_TEMPLATE.replace("__DATA__", data)


_HTML_TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Astroray knowledge graph</title>
<style>
  :root{--c-bg:#0d1117;--c-fg:#e6edf3;--c-mute:#8b949e;--c-line:#30363d;--c-panel:rgba(13,17,23,.94);--c-accent:#58a6ff;
    --c-open:#58a6ff;--c-in-progress:#d29922;--c-blocked:#f85149;--c-paused:#39c5cf;--c-done:#3fb950;
    --c-superseded:#6e7681;--c-other:#b0b8c1;--c-doc:#bc8cff;--c-file:#c9a26b;--c-issue:#f778ba;
    --c-stale:#ff8c00;--c-unres:#ff3b3b;--c-nofile:#e6edf3}
  @media (prefers-color-scheme: light){:root:not([data-theme=dark]){--c-bg:#ffffff;--c-fg:#1f2328;--c-mute:#59636e;
    --c-line:#d0d7de;--c-panel:rgba(255,255,255,.95);--c-accent:#0969da;--c-open:#0969da;--c-in-progress:#9a6700;
    --c-blocked:#cf222e;--c-paused:#1b7c83;--c-done:#1a7f37;--c-superseded:#6e7781;--c-other:#8c959f;--c-doc:#8250df;
    --c-file:#a0713b;--c-issue:#bf3989;--c-stale:#d4570b;--c-unres:#cf222e;--c-nofile:#1f2328}}
  :root[data-theme=light]{--c-bg:#ffffff;--c-fg:#1f2328;--c-mute:#59636e;--c-line:#d0d7de;--c-panel:rgba(255,255,255,.95);
    --c-accent:#0969da;--c-open:#0969da;--c-in-progress:#9a6700;--c-blocked:#cf222e;--c-paused:#1b7c83;--c-done:#1a7f37;
    --c-superseded:#6e7781;--c-other:#8c959f;--c-doc:#8250df;--c-file:#a0713b;--c-issue:#bf3989;--c-stale:#d4570b;
    --c-unres:#cf222e;--c-nofile:#1f2328}
  [hidden]{display:none!important}
  html,body{margin:0;height:100%;overflow:hidden;background:var(--c-bg);color:var(--c-fg);
    font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,sans-serif;font-size:13px}
  .stage{position:fixed;inset:0}
  aside{position:fixed;z-index:10;background:var(--c-panel);border:1px solid var(--c-line);border-radius:10px;
    box-shadow:0 8px 24px rgba(0,0,0,.25);overflow:auto;box-sizing:border-box}
  #panel{top:14px;left:14px;width:260px;max-height:calc(100vh - 28px);padding:10px 12px}
  #panel.collapsed{width:auto}
  details.sec{margin:6px 0}details.sec>summary{cursor:pointer;font-size:11px;text-transform:uppercase;letter-spacing:.8px;color:var(--c-mute)}
  #loading{position:fixed;z-index:15;top:50%;left:50%;transform:translate(-50%,-50%);padding:8px 16px;border-radius:8px;background:var(--c-panel);border:1px solid var(--c-line)}
  .clamp{display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden}
  #panel header,#insp .ih{display:flex;align-items:center;justify-content:space-between;gap:8px}
  #panel h1{margin:0;font-size:14px;font-weight:600}
  #panel.collapsed #pbody{display:none}
  button{background:transparent;color:var(--c-fg);border:1px solid var(--c-line);border-radius:6px;padding:2px 8px;cursor:pointer;font:inherit}
  button:hover{border-color:var(--c-accent)}
  input[type=text],select{width:100%;box-sizing:border-box;background:var(--c-bg);color:var(--c-fg);border:1px solid var(--c-line);
    border-radius:6px;padding:5px 8px;font:inherit}
  input[type=checkbox]{accent-color:var(--c-accent);margin:0}
  label{cursor:pointer;user-select:none}
  .row{display:flex;align-items:center;gap:8px;margin:4px 0}
  .grid{display:flex;flex-wrap:wrap;gap:2px 12px}
  .chip{display:inline-flex;align-items:center;gap:5px;margin:2px 0}
  .sw{width:11px;height:11px;border-radius:50%;display:inline-block;flex:none;box-shadow:0 0 0 1px rgba(128,128,128,.4)}
  .sw.box{border-radius:3px}.sw.dia{border-radius:2px;transform:rotate(45deg) scale(.85)}
  hr{border:none;border-top:1px solid var(--c-line);margin:9px 0}
  .section{font-size:11px;text-transform:uppercase;letter-spacing:.8px;color:var(--c-mute);margin:8px 0 4px}
  .mute,small{color:var(--c-mute)}
  #fresh{font-size:11px;margin:6px 0 8px;line-height:1.4}
  #res .hit{padding:4px 6px;border-radius:6px;cursor:pointer;display:flex;gap:6px;align-items:baseline}
  #res .hit:hover,#res .hit.first{background:rgba(128,128,128,.18)}
  #insp{top:14px;right:14px;width:340px;max-height:calc(100vh - 28px);padding:12px 14px;line-height:1.45}
  #insp .it{font-weight:600;margin:6px 0}
  #insp h4{margin:10px 0 3px;font-size:11px;text-transform:uppercase;letter-spacing:.7px;color:var(--c-mute)}
  #insp .st{margin:0;white-space:pre-wrap;word-break:break-word}
  #insp ul{margin:2px 0;padding-left:16px}
  #insp li{margin:1px 0;word-break:break-word}
  #insp a{color:var(--c-accent);text-decoration:none}#insp a:hover{text-decoration:underline}
  .badge{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;font-weight:600;color:#fff;margin-left:6px}
  .amb{color:var(--c-mute);font-size:11px}
  .warn{color:var(--c-stale)}
  code,.cmd{font-family:ui-monospace,Consolas,monospace;font-size:11.5px}
  .cmd{display:flex;gap:6px;align-items:center;background:var(--c-bg);border:1px solid var(--c-line);border-radius:6px;padding:4px 6px}
  .cmd code{flex:1;overflow-x:auto;white-space:nowrap}
  #banner{position:fixed;z-index:20;top:0;left:0;right:0;padding:8px 14px;background:#9a6700;color:#fff;text-align:center}
  #fallback{position:fixed;inset:0;overflow:auto;padding:52px 18px 18px;box-sizing:border-box;background:var(--c-bg)}
  #fallback table{border-collapse:collapse;width:100%;margin-top:10px}
  #fallback th,#fallback td{border-bottom:1px solid var(--c-line);padding:4px 8px;text-align:left;vertical-align:top}
  @media (max-width:700px){
    #panel{top:8px;left:8px;right:8px;width:auto;max-height:50vh}
    #insp{top:auto;right:0;left:0;bottom:0;width:auto;max-height:45vh;border-radius:12px 12px 0 0}
  }
</style>
</head><body>
<div id="g2" class="stage"></div>
<div id="g3" class="stage" hidden></div>
<div id="banner" hidden></div>
<div id="loading" hidden>Loading 3D&hellip;</div>
<aside id="panel">
  <header><h1>Astroray knowledge graph</h1>
    <span><button id="theme" title="Toggle light/dark">&#9680;</button> <button id="collapse" title="Collapse panel">&#8211;</button></span></header>
  <div id="pbody">
    <div id="fresh" class="mute"></div>
    <input type="text" id="q" placeholder="Search num / title / path  ( / )" autocomplete="off">
    <div id="res"></div>
    <div class="section" style="margin-top:6px">Layout</div>
    <select id="layout"><option value="2d">2D graph</option><option value="3d">3D graph</option><option value="timeline">Timeline (packages by date &times; pillar)</option></select>
    <div class="section">Focus on selection (f)</div>
    <select id="focus"><option value="0">off</option><option value="1">1-hop neighbourhood</option><option value="2">2-hop neighbourhood</option>
      <option value="up">upstream dependencies</option><option value="down">downstream dependants</option></select>
    <details class="sec"><summary>Layers</summary>
      <div class="grid">
        <label class="chip"><input type="checkbox" id="t-package" checked>Packages</label>
        <label class="chip"><input type="checkbox" id="t-doc">Docs</label>
        <label class="chip"><input type="checkbox" id="t-file">Files</label>
        <label class="chip"><input type="checkbox" id="t-issue">Issues/PRs</label>
      </div>
      <div class="grid" style="margin-top:4px">
        <span class="chip"><i class="sw box" style="background:var(--c-doc)"></i>doc</span>
        <span class="chip"><i class="sw box" style="background:var(--c-file);transform:scale(.7)"></i>file</span>
        <span class="chip"><i class="sw dia" style="background:var(--c-issue)"></i>issue / PR</span>
      </div>
    </details>
    <details class="sec"><summary>Edges</summary>
      <div class="grid">
        <label class="chip"><input type="checkbox" id="t-dep" checked>Dependency</label>
        <label class="chip"><input type="checkbox" id="t-dedge">Doc</label>
        <label class="chip"><input type="checkbox" id="t-hub">Hub-doc edges</label>
        <label class="chip"><input type="checkbox" id="t-fedge">File</label>
        <label class="chip"><input type="checkbox" id="t-iedge" checked>Issue/PR</label>
      </div>
    </details>
    <details class="sec"><summary>Package state</summary>
      <div class="grid" id="states"></div>
      <label class="chip"><input type="checkbox" id="t-hidedone">Hide done</label>
    </details>
    <details class="sec"><summary>Pillar</summary><div class="grid" id="pillars"></div></details>
    <details class="sec"><summary>Health overlay</summary>
      <label class="chip"><input type="checkbox" id="t-health">Show rings</label>
      <div id="hcounts" class="mute"></div>
    </details>
    <hr><div id="counts" class="mute"></div>
    <div class="mute" style="margin-top:6px;font-size:11px">click a node to inspect &middot; f focus &middot; / search &middot; Esc clear</div>
  </div>
</aside>
<aside id="insp" hidden></aside>
<div id="fallback" hidden>
  <h2 style="margin:0 0 6px">Astroray package index (offline table)</h2>
  <input type="text" id="fq" placeholder="Filter packages...">
  <table><thead><tr><th>id</th><th>state</th><th>title</th><th>depends on</th></tr></thead><tbody id="ftb"></tbody></table>
</div>
<script>
const DATA = __DATA__;
const META = DATA.meta || {};
const LIBS = {
  fg2: 'https://unpkg.com/force-graph@1.43.5/dist/force-graph.min.js',
  fg3: 'https://unpkg.com/3d-force-graph@1.73.3/dist/3d-force-graph.min.js'
};
const STATES = ['open','in-progress','blocked','paused','done','superseded','other'];
const PILLARS = ['1','2','3','4','5',''];
const FOCI = ['0','1','2','up','down'];
const $ = id => document.getElementById(id);
const T = id => $(id).checked;
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const idOf = x => (x && typeof x === 'object') ? x.id : x;

// ---- indexes over the embedded data (DATA.edges is never mutated) -------------
const byId = {};
DATA.nodes.forEach(n => byId[n.id] = n);
const NB = {};   // id -> {dep, rdep, doc, file, issue}: neighbours seen from that node
const nb = id => NB[id] || (NB[id] = {dep:[], rdep:[], doc:[], file:[], issue:[]});
DATA.edges.forEach(e => {
  const amb = !!e.ambiguous;
  if(e.kind === 'depends'){ nb(e.source).dep.push({id:e.target, amb}); nb(e.target).rdep.push({id:e.source, amb}); }
  else { nb(e.source)[e.kind].push({id:e.target, amb}); nb(e.target)[e.kind].push({id:e.source, amb}); }
});
const PKGS = DATA.nodes.filter(n => n.group === 'package');
const hasHealth = n => n.group === 'package' && (n.stale_prs.length || n.unresolved.length || n.nfiles === 0);
const healthKey = n => n.stale_prs.length ? 'stale' : n.unresolved.length ? 'unres' : (n.nfiles === 0 ? 'nofile' : '');

// ---- theme / palette (single source of truth: the CSS variables) --------------
let PV = {};
function readPal(){
  const cs = getComputedStyle(document.documentElement); PV = {};
  ['bg','fg','mute','open','in-progress','blocked','paused','done','superseded','other','doc','file','issue','stale','unres','nofile']
    .forEach(k => PV[k] = cs.getPropertyValue('--c-' + k).trim());
}
function hexA(hex, a){
  hex = hex.replace('#', ''); if(hex.length === 3) hex = hex.split('').map(c => c + c).join('');
  const v = parseInt(hex, 16); return 'rgba(' + (v >> 16 & 255) + ',' + (v >> 8 & 255) + ',' + (v & 255) + ',' + a + ')';
}
const colorOf = n => n.group === 'package' ? PV[n.state] : PV[n.group];
function effTheme(){ return document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'); }
function themeChanged(){
  readPal();
  if(g2) g2.backgroundColor(PV.bg);
  if(g3) g3.backgroundColor(PV.bg);
  refreshStyle();
}
try { const t = localStorage.getItem('idx-theme'); if(t === 'dark' || t === 'light') document.documentElement.dataset.theme = t; } catch(e) {}
readPal();

// ---- state --------------------------------------------------------------------
let g2 = null, g3 = null, graph = null;
let layout = '2d', focus = '0', sel = null, focusSet = null;
let curNodes = [], curLinks = [], TL = null;
const F = {state:{}, pillar:{}};
STATES.forEach(s => F.state[s] = true);
PILLARS.forEach(p => F.pillar[p] = true);

const pkgOk = n => F.state[n.state] && F.pillar[n.pillar];
function visible(n){
  if(layout === 'timeline') return n.group === 'package' && pkgOk(n);
  switch(n.group){
    case 'package': return T('t-package') && pkgOk(n);
    case 'doc': return T('t-doc') && (!n.hub || T('t-hub'));
    case 'file': return T('t-file');
    default: return T('t-issue');
  }
}
function edgeOn(e){
  switch(e.kind){
    case 'depends': return T('t-dep');
    case 'doc': return T('t-dedge') && (!e.hub || T('t-hub'));
    case 'file': return T('t-fedge');
    default: return T('t-iedge');
  }
}
function build(){
  const nodes = DATA.nodes.filter(visible);
  const ids = new Set(nodes.map(n => n.id));
  // Fresh link objects every time: the graph libs rewrite source/target into node objects.
  const links = DATA.edges.filter(e => edgeOn(e) && ids.has(e.source) && ids.has(e.target) &&
    (layout !== 'timeline' || e.source === sel || e.target === sel)).map(e => Object.assign({}, e));
  return {nodes, links};
}

// ---- focus ----------------------------------------------------------------------
function computeFocus(){
  focusSet = null;
  if(!sel || focus === '0') return;
  const seen = new Set([sel]);
  let q = [sel];
  if(focus === 'up' || focus === 'down'){
    const key = focus === 'up' ? 'dep' : 'rdep';
    while(q.length){
      const nx = [];
      q.forEach(id => (NB[id] ? NB[id][key] : []).forEach(o => { if(!seen.has(o.id)){ seen.add(o.id); nx.push(o.id); } }));
      q = nx;
    }
  } else {
    const adj = {};
    curLinks.forEach(l => { const a = idOf(l.source), b = idOf(l.target); (adj[a] = adj[a] || []).push(b); (adj[b] = adj[b] || []).push(a); });
    for(let h = 0; h < +focus; h++){
      const nx = [];
      q.forEach(id => (adj[id] || []).forEach(o => { if(!seen.has(o)){ seen.add(o); nx.push(o); } }));
      q = nx;
    }
  }
  focusSet = seen;
}
const dimmed = n => focusSet && !focusSet.has(n.id);
const linkDimmed = l => focusSet && !(focusSet.has(idOf(l.source)) && focusSet.has(idOf(l.target)));

// ---- drawing (2D) ---------------------------------------------------------------
const ACTIVE = {'open':1, 'in-progress':1, 'blocked':1};
const shortTitle = n => (n.title || '').replace(/^pkg[0-9a-z-]*\s*[—–-]\s*/i, '');
let Kz = 1;
function nodePx(n){   // on-screen radius in px (>= ~4)
  if(n.group === 'package') return ACTIVE[n.state] ? 6.5 : n.state === 'done' ? 4 : 4.5;
  return n.group === 'doc' ? 4 : n.group === 'issue' ? 4.5 : 3.5;
}
function drawNode(n, ctx, k){
  if(n.x == null || isNaN(n.x)) return;
  const dim = dimmed(n), isSel = n.id === sel, r = nodePx(n) * (layout === 'timeline' ? 0.8 : 1) / k;
  ctx.globalAlpha = dim ? 0.12 : n.state === 'done' ? 0.6 : 1;
  ctx.fillStyle = colorOf(n);
  ctx.beginPath();
  if(n.group === 'package') ctx.arc(n.x, n.y, r, 0, 2 * Math.PI);
  else if(n.group === 'issue'){ const d = r * 1.3; ctx.moveTo(n.x, n.y - d); ctx.lineTo(n.x + d, n.y); ctx.lineTo(n.x, n.y + d); ctx.lineTo(n.x - d, n.y); ctx.closePath(); }
  else ctx.rect(n.x - r, n.y - r, 2 * r, 2 * r);
  ctx.fill();
  if(T('t-health') && hasHealth(n)){
    const hk = healthKey(n);
    ctx.strokeStyle = PV[hk]; ctx.lineWidth = 1.6 / k;
    ctx.setLineDash(hk === 'nofile' ? [2 / k, 2 / k] : []);
    ctx.beginPath(); ctx.arc(n.x, n.y, r + 2.6 / k, 0, 2 * Math.PI); ctx.stroke(); ctx.setLineDash([]);
  }
  if(isSel){ ctx.strokeStyle = PV.fg; ctx.lineWidth = 2 / k; ctx.beginPath(); ctx.arc(n.x, n.y, r + 5 / k, 0, 2 * Math.PI); ctx.stroke(); }
  let txt = null;
  if(n.group === 'package'){
    if(isSel || k >= 3.5) txt = (n.num + ' ' + shortTitle(n)).slice(0, 64);
    else if(ACTIVE[n.state] || k >= 1.8 || (focusSet && !dim && k >= 0.9)) txt = n.num;
  } else if(isSel || k >= 5) txt = n.label;
  if(txt && !dim){
    ctx.globalAlpha = 1;
    ctx.font = (11 / k) + 'px system-ui,sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    ctx.lineWidth = 3 / k; ctx.strokeStyle = PV.bg; ctx.strokeText(txt, n.x, n.y + r + 2 / k);
    ctx.fillStyle = PV.fg; ctx.fillText(txt, n.x, n.y + r + 2 / k);
  }
  ctx.globalAlpha = 1;
}
function paintArea(n, color, ctx, k){ if(n.x == null) return; ctx.fillStyle = color; ctx.beginPath(); ctx.arc(n.x, n.y, (nodePx(n) + 2) / (k || 1), 0, 2 * Math.PI); ctx.fill(); }
const touchesSel = l => sel && (idOf(l.source) === sel || idOf(l.target) === sel);
const linkBase = l => l.kind === 'depends' ? PV.open : l.kind === 'doc' ? PV.doc : l.kind === 'file' ? PV.file : PV.issue;
function linkCol(l){
  const a = linkDimmed(l) ? 0.04 : touchesSel(l) ? 0.9 : l.ambiguous ? 0.25 : l.kind === 'depends' ? 0.45 : l.kind === 'issue' ? 0.3 : 0.2;
  return hexA(linkBase(l), a);
}
function linkCol3(l){   // 3D lines are 1 px: needs more opacity, most of all on a light background
  const light = effTheme() === 'light';
  const a = linkDimmed(l) ? 0.05 : touchesSel(l) ? 1 : l.kind === 'depends' ? (light ? 0.85 : 0.6) : (light ? 0.5 : 0.3);
  return hexA(linkBase(l), a);
}
const linkW = l => (touchesSel(l) ? 1.6 : l.kind === 'depends' ? 0.8 : 0.4) / Kz;
function preFrame(ctx, k){
  if(layout !== 'timeline' || !TL) return;
  const lx = graph.screen2GraphCoords(freeRect().x0 + 8, 0).x;
  ctx.save();
  ctx.font = (11 / k) + 'px system-ui,sans-serif'; ctx.fillStyle = PV.mute; ctx.strokeStyle = hexA(PV.mute, 0.25); ctx.lineWidth = 1 / k;
  ctx.textAlign = 'left'; ctx.textBaseline = 'top';
  TL.lanes.forEach((ln, i) => {
    const y = i * TL.laneH - TL.laneH / 2;
    ctx.beginPath(); ctx.moveTo(TL.xmin, y); ctx.lineTo(TL.xmax, y); ctx.stroke();
    ctx.fillStyle = PV.fg; ctx.fillText(ln, lx, y + 4 / k); ctx.fillStyle = PV.mute;
  });
  TL.months.forEach(m => {
    ctx.beginPath(); ctx.moveTo(m.x, TL.ytop); ctx.lineTo(m.x, TL.ybot); ctx.stroke();
    ctx.fillText(m.label, m.x + 2 / k, TL.ytop - 14 / k);
  });
  ctx.restore();
}

// ---- timeline layout ------------------------------------------------------------
function layoutTimeline(){
  const DAYW = 14, LANE_H = 150, X_UND = -140;
  const times = PKGS.filter(n => n.date).map(n => Date.parse(n.date));
  const d0 = times.length ? Math.min.apply(null, times) : Date.now();
  const d1 = times.length ? Math.max.apply(null, times) : d0;
  const cnt = {};
  PKGS.forEach(n => {
    const li = PILLARS.indexOf(n.pillar), key = li + '|' + (n.date || '-'), c = cnt[key] || 0;
    cnt[key] = c + 1;
    const x = n.date ? (Date.parse(n.date) - d0) / 864e5 * DAYW + Math.floor(c / 11) * 9 : X_UND - Math.floor(c / 11) * 9;
    n.x = n.fx = x; n.y = n.fy = li * LANE_H + (c % 11) * 12 - 60;
  });
  const months = [{x: X_UND, label: 'undated'}];
  const m = new Date(d0); m.setUTCDate(1);
  for(; m.getTime() <= d1; m.setUTCMonth(m.getUTCMonth() + 1)){
    const x = (m.getTime() - d0) / 864e5 * DAYW;
    if(x >= 0) months.push({x, label: m.toISOString().slice(0, 7)});
  }
  TL = {laneH: LANE_H, months, xmin: -260, xmax: (d1 - d0) / 864e5 * DAYW + 160, ytop: -LANE_H / 2, ybot: PILLARS.length * LANE_H - LANE_H / 2,
        lanes: PILLARS.map(p => p ? 'Pillar ' + p : 'Infra / none')};
}
function clearFixed(){ DATA.nodes.forEach(n => { delete n.fx; delete n.fy; }); }

// ---- renderers ------------------------------------------------------------------
function loadScript(src){
  return new Promise((res, rej) => {
    const s = document.createElement('script'); s.src = src; s.onload = res;
    s.onerror = () => rej(new Error('could not load ' + src)); document.head.appendChild(s);
  });
}
function make2D(){
  g2 = ForceGraph()($('g2'))
    .nodeId('id').backgroundColor(PV.bg)
    .nodeCanvasObject(drawNode).nodeCanvasObjectMode(() => 'replace').nodePointerAreaPaint(paintArea)
    .onZoom(z => { Kz = z.k; })
    .nodeLabel(n => esc(n.title || n.label))
    .linkColor(linkCol).linkWidth(linkW).linkLineDash(l => l.ambiguous ? [3, 3] : null)
    .linkDirectionalArrowLength(l => l.kind === 'depends' ? 5 / Kz : 0).linkDirectionalArrowRelPos(1)
    .autoPauseRedraw(false).d3VelocityDecay(0.35).cooldownTicks(100)
    .onEngineStop(() => { if(fitPending){ fitPending = false; fitAll(); } })
    .onNodeClick(n => select(n.id)).onBackgroundClick(() => select(null))
    .onRenderFramePre(preFrame);
  g2.d3Force('charge').strength(-90).distanceMax(400);
  g2.d3Force('link').distance(l => l.kind === 'file' ? 14 : 38);
}
const nodeCol3 = n => dimmed(n) ? hexA(colorOf(n), 0.15) : colorOf(n);
function nodeVal3(n){
  let v = n.group === 'package' ? 2.2 : n.group === 'doc' ? 1.7 : n.group === 'issue' ? 1.4 : 1;
  if(n.id === sel) v *= 3;
  if(T('t-health') && hasHealth(n)) v *= 2;
  return v;
}
async function ensure3D(){
  if(g3) return;
  if(!window.ForceGraph3D) await loadScript(LIBS.fg3);
  g3 = ForceGraph3D()($('g3'))
    .nodeId('id').backgroundColor(PV.bg).nodeLabel(n => esc(n.title || n.label))
    .nodeColor(nodeCol3).nodeVal(nodeVal3).nodeRelSize(4)
    .linkColor(linkCol3).linkWidth(l => l.kind === 'depends' ? 1 : 0.4)
    .linkDirectionalArrowLength(l => l.kind === 'depends' ? 3.5 : 0).linkDirectionalArrowRelPos(1)
    .showNavInfo(false).d3VelocityDecay(0.35).warmupTicks(0).cooldownTicks(Infinity).cooldownTime(6000)
    .onEngineStop(() => { if(fitPending){ fitPending = false; fitAll(); } })
    .onNodeClick(n => select(n.id)).onBackgroundClick(() => select(null));
  g3.d3Force('charge').strength(-140).distanceMax(450);
  g3.d3Force('link').distance(l => l.kind === 'file' ? 16 : 42);
}
function refreshStyle(){
  if(graph && graph === g3) g3.nodeColor(nodeCol3).nodeVal(nodeVal3).linkColor(linkCol3);
}
let fitPending = false, resizeTimer = 0;
function resize(){
  const el = $(layout === '3d' ? 'g3' : 'g2');
  if(graph) graph.width(el.clientWidth || innerWidth).height(el.clientHeight || innerHeight);
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { if(!sel) fitAll(); }, 250);
}
// Region of the window not covered by the panel / inspector.
function freeRect(){
  const W = innerWidth, H = innerHeight, p = $('panel'), i = $('insp'), pr = p.getBoundingClientRect();
  let x0 = 0, x1 = W, y0 = 0, y1 = H;
  if(W <= 700){ if(!p.hidden) y0 = pr.bottom + 4; if(!i.hidden) y1 = i.getBoundingClientRect().top - 4; }
  else { if(!p.hidden && !p.classList.contains('collapsed')) x0 = pr.right + 10; if(!i.hidden) x1 = i.getBoundingClientRect().left - 10; }
  return {x0, x1: Math.max(x1, x0 + 50), y0, y1: Math.max(y1, y0 + 50)};
}
// Zoom/centre so `ns` fills the free area (2D); 3D uses the engine's fit with overlay padding.
function fitTo(ns, minK){
  ns = ns.filter(n => n.x != null && !isNaN(n.x));
  if(!graph || !ns.length) return;
  const fr = freeRect();
  if(graph === g3){ graph.zoomToFit(400, 60 + Math.max(fr.x0, innerWidth - fr.x1)); return; }
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  ns.forEach(n => { x0 = Math.min(x0, n.x); x1 = Math.max(x1, n.x); y0 = Math.min(y0, n.y); y1 = Math.max(y1, n.y); });
  const fw = fr.x1 - fr.x0, fh = fr.y1 - fr.y0;
  let k = Math.min(fw / Math.max(x1 - x0, 1), fh / Math.max(y1 - y0, 1)) * 0.85;
  k = Math.min(Math.max(k, 0.05), 4); if(minK) k = Math.max(k, minK);
  const dx = (fr.x0 + fr.x1) / 2 - innerWidth / 2, dy = (fr.y0 + fr.y1) / 2 - innerHeight / 2;
  graph.zoom(k, 400); graph.centerAt((x0 + x1) / 2 - dx / k, (y0 + y1) / 2 - dy / k, 400);
}
function fitAll(){ fitTo(sel && focusSet ? curNodes.filter(n => focusSet.has(n.id)) : curNodes); }
function updateCounts(){
  $('counts').textContent = 'showing ' + curNodes.length + ' nodes / ' + curLinks.length + ' edges (of ' + DATA.nodes.length + ' / ' + DATA.edges.length + ')';
}
function render(){
  if(!graph) return;
  const d = build(); curNodes = d.nodes; curLinks = d.links;
  computeFocus();
  graph.cooldownTicks(layout === 'timeline' ? 0 : layout === '3d' ? Infinity : 100);
  graph.graphData(d);
  fitPending = !sel || !!focusSet;
  updateCounts(); refreshStyle();
}
async function setLayout(l){
  if(l === '3d'){
    $('loading').hidden = false;
    try { await new Promise(r => setTimeout(r, 30)); await ensure3D(); $('loading').hidden = true; }
    catch(e){ $('loading').hidden = true; showBanner('3D renderer failed to load (' + e.message + '); staying in the current layout.'); $('layout').value = layout; return; }
  }
  layout = l; $('layout').value = l;
  const is3 = l === '3d';
  $('g2').hidden = is3; $('g3').hidden = !is3;
  if(g2) is3 ? g2.pauseAnimation() : g2.resumeAnimation();
  if(g3) is3 ? g3.resumeAnimation() : g3.pauseAnimation();
  graph = is3 ? g3 : g2;
  if(l === 'timeline') layoutTimeline(); else clearFixed();
  resize(); render();
  if(sel) setTimeout(() => flyTo(byId[sel]), 300); else setTimeout(fitAll, 150);
  writeHash();
}
function showBanner(msg){ $('banner').textContent = msg; $('banner').hidden = false; }

// ---- selection / camera ---------------------------------------------------------
function ensureVisible(n){
  let ch = false;
  const on = id => { const c = $(id); if(!c.checked){ c.checked = true; ch = true; } };
  if(layout === 'timeline' && n.group !== 'package'){ setLayout('2d'); ch = true; }
  if(n.group === 'package'){
    if(layout !== 'timeline') on('t-package');
    if(!F.state[n.state]){ F.state[n.state] = true; $('s-' + n.state).checked = true; ch = true; }
    if(!F.pillar[n.pillar]){ F.pillar[n.pillar] = true; $('p-' + (n.pillar || 'none')).checked = true; ch = true; }
  } else if(n.group === 'doc'){ on('t-doc'); if(n.hub) on('t-hub'); }
  else if(n.group === 'file') on('t-file');
  else on('t-issue');
  if(ch) render();
  return ch;
}
function flyTo(n){
  if(!graph || !n || n.x == null || isNaN(n.x)) return;
  if(focusSet){ fitTo(curNodes.filter(m => focusSet.has(m.id))); return; }
  if(graph === g3){
    const z = n.z || 0, h = Math.hypot(n.x, n.y, z) || 1, r = 1 + 60 / h;
    graph.cameraPosition({x: n.x * r, y: n.y * r, z: z * r}, {x: n.x, y: n.y, z}, 900);
  } else fitTo([n], Math.max(Kz, 2.5));
}
function select(id, o){
  o = o || {};
  const n = id ? byId[id] : null;
  sel = n ? n.id : null;
  let rerendered = false;
  if(n) rerendered = ensureVisible(n);
  if(layout === 'timeline' && !rerendered) render();
  computeFocus(); refreshStyle();
  showInspector(n); writeHash();
  if(n && !o.noCam){ if(rerendered) setTimeout(() => flyTo(n), 450); else setTimeout(() => flyTo(n), 30); }
}
function writeHash(){
  const p = [];
  if(sel) p.push('node=' + encodeURIComponent(sel));
  if(focus !== '0') p.push('focus=' + focus);
  if(layout !== '2d') p.push('layout=' + layout);
  try { history.replaceState(null, '', p.length ? '#' + p.join('&') : location.pathname + location.search); } catch(e) {}
}
function parseHash(){
  const o = {};
  location.hash.replace(/^#/, '').split('&').forEach(kv => {
    const i = kv.indexOf('=');
    if(i > 0){ try { o[kv.slice(0, i)] = decodeURIComponent(kv.slice(i + 1)); } catch(e) {} }
  });
  return o;
}

// ---- inspector ------------------------------------------------------------------
function nlink(o){
  const m = byId[o.id];
  const txt = !m ? o.id : (o.amb && m.group === 'package') ? m.id : m.label;
  return '<a href="#" data-sel="' + esc(o.id) + '">' + esc(txt) + '</a>' + (o.amb ? ' <span class="amb" title="duplicate legacy number: may be any spec sharing it">(ambiguous)</span>' : '');
}
const list = (arr, fn) => arr.length ? '<ul>' + arr.map(x => '<li>' + fn(x) + '</li>').join('') + '</ul>' : '<div class="mute">(none)</div>';
function ghLink(path){ return META.repo && path ? '<a href="' + esc(META.repo + '/blob/main/' + path) + '" target="_blank" rel="noopener">view on GitHub (main)</a>' : ''; }
function prLink(num){ return META.repo ? '<a href="' + esc(META.repo + '/pull/' + num) + '" target="_blank" rel="noopener">#' + num + '</a>' : '#' + num; }
function showInspector(n){
  const el = $('insp');
  if(!n){ el.hidden = true; el.innerHTML = ''; return; }
  const N = nb(n.id);
  let h = '<div class="ih"><span><b>' + esc(n.group === 'package' ? n.num : n.label) + '</b>';
  if(n.group === 'package') h += '<span class="badge" style="background:' + PV[n.state] + '">' + esc(n.state) + '</span>';
  h += '</span><button data-close="1" title="Close (Esc)">&times;</button></div>';
  h += '<div class="it">' + esc(n.title || n.id) + '</div>';
  if(n.group === 'package'){
    h += '<div class="mute">' + ['pillar ' + (n.pillar || '-'), 'track ' + (n.track || '-'), 'effort ' + (n.effort || '-'), n.date ? n.date : 'undated'].map(esc).join(' &middot; ') + '</div>';
    const long = (n.status || '').length > 240;
    h += '<h4>Status</h4><p class="st' + (long ? ' clamp' : '') + '">' + esc(n.status || '(none)') + '</p>' + (long ? '<a href="#" data-more="1">more</a>' : '');
    if(n.goal) h += '<h4>Goal</h4><p class="st">' + esc(n.goal) + '</p>';
    h += '<h4>Depends on</h4>' + list(N.dep, nlink);
    if(n.unresolved.length) h += '<div class="warn">unresolved: ' + esc(n.unresolved.join(', ')) + '</div>';
    h += '<h4>Depended on by</h4>' + list(N.rdep, nlink);
    h += '<h4>Owned files (' + N.file.length + ')</h4>' + (N.file.length ? '<details><summary>show</summary>' + list(N.file, nlink) + '</details>' : '<div class="mute">(none)</div>');
    h += '<h4>Linked docs (' + N.doc.length + ')</h4>' + (N.doc.length ? '<details><summary>show</summary>' + list(N.doc, o => nlink(o) + (byId[o.id] && byId[o.id].hub ? ' <span class="amb">hub</span>' : '')) + '</details>' : '<div class="mute">(none)</div>');
    const known = new Set(N.issue.map(o => byId[o.id] && byId[o.id].label.slice(1)));
    const extra = n.prs.filter(p => !known.has(String(p)));
    h += '<h4>Issues / PRs</h4>' + list(N.issue.map(o => byId[o.id]).filter(Boolean),
      i => '<a href="' + esc(i.url) + '" target="_blank" rel="noopener">' + esc(i.kind === 'pr' ? 'PR ' : 'issue ') + esc(i.label) + '</a> ' + esc(i.title) + ' <span class="amb">' + esc(i.merged ? 'merged' : i.gh_state) + '</span>');
    if(extra.length) h += '<div class="mute">cited in Status: ' + extra.map(prLink).join(', ') + '</div>';
    const hl = [];
    if(n.stale_prs.length) hl.push('<span class="warn">possibly stale: merged PR ' + n.stale_prs.map(prLink).join(', ') + ' names this package but status is ' + esc(n.state) + '</span>');
    if(n.unresolved.length) hl.push('<span class="warn">unresolved dependency tokens</span>');
    if(n.nfiles === 0) hl.push('owns no files');
    if(hl.length) h += '<h4>Health</h4>' + list(hl, x => x);
    h += '<h4>Links</h4>' + ghLink(n.path);
    const cmd = 'python scripts/project_index.py whatis ' + n.num;
    h += '<h4>Index</h4><div class="cmd"><code>' + esc(cmd) + '</code><button data-copy="' + esc(cmd) + '">Copy</button></div>';
  } else if(n.group === 'issue'){
    h += '<div class="mute">' + esc(n.kind) + ' &middot; ' + esc(n.merged ? 'merged' : n.gh_state) + '</div>';
    h += '<p><a href="' + esc(n.url) + '" target="_blank" rel="noopener">open on GitHub</a></p>';
    h += '<h4>Linked packages</h4>' + list(N.issue, nlink);
  } else {
    h += '<div class="mute">' + esc(n.path) + (n.hub ? ' &middot; hub doc (linked to many packages)' : '') + '</div><p>' + ghLink(n.path) + '</p>';
    h += '<h4>Linked packages (' + N[n.group].length + ')</h4><details open><summary>show</summary>' + list(N[n.group], nlink) + '</details>';
  }
  el.innerHTML = h; el.hidden = false; el.scrollTop = 0;
  if(innerWidth < 1100) $('panel').classList.add('collapsed');
}

// ---- search ---------------------------------------------------------------------
const stateRank = n => ACTIVE[n.state] ? 0 : n.state === 'paused' ? 1 : n.state === 'other' ? 2 : n.state === 'done' ? 3 : n.state === 'superseded' ? 4 : 5;
function search(text){
  const terms = text.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if(!terms.length) return [];
  const t0 = terms[0], out = [];
  DATA.nodes.forEach((n, i) => {
    const title = (n.title || '').toLowerCase(), hay = (n.id + ' ' + title + ' ' + (n.path || '') + ' ' + n.label).toLowerCase();
    if(!terms.every(t => hay.includes(t))) return;
    const num = (n.group === 'package' ? n.num : n.label).toLowerCase();
    const m = num === t0 ? 0 : num.startsWith(t0) ? 1 : terms.every(t => title.includes(t)) ? 2 : 3;
    out.push({n, key: [m, n.group === 'package' ? 0 : n.group === 'doc' ? 1 : n.group === 'file' ? 2 : 3, n.group === 'package' ? stateRank(n) : 0, i]});
  });
  out.sort((a, b) => { for(let j = 0; j < 4; j++) if(a.key[j] !== b.key[j]) return a.key[j] - b.key[j]; return 0; });
  return out.slice(0, 15).map(o => o.n);
}
let hits = [];
function showResults(){
  hits = search($('q').value);
  $('res').innerHTML = hits.map((n, i) => '<div class="hit' + (i === 0 ? ' first' : '') + '" data-sel="' + esc(n.id) + '"><b>' + esc(n.group === 'package' ? n.num : n.label) +
    '</b><span class="mute">' + esc((n.title || '').slice(0, 44)) + '</span></div>').join('');
}
function clearSearch(){ $('q').value = ''; showResults(); $('q').blur(); }

// ---- wiring ---------------------------------------------------------------------
function buildFilters(){
  $('states').innerHTML = STATES.map(s => '<label class="chip"><input type="checkbox" id="s-' + s + '" checked><i class="sw" style="background:var(--c-' + s + ')"></i>' + s +
    ' <small>' + PKGS.filter(n => n.state === s).length + '</small></label>').join('');
  $('pillars').innerHTML = PILLARS.map(p => '<label class="chip"><input type="checkbox" id="p-' + (p || 'none') + '" checked>' + (p ? 'P' + p : 'none') + '</label>').join('');
  STATES.forEach(s => $('s-' + s).addEventListener('change', e => {
    F.state[s] = e.target.checked; if(s === 'done') $('t-hidedone').checked = !e.target.checked; render();
  }));
  PILLARS.forEach(p => $('p-' + (p || 'none')).addEventListener('change', e => { F.pillar[p] = e.target.checked; render(); }));
  $('t-hidedone').addEventListener('change', e => { F.state.done = !e.target.checked; $('s-done').checked = !e.target.checked; render(); });
  ['t-package','t-doc','t-file','t-issue','t-dep','t-dedge','t-hub','t-fedge','t-iedge'].forEach(id => $(id).addEventListener('change', render));
  $('t-health').addEventListener('change', () => { refreshStyle(); });
  const c = {stale: PKGS.filter(n => n.stale_prs.length).length, unres: PKGS.filter(n => n.unresolved.length).length, nofile: PKGS.filter(n => n.nfiles === 0).length};
  $('hcounts').innerHTML = '<span style="color:var(--c-stale)">&#9679;</span> possibly stale ' + c.stale + ' &middot; <span style="color:var(--c-unres)">&#9679;</span> unresolved deps ' + c.unres + ' &middot; &#9675; no files ' + c.nofile;
}
function ago(iso){
  if(!iso) return 'never';
  const s = (Date.now() - Date.parse(iso)) / 1000; if(isNaN(s)) return iso;
  return (s < 3600 ? Math.round(s / 60) + ' min' : s < 86400 ? Math.round(s / 3600) + ' h' : Math.round(s / 86400) + ' d') + ' ago';
}
function setFocus(v){ focus = v; $('focus').value = v; computeFocus(); refreshStyle(); writeHash();
  if(sel) setTimeout(() => flyTo(byId[sel]), 30); }
function wireCommon(){
  $('fresh').textContent = 'generated ' + (META.generated || '?') + ' | HEAD ' + (META.head || '?') + ' | gh-sync ' + ago(META.gh_synced_at) +
    ' | ' + DATA.nodes.length + ' nodes, ' + DATA.edges.length + ' edges';
  document.addEventListener('click', e => {
    const a = e.target.closest('[data-sel]'); if(a){ e.preventDefault(); select(a.getAttribute('data-sel')); return; }
    if(e.target.closest('[data-close]')){ select(null); return; }
    const mo = e.target.closest('[data-more]');
    if(mo){ e.preventDefault(); const p = mo.previousElementSibling; mo.textContent = p.classList.toggle('clamp') ? 'more' : 'less'; return; }
    const c = e.target.closest('[data-copy]');
    if(c){ try { navigator.clipboard.writeText(c.getAttribute('data-copy')); c.textContent = 'Copied'; setTimeout(() => c.textContent = 'Copy', 1200); } catch(err) {} }
  });
  $('collapse').addEventListener('click', () => $('panel').classList.toggle('collapsed'));
  $('theme').addEventListener('click', () => {
    const t = effTheme() === 'dark' ? 'light' : 'dark'; document.documentElement.dataset.theme = t;
    try { localStorage.setItem('idx-theme', t); } catch(e) {}
    themeChanged(); if(sel) showInspector(byId[sel]);
  });
  matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => { if(!document.documentElement.dataset.theme) themeChanged(); });
  $('layout').addEventListener('change', e => setLayout(e.target.value));
  $('focus').addEventListener('change', e => setFocus(e.target.value));
  $('q').addEventListener('input', showResults);
  document.addEventListener('keydown', e => {
    const typing = /^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName);
    if(e.key === 'Escape'){ if(document.activeElement === $('q') || $('q').value) clearSearch(); else select(null); return; }
    if(e.key === 'Enter' && document.activeElement === $('q')){ if(hits[0]) select(hits[0].id); return; }
    if(typing || e.ctrlKey || e.metaKey || e.altKey) return;
    if(e.key === '/'){ e.preventDefault(); $('panel').classList.remove('collapsed'); $('q').focus(); $('q').select(); }
    else if(e.key === 'f' || e.key === 'F'){ setFocus(FOCI[(FOCI.indexOf(focus) + 1) % FOCI.length]); }
  });
  window.addEventListener('resize', resize);
  if(window.ResizeObserver){ const ro = new ResizeObserver(resize); ro.observe($('g2')); ro.observe($('g3')); }
  if(innerWidth < 700) $('panel').classList.add('collapsed');
  buildFilters();
}

// ---- offline fallback -----------------------------------------------------------
function offline(err){
  showBanner('Graph renderer failed to load (' + err.message + '). Showing an offline package table built from the embedded data.');
  $('panel').hidden = true; $('insp').hidden = true; $('g2').hidden = true; $('fallback').hidden = false;
  const rows = PKGS.map(n => ({n, hay: (n.id + ' ' + n.title + ' ' + n.state).toLowerCase()}));
  const draw = () => {
    const terms = $('fq').value.toLowerCase().split(/\s+/).filter(Boolean);
    $('ftb').innerHTML = rows.filter(r => terms.every(t => r.hay.includes(t))).map(r =>
      '<tr><td>' + esc(r.n.id) + '</td><td>' + esc(r.n.state) + '</td><td>' + esc(r.n.title) + '</td><td>' + esc(nb(r.n.id).dep.map(o => o.id).join(', ')) + '</td></tr>').join('');
  };
  $('fq').addEventListener('input', draw); draw();
}

async function applyHash(){
  const H = parseHash(), f = H.focus || '0';
  if(FOCI.indexOf(f) >= 0 && f !== focus){ focus = f; $('focus').value = f; }
  const l = ['2d', '3d', 'timeline'].indexOf(H.layout) >= 0 ? H.layout : '2d';
  if(l !== layout) await setLayout(l);
  const id = H.node && byId[H.node] ? H.node : null;
  if(id !== sel) select(id); else { computeFocus(); refreshStyle(); }
}
// ---- start ----------------------------------------------------------------------
(async function start(){
  try { await loadScript(LIBS.fg2); if(!window.ForceGraph) throw new Error('force-graph missing'); }
  catch(e){ offline(e); return; }
  make2D(); graph = g2; wireCommon();
  window.addEventListener('hashchange', applyHash);
  const H = parseHash();
  if(FOCI.indexOf(H.focus) >= 0){ focus = H.focus; $('focus').value = focus; }
  await setLayout(['2d', '3d', 'timeline'].indexOf(H.layout) >= 0 ? H.layout : '2d');
  if(H.node && byId[H.node]) select(H.node);
})();
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
    p_q = sub.add_parser("query", help="search title/body/file paths (scannable)")
    p_q.add_argument("text")
    p_d = sub.add_parser("deps", help="show a package's dependencies")
    p_d.add_argument("num")
    p_o = sub.add_parser("owns", help="which package owns a file path")
    p_o.add_argument("path")
    p_s = sub.add_parser("script", help="canonical script for a task (scripts/README.md)")
    p_s.add_argument("task")
    p_w = sub.add_parser("whatis", help="compact card for one package")
    p_w.add_argument("num")
    p_g = sub.add_parser("graph", help="emit nodes/edges JSON or an HTML node tree")
    p_g.add_argument("--json", dest="json_out")
    p_g.add_argument("--html", dest="html_out")
    sub.add_parser("gh-sync", help="sync GitHub issues/PRs")
    p_l = sub.add_parser("lint", help="lint package specs against TEMPLATE v2")
    p_l.add_argument("paths", nargs="*", metavar="PATH")
    p_l.add_argument("--all", action="store_true", help="lint every package spec")
    p_l.add_argument("--baseline", dest="baseline_path", default=None,
                      help=f"baseline file (default: {DEFAULT_BASELINE_PATH})")
    p_l.add_argument("--no-baseline", action="store_true", help="ignore the baseline; every finding fails")
    p_l.add_argument("--quiet", action="store_true", help="suppress the summary line on success")

    args = ap.parse_args()
    cmd = args.cmd or "build"

    if cmd == "lint":
        # Never touches the DB (must not trigger a rebuild), and an empty
        # target list is a usage error so an empty hook file list can't
        # silently "pass".
        if not args.all and not args.paths:
            print("usage: project_index.py lint [PATH ...] | --all", file=sys.stderr)
            sys.exit(2)
        target_paths = _pkg_files() if args.all else [Path(p) for p in args.paths]
        if args.no_baseline:
            baseline = None
        else:
            baseline_path = Path(args.baseline_path) if args.baseline_path else DEFAULT_BASELINE_PATH
            baseline = _read_baseline(baseline_path)
        sys.exit(lint(target_paths, baseline, quiet=args.quiet))

    # Capture staleness BEFORE connecting: sqlite3.connect() creates an empty
    # file, which would otherwise look "fresh" (mtime=now) but have no tables.
    stale = _db_is_stale()
    if not DB_PATH.exists():
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    db = _connect()

    # Read commands auto-rebuild when a source file is newer than the DB.
    if cmd in ("query", "deps", "owns", "script", "whatis", "graph") and stale:
        build(db)
        print("(index rebuilt)", file=sys.stderr)

    if cmd == "build":
        build(db)
        print(f"indexed {db.execute('SELECT COUNT(*) FROM packages').fetchone()[0]} packages, "
              f"{db.execute('SELECT COUNT(*) FROM docs').fetchone()[0]} docs, "
              f"{db.execute('SELECT COUNT(*) FROM tests').fetchone()[0]} test files -> {DB_PATH}")
    elif cmd == "query":
        query(db, args.text)
    elif cmd == "deps":
        deps(db, args.num)
    elif cmd == "owns":
        owns(db, args.path)
    elif cmd == "script":
        script(db, args.task)
    elif cmd == "whatis":
        whatis(db, args.num)
    elif cmd == "graph":
        graph(db, args.json_out, args.html_out)
    elif cmd == "gh-sync":
        gh_sync(db)
        print(f"synced {db.execute('SELECT COUNT(*) FROM issues').fetchone()[0]} issues/PRs")
    db.close()


if __name__ == "__main__":
    main()
