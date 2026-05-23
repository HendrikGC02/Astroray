"""Persisted debounce + SHA-bound hardware-result ledger."""
import json, os
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_ledger(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_ledger(path: str, ledger: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


def _entry(ledger: dict, number: int) -> dict:
    return ledger.setdefault(str(number), {})


def record_hw_result(ledger, number, head_sha, result, numbers, artifact):
    e = _entry(ledger, number)
    e.update(head_sha=head_sha, hw_result=result, hw_numbers=numbers,
             hw_artifact=artifact, last_action="hw_recorded", last_action_ts=_now())


def record_action(ledger, number, action):
    e = _entry(ledger, number)
    e.update(last_action=action, last_action_ts=_now())


def expire_closed(ledger: dict, open_numbers: set) -> None:
    for k in [k for k in ledger if str(k).isdigit() and int(k) not in open_numbers]:
        del ledger[k]


def gc_merged_worktrees(worktrees_dir: str, ledger: dict) -> dict:
    """Remove merged-package worktrees + branches. Returns GC report with escalations.

    Gates (all must hold):
    (a) PR is MERGED per gh pr view
    (b) Content in main (branch ancestor OR mergeCommit ancestor, squash-aware)
    (c) Zero uncommitted + zero unpushed changes in worktree

    Anything not provably safe → escalate, never force-delete.
    Design: pkg97 § Phase 1.
    """
    import subprocess, re, json as json_module

    removed = []
    escalations = []

    # List all worktrees under .claude/worktrees/
    try:
        wt_out = subprocess.check_output(
            ["git", "worktree", "list", "--porcelain"], text=True, stderr=subprocess.DEVNULL
        )
    except subprocess.CalledProcessError:
        return {"removed": removed, "escalations": escalations}

    # Parse worktree list: each entry is "worktree <path>\nHEAD <sha>\nbranch <ref>\n\n"
    wt_entries = []
    for block in wt_out.strip().split("\n\n"):
        lines = block.strip().split("\n")
        entry = {}
        for line in lines:
            if line.startswith("worktree "):
                entry["path"] = line.split(None, 1)[1]
            elif line.startswith("HEAD "):
                entry["head"] = line.split(None, 1)[1]
            elif line.startswith("branch "):
                ref = line.split(None, 1)[1]
                entry["branch"] = ref.replace("refs/heads/", "")
        if "path" in entry and "branch" in entry:
            wt_entries.append(entry)

    for wt in wt_entries:
        path = wt["path"]
        branch = wt["branch"]

        # Only process package worktrees under .claude/worktrees/
        if ".claude/worktrees/" not in path.replace("\\", "/"):
            continue

        # Extract package name from branch (e.g., pkg97-orchestrator-autogc → pkg97)
        pkg_match = re.match(r"(pkg\d+)", branch)
        if not pkg_match:
            continue

        head_sha = wt.get("head", "")

        # Gate (a): PR is MERGED
        try:
            pr_json = subprocess.check_output(
                ["gh", "pr", "view", branch, "--json",
                 "state,mergeCommit,mergedAt,number"],
                text=True, stderr=subprocess.DEVNULL
            )
            pr_data = json_module.loads(pr_json)
        except (subprocess.CalledProcessError, json_module.JSONDecodeError):
            escalations.append(f"{branch}: no PR or PR query failed → skip")
            continue

        if pr_data.get("state") != "MERGED":
            escalations.append(f"#{pr_data.get('number', '?')} ({branch}): PR not MERGED (state={pr_data.get('state')}) → skip")
            continue

        merge_commit = pr_data.get("mergeCommit", {}).get("oid")
        if not merge_commit:
            escalations.append(f"#{pr_data['number']} ({branch}): PR MERGED but no mergeCommit SHA → skip")
            continue

        # Gate (b): Content in main (squash-aware)
        # First check: branch tip is ancestor of origin/main
        branch_in_main = subprocess.call(
            ["git", "merge-base", "--is-ancestor", head_sha, "origin/main"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ) == 0

        # Second check: mergeCommit is ancestor of origin/main (squash case)
        merge_in_main = subprocess.call(
            ["git", "merge-base", "--is-ancestor", merge_commit, "origin/main"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ) == 0

        if not (branch_in_main or merge_in_main):
            escalations.append(f"#{pr_data['number']} ({branch}): PR MERGED but content not in origin/main → skip")
            continue

        # Gate (c): Zero uncommitted + zero unpushed
        try:
            status_out = subprocess.check_output(
                ["git", "-C", path, "status", "--porcelain"],
                text=True, stderr=subprocess.DEVNULL
            ).strip()
            if status_out:
                escalations.append(f"#{pr_data['number']} ({branch}): uncommitted changes in worktree → skip")
                continue

            # Check unpushed commits (requires upstream)
            try:
                unpushed = subprocess.check_output(
                    ["git", "-C", path, "log", "--oneline", "@{upstream}..HEAD"],
                    text=True, stderr=subprocess.DEVNULL
                ).strip()
                if unpushed:
                    escalations.append(f"#{pr_data['number']} ({branch}): unpushed commits in worktree → skip")
                    continue
            except subprocess.CalledProcessError:
                # No upstream configured
                escalations.append(f"#{pr_data['number']} ({branch}): no upstream configured → skip")
                continue
        except subprocess.CalledProcessError:
            escalations.append(f"#{pr_data['number']} ({branch}): git status failed → skip")
            continue

        # All gates passed → safe to remove
        pr_num = pr_data["number"]

        # Remove worktree (NOT --force)
        wt_remove_ok = False
        try:
            subprocess.check_call(
                ["git", "worktree", "remove", path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            wt_remove_ok = True
        except subprocess.CalledProcessError:
            # Check if it's de-registered despite filesystem error (OneDrive footgun)
            wt_list = subprocess.check_output(
                ["git", "worktree", "list", "--porcelain"], text=True
            )
            if path not in wt_list:
                wt_remove_ok = True
                escalations.append(f"#{pr_num} ({branch}): worktree de-registered but physical dir cleanup needed at {path}")
            else:
                escalations.append(f"#{pr_num} ({branch}): git worktree remove failed and worktree still registered → skip branch delete")
                continue

        if not wt_remove_ok:
            continue

        # Remove branch (safe delete first; force only if squash-merged)
        try:
            subprocess.check_call(
                ["git", "branch", "-d", branch],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            removed.append(f"#{pr_num} ({branch}): worktree + branch removed (safe delete)")
        except subprocess.CalledProcessError:
            # Safe delete refused; try force delete ONLY if squash case
            if merge_in_main and not branch_in_main:
                # Squash merge: branch tip not ancestor but mergeCommit is
                try:
                    subprocess.check_call(
                        ["git", "branch", "-D", branch],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                    )
                    removed.append(f"#{pr_num} ({branch}): worktree + branch removed (force delete justified by squash merge {merge_commit[:8]})")
                except subprocess.CalledProcessError:
                    escalations.append(f"#{pr_num} ({branch}): git branch -D failed even after worktree removal")
            else:
                escalations.append(f"#{pr_num} ({branch}): git branch -d refused and not a squash case → branch still exists")

        # Prune stale refs
        subprocess.call(["git", "worktree", "prune"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    return {"removed": removed, "escalations": escalations}
