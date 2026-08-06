#!/usr/bin/env python3
"""Astroray differential lint gate.

Runs a set of deterministic static-analysis / hygiene tools over the files a
change touches, and — by default — reports ONLY findings the change newly
introduces. Pre-existing repository debt therefore never blocks, and a newly
introduced defect cannot hide behind it.

Design mirrors darrencroton/ai-agent-coder's `lint` skill, adapted for this
repo (Windows-first, C++/CUDA + Python + Markdown), and honours the same
non-negotiable invariants:

  * It NEVER installs anything. A missing linter is reported as `unavailable`
    (with an install hint) and counted as a coverage gap — never a silent pass.
  * A linter that crashes is an `error`, never a pass.
  * Nothing is ever auto-fixed.

Differential mode (default): the same tools run over the same files both at the
working tree and at a base ref (checked out into a throwaway detached git
worktree in the system temp dir). A finding is "new" iff its normalized
signature (tool, path, rule, digit-normalized message — line numbers dropped)
is absent from the base set.

Exit codes:  0 clean · 1 new findings · 2 tool error · 3 coverage gap
Precedence when several apply:  error(2) > coverage-gap(3) > findings(1).
(Coverage gaps only force exit 3 when --require-coverage is passed.)

Usage:
  python lint.py check [--base REF] [--all] [--require-coverage] [--paths P ...]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import namedtuple

Finding = namedtuple("Finding", "tool path line rule message")

# Directories whose contents are vendored or generated — never our code.
_EXCLUDE_PARTS = {"third_party", "node_modules", "_deps", ".git", "dist"}


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def _norm_path(p: str) -> str:
    p = p.replace("\\", "/")
    return p[2:] if p.startswith("./") else p


def _norm_msg(msg: str) -> str:
    return re.sub(r"\d+", "#", msg).strip()


def _sig(f: Finding):
    return (f.tool, _norm_path(f.path), f.rule, _norm_msg(f.message))


def _excluded(path: str) -> bool:
    parts = _norm_path(path).split("/")
    if parts and parts[0].startswith("build"):
        return True
    if len(parts) >= 2 and parts[0] == ".claude" and parts[1] == "worktrees":
        return True
    return any(part in _EXCLUDE_PARTS for part in parts)


def _wrap(exe: str, args):
    """Windows can't CreateProcess a .cmd/.bat directly — route via cmd /c."""
    if os.name == "nt" and exe.lower().endswith((".cmd", ".bat")):
        return ["cmd", "/c", exe, *args]
    return [exe, *args]


def _run(cmd, cwd=None):
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        return r.returncode, r.stdout or "", r.stderr or ""
    except FileNotFoundError:
        return None, "", ""


def _chunks(seq, n=150):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _git(args, cwd=None):
    rc, out, _ = _run(["git", *args], cwd=cwd)
    return out if rc == 0 else ""


# --------------------------------------------------------------------------- #
# per-tool output parsers  (return list[(path, line, rule, message)])
# --------------------------------------------------------------------------- #
def _p_ruff(rc, out, err):
    try:
        data = json.loads(out or "[]")
    except json.JSONDecodeError:
        return []
    res = []
    for it in data:
        loc = it.get("location") or {}
        res.append((it.get("filename", "?"), loc.get("row", 0),
                    it.get("code") or "ruff", it.get("message", "").strip()))
    return res


def _p_cppcheck(rc, out, err):
    res = []
    for line in (err + "\n" + out).splitlines():
        parts = line.split("|||")
        if len(parts) == 5:
            f, ln, _sev, rid, msg = parts
            res.append((f, ln, rid, msg.strip()))
    return res


def _p_clang_format(rc, out, err):
    res = []
    pat = re.compile(r"^(?P<p>.+?):(?P<l>\d+):\d+:\s+warning:\s+(?P<m>.*)$")
    for line in err.splitlines():
        m = pat.match(line)
        if m:
            res.append((m["p"], m["l"], "clang-format", m["m"].strip()))
    return res


def _p_markdownlint(rc, out, err):
    res = []
    pat = re.compile(r"^(?P<p>.+?):(?P<l>\d+)(?::\d+)?\s+(?P<r>MD\d+)\S*\s+(?P<m>.*)$")
    for line in (err + "\n" + out).splitlines():
        m = pat.match(line.strip())
        if m:
            res.append((m["p"], m["l"], m["r"], m["m"].strip()))
    return res


def _p_codespell(rc, out, err):
    res = []
    pat = re.compile(r"^(?P<p>.+?):(?P<l>\d+):\s+(?P<m>.*)$")
    for line in out.splitlines():
        m = pat.match(line)
        if m:
            res.append((m["p"], m["l"], "spelling", m["m"].strip()))
    return res


def _p_shellcheck(rc, out, err):
    try:
        data = json.loads(out or "{}")
    except json.JSONDecodeError:
        return []
    res = []
    for c in data.get("comments", []):
        res.append((c.get("file", "?"), c.get("line", 0),
                    f"SC{c.get('code', '')}", (c.get("message") or "").strip()))
    return res


# --------------------------------------------------------------------------- #
# tool registry
# --------------------------------------------------------------------------- #
CPP_EXTS = {".cpp", ".cc", ".cxx", ".hpp", ".hh", ".h"}

TOOLS = [
    dict(name="ruff", exe="ruff", exts={".py"}, ok={0, 1}, parse=_p_ruff,
         hint="pip install ruff",
         cmd=lambda fs: _wrap(shutil.which("ruff"),
                              ["check", "--quiet", "--output-format=json", *fs])),
    dict(name="cppcheck", exe="cppcheck", exts=set(CPP_EXTS), ok={0}, parse=_p_cppcheck,
         hint="choco install cppcheck  /  apt install cppcheck",
         cmd=lambda fs: _wrap(shutil.which("cppcheck"),
                              ["--enable=warning,style,performance,portability",
                               "--inline-suppr", "--suppress=missingIncludeSystem",
                               "--quiet",
                               "--template={file}|||{line}|||{severity}|||{id}|||{message}",
                               *fs])),
    dict(name="clang-format", exe="clang-format", exts=CPP_EXTS | {".cu", ".cuh"},
         ok={0, 1}, parse=_p_clang_format,
         hint="choco install llvm  /  apt install clang-format",
         needs_root=".clang-format",
         cmd=lambda fs: _wrap(shutil.which("clang-format"),
                              ["--dry-run", "--Werror", *fs])),
    dict(name="markdownlint", exe="markdownlint-cli2", exts={".md"}, ok={0, 1},
         parse=_p_markdownlint, hint="npm install -g markdownlint-cli2",
         cmd=lambda fs: _wrap(shutil.which("markdownlint-cli2"), [*fs])),
    dict(name="codespell", exe="codespell",
         exts={".py", ".md", ".rst", ".txt", ".toml", ".cpp", ".cc", ".cxx",
               ".hpp", ".h", ".cu", ".cuh"},
         ok={0, 65}, parse=_p_codespell, hint="pip install codespell",
         cmd=lambda fs: _wrap(shutil.which("codespell"), [*fs])),
    dict(name="shellcheck", exe="shellcheck", exts={".sh", ".bash"}, ok={0, 1},
         parse=_p_shellcheck, hint="choco install shellcheck  /  apt install shellcheck",
         cmd=lambda fs: _wrap(shutil.which("shellcheck"), ["--format=json1", *fs])),
]

# language -> the tools that provide any coverage for it (for gap reporting)
COVERAGE = {
    "python": ({".py"}, ["ruff"]),
    "c++": (CPP_EXTS, ["cppcheck", "clang-format"]),
    "cuda": ({".cu", ".cuh"}, ["clang-format"]),
    "markdown": ({".md"}, ["markdownlint"]),
    "shell": ({".sh", ".bash"}, ["shellcheck"]),
}


# --------------------------------------------------------------------------- #
# running one tool over a file set in a given tree
# --------------------------------------------------------------------------- #
def run_tool(tool, files, root):
    """Returns (status, findings) with status in ok/unavailable/skipped/error."""
    applicable = sorted(f for f in files if os.path.splitext(f)[1].lower() in tool["exts"])
    applicable = [f for f in applicable if os.path.exists(os.path.join(root, f))]
    if not applicable:
        return "n/a", []
    if tool.get("needs_root") and not os.path.exists(os.path.join(root, tool["needs_root"])):
        return "skipped", []
    if shutil.which(tool["exe"]) is None:
        return "unavailable", []

    findings, errored = [], False
    for batch in _chunks(applicable):
        rc, out, err = _run(tool["cmd"](batch), cwd=root)
        if rc is None:
            return "unavailable", []
        raw = tool["parse"](rc, out, err)
        if rc not in tool["ok"] and not raw:
            errored = True
        for (p, ln, rule, msg) in raw:
            # Relativize absolute tool output against the tree it ran in
            # (root here is either the real repo or the throwaway base
            # worktree). Without this, base signatures carry the temp-worktree
            # path prefix and can never match head signatures, so the
            # differential silently subtracts nothing for absolute-path
            # emitters like ruff on Windows.
            if os.path.isabs(p):
                try:
                    p = os.path.relpath(p, root)
                except ValueError:
                    pass  # different drive — keep as-is
            findings.append(Finding(tool["name"], _norm_path(p), str(ln), rule, msg))
    return ("error" if errored else "ok"), findings


def git_diff_check(root, base):
    """Whitespace / conflict-marker errors introduced vs base (already differential)."""
    target = base if base else "HEAD"
    rc, out, err = _run(["git", "diff", "--check", target], cwd=root)
    if rc is None:
        return []
    res, pat = [], re.compile(r"^(?P<p>.+?):(?P<l>\d+):\s+(?P<m>.*)$")
    for line in (out + "\n" + err).splitlines():
        m = pat.match(line)
        if m and not _excluded(m["p"]):
            res.append(Finding("git-diff-check", _norm_path(m["p"]), m["l"],
                               "whitespace", m["m"].strip()))
    return res


# --------------------------------------------------------------------------- #
# changed-file discovery
# --------------------------------------------------------------------------- #
def resolve_base(root, requested):
    if requested:
        if _git(["rev-parse", "--verify", "--quiet", requested], cwd=root).strip():
            return requested
        print(f"warning: base ref '{requested}' not found; running non-differential",
              file=sys.stderr)
        return None
    for cand in ("origin/main", "main"):
        if _git(["rev-parse", "--verify", "--quiet", cand], cwd=root).strip():
            return cand
    return None


def changed_files(root, base, all_tracked, explicit):
    if explicit:
        raw = explicit
    elif all_tracked:
        raw = _git(["ls-files"], cwd=root).splitlines()
    else:
        diff_target = [base] if base else ["HEAD"]
        raw = _git(["diff", "--name-only", "--diff-filter=ACMR", *diff_target],
                   cwd=root).splitlines()
        raw += _git(["ls-files", "--others", "--exclude-standard"], cwd=root).splitlines()
    seen, out = set(), []
    for f in raw:
        f = _norm_path(f.strip())
        if not f or f in seen or _excluded(f):
            continue
        if not os.path.exists(os.path.join(root, f)):
            continue
        seen.add(f)
        out.append(f)
    return out


# --------------------------------------------------------------------------- #
# base-tree signatures via throwaway worktree
# --------------------------------------------------------------------------- #
def base_signatures(root, base, files):
    wt = tempfile.mkdtemp(prefix="astroray-lint-base-")
    try:
        rc, _o, err = _run(["git", "worktree", "add", "--detach", wt, base], cwd=root)
        if rc != 0:
            print(f"warning: could not create base worktree ({err.strip()}); "
                  "treating all findings as new", file=sys.stderr)
            return set()
        present = [f for f in files if os.path.exists(os.path.join(wt, f))]
        sigs = set()
        for tool in TOOLS:
            status, findings = run_tool(tool, present, wt)
            if status == "ok":
                sigs.update(_sig(f) for f in findings)
        return sigs
    finally:
        _run(["git", "worktree", "remove", "--force", wt], cwd=root)
        _run(["git", "worktree", "prune"], cwd=root)
        shutil.rmtree(wt, ignore_errors=True)


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #
C = dict(dim="\033[2m", red="\033[31m", grn="\033[32m", yel="\033[33m",
         cyn="\033[36m", bold="\033[1m", off="\033[0m")
# Only emit ANSI to an interactive terminal — never into captured/piped output.
if not (hasattr(sys.stdout, "isatty") and sys.stdout.isatty()) or os.environ.get("TERM") == "dumb":
    C = {k: "" for k in C}


def report(base, files, tool_status, new_findings, gaps, mode):
    print(f"\n{C['bold']}Astroray lint — {mode}{C['off']}")
    print(f"  base: {base or '(none)'}    changed files: {len(files)}\n")

    order = ["ok", "error", "unavailable", "skipped", "n/a"]
    for tool in TOOLS + [dict(name="git-diff-check")]:
        st = tool_status.get(tool["name"], "n/a")
        if st == "n/a":
            continue
        n = sum(1 for f in new_findings if f.tool == tool["name"])
        col = {"ok": C["grn"] if n == 0 else C["yel"], "error": C["red"],
               "unavailable": C["dim"], "skipped": C["dim"]}.get(st, "")
        extra = ""
        if st == "unavailable":
            hint = next((t.get("hint") for t in TOOLS if t["name"] == tool["name"]), "")
            extra = f"  ({hint})"
        elif st == "skipped":
            need = next((t.get("needs_root") for t in TOOLS if t["name"] == tool["name"]), "")
            extra = f"  (no root {need})"
        elif st == "ok":
            extra = f"  {n} new finding(s)"
        elif st == "error":
            extra = "  tool crashed — treat as unchecked"
        print(f"  {col}{tool['name']:<16}{st:<12}{C['off']}{extra}")

    if new_findings:
        print(f"\n{C['bold']}New findings{C['off']}")
        by_file = {}
        for f in new_findings:
            by_file.setdefault(f.path, []).append(f)
        for path in sorted(by_file):
            print(f"  {C['cyn']}{path}{C['off']}")
            for f in sorted(by_file[path], key=lambda x: int(x.line) if x.line.isdigit() else 0):
                print(f"    {f.line:>5}  {C['dim']}[{f.tool}/{f.rule}]{C['off']} {f.message}")

    if gaps:
        print(f"\n{C['yel']}Coverage gaps{C['off']} (a changed language has no available linter):")
        for lang, hint in gaps:
            print(f"  {lang:<10} {C['dim']}{hint}{C['off']}")

    print(f"\n{C['bold']}Summary:{C['off']} {len(new_findings)} new finding(s), "
          f"{sum(1 for s in tool_status.values() if s == 'ok')} tool(s) ran, "
          f"{sum(1 for s in tool_status.values() if s == 'unavailable')} unavailable, "
          f"{sum(1 for s in tool_status.values() if s == 'error')} errored\n")


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def cmd_check(args):
    root = _git(["rev-parse", "--show-toplevel"]).strip() or os.getcwd()
    base = None if args.all else resolve_base(root, args.base)
    files = changed_files(root, base, args.all, [_norm_path(p) for p in (args.paths or [])])

    if not files:
        print("\nAstroray lint: no changed source files to check.\n")
        return 0

    differential = base is not None and not args.all
    mode = f"differential vs {base}" if differential else ("full tree" if args.all else "working tree")

    base_sigs = base_signatures(root, base, files) if differential else set()

    tool_status, new_findings, errored_any = {}, [], False
    for tool in TOOLS:
        status, findings = run_tool(tool, files, root)
        tool_status[tool["name"]] = status
        if status == "error":
            errored_any = True
        if status == "ok":
            for f in findings:
                if _sig(f) not in base_sigs:
                    new_findings.append(f)

    gdc = git_diff_check(root, base)
    if gdc:
        tool_status["git-diff-check"] = "ok"
        new_findings.extend(gdc)
    else:
        tool_status["git-diff-check"] = "ok"

    # coverage gaps: a changed language whose every tool is unavailable
    changed_exts = {os.path.splitext(f)[1].lower() for f in files}
    gaps = []
    for lang, (exts, tools) in COVERAGE.items():
        if changed_exts & exts:
            statuses = [tool_status.get(t) for t in tools]
            if all(s in ("unavailable", "skipped", None) for s in statuses):
                hint = next((t.get("hint") for t in TOOLS if t["name"] in tools), "")
                gaps.append((lang, hint))

    report(base, files, tool_status, new_findings, gaps, mode)

    if errored_any:
        return 2
    if gaps and args.require_coverage:
        return 3
    if new_findings:
        return 1
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # `check` is the only (and default) subcommand — inject it if omitted.
    if not argv or argv[0] not in ("check", "-h", "--help"):
        argv = ["check", *argv]

    ap = argparse.ArgumentParser(prog="lint.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="sub")
    c = sub.add_parser("check", help="run the differential lint gate")
    c.add_argument("--base", help="base ref to diff against (default: origin/main then main)")
    c.add_argument("--all", action="store_true",
                  help="lint the whole tracked tree (non-differential)")
    c.add_argument("--require-coverage", action="store_true",
                  help="exit 3 if a changed language has no available linter")
    c.add_argument("--paths", nargs="*", help="explicit files to lint instead of the changeset")
    c.set_defaults(func=cmd_check)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
