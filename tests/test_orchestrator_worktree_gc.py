"""Unit tests for safe merged-worktree auto-GC (pkg97 Phase 1)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import json
import subprocess
from unittest.mock import patch, MagicMock, call
from roadmap_orchestrator.state import gc_merged_worktrees


def test_squash_merge_case():
    """Squash-merge: PR MERGED, branch tip NOT ancestor, mergeCommit IS in main → remove."""
    worktrees_dir = ".claude/worktrees"
    ledger = {}

    # Mock git worktree list
    wt_list_output = """worktree /repo/.claude/worktrees/pkg97
HEAD abc1234
branch refs/heads/pkg97-test

"""

    # Mock gh pr view (MERGED squash)
    pr_view_output = json.dumps({
        "state": "MERGED",
        "mergeCommit": {"oid": "def5678"},
        "mergedAt": "2026-05-21T12:00:00Z",
        "number": 123
    })

    with patch("subprocess.check_output") as mock_check,          patch("subprocess.call") as mock_call,          patch("subprocess.check_call") as mock_check_call:

        # Setup mocks
        def check_output_side_effect(cmd, **kwargs):
            if cmd[0] == "git" and cmd[1] == "worktree" and cmd[2] == "list":
                return wt_list_output
            elif cmd[0] == "gh" and cmd[1] == "pr" and cmd[2] == "view":
                return pr_view_output
            elif cmd[0] == "git" and "-C" in cmd and "status" in cmd:
                return ""  # Clean worktree
            elif cmd[0] == "git" and "-C" in cmd and "log" in cmd:
                return ""  # No unpushed commits
            raise subprocess.CalledProcessError(1, cmd)

        mock_check.side_effect = check_output_side_effect

        # merge-base calls: branch tip NOT ancestor, mergeCommit IS ancestor
        def call_side_effect(cmd, **kwargs):
            if "merge-base" in cmd and "--is-ancestor" in cmd:
                if "abc1234" in cmd:
                    return 1  # Branch tip not in main
                elif "def5678" in cmd:
                    return 0  # Merge commit in main
            return 0

        mock_call.side_effect = call_side_effect

        # git worktree remove succeeds; git branch -d fails (squash), -D succeeds
        def check_call_side_effect(cmd, **kwargs):
            if "branch" in cmd and "-d" in cmd:
                raise subprocess.CalledProcessError(1, cmd, "error: branch not fully merged")
            return None  # worktree remove and branch -D succeed

        mock_check_call.side_effect = check_call_side_effect

        result = gc_merged_worktrees(worktrees_dir, ledger)

        # Should succeed with force delete justified by squash
        assert len(result["removed"]) == 1
        assert "#123" in result["removed"][0]
        assert "force delete" in result["removed"][0].lower()
        assert "def5678" in result["removed"][0]  # Merge commit cited
        assert len(result["escalations"]) == 0


def test_normal_merge_case():
    """Normal merge: PR MERGED, branch tip IS ancestor → safe delete."""
    worktrees_dir = ".claude/worktrees"
    ledger = {}

    wt_list_output = """worktree /repo/.claude/worktrees/pkg98
HEAD fed4321
branch refs/heads/pkg98-test

"""

    pr_view_output = json.dumps({
        "state": "MERGED",
        "mergeCommit": {"oid": "aaa1111"},
        "mergedAt": "2026-05-21T12:00:00Z",
        "number": 124
    })

    with patch("subprocess.check_output") as mock_check, \
         patch("subprocess.call") as mock_call, \
         patch("subprocess.check_call") as mock_check_call:

        def check_output_side_effect(cmd, **kwargs):
            if cmd[0] == "git" and cmd[1] == "worktree" and cmd[2] == "list":
                return wt_list_output
            elif cmd[0] == "gh":
                return pr_view_output
            elif cmd[0] == "git" and "-C" in cmd and "status" in cmd:
                return ""
            elif cmd[0] == "git" and "-C" in cmd and "log" in cmd:
                return ""
            raise subprocess.CalledProcessError(1, cmd)

        mock_check.side_effect = check_output_side_effect

        # Branch tip IS ancestor of main
        mock_call.return_value = 0

        mock_check_call.return_value = None

        result = gc_merged_worktrees(worktrees_dir, ledger)

        assert len(result["removed"]) == 1
        assert "#124" in result["removed"][0]
        assert "safe delete" in result["removed"][0].lower()
        assert len(result["escalations"]) == 0


def test_open_pr_case():
    """Open PR: state != MERGED → escalate, do not delete."""
    worktrees_dir = ".claude/worktrees"
    ledger = {}

    wt_list_output = """worktree /repo/.claude/worktrees/pkg99
HEAD ccc3333
branch refs/heads/pkg99-test

"""

    pr_view_output = json.dumps({
        "state": "OPEN",
        "number": 125
    })

    with patch("subprocess.check_output") as mock_check, \
         patch("subprocess.call") as mock_call, \
         patch("subprocess.check_call") as mock_check_call:

        def check_output_side_effect(cmd, **kwargs):
            if cmd[0] == "git" and cmd[1] == "worktree" and cmd[2] == "list":
                return wt_list_output
            elif cmd[0] == "gh":
                return pr_view_output
            raise subprocess.CalledProcessError(1, cmd)

        mock_check.side_effect = check_output_side_effect

        result = gc_merged_worktrees(worktrees_dir, ledger)

        assert len(result["removed"]) == 0
        assert len(result["escalations"]) == 1
        assert "#125" in result["escalations"][0]
        assert "not MERGED" in result["escalations"][0]


def test_no_pr_case():
    """No PR for branch → escalate (pkg93 trap), never force-delete."""
    worktrees_dir = ".claude/worktrees"
    ledger = {}

    wt_list_output = """worktree /repo/.claude/worktrees/pkg100
HEAD ddd4444
branch refs/heads/pkg100-test

"""

    with patch("subprocess.check_output") as mock_check, \
         patch("subprocess.call") as mock_call, \
         patch("subprocess.check_call") as mock_check_call:

        def check_output_side_effect(cmd, **kwargs):
            if cmd[0] == "git" and cmd[1] == "worktree" and cmd[2] == "list":
                return wt_list_output
            elif cmd[0] == "gh":
                raise subprocess.CalledProcessError(1, cmd)  # No PR
            raise subprocess.CalledProcessError(1, cmd)

        mock_check.side_effect = check_output_side_effect

        result = gc_merged_worktrees(worktrees_dir, ledger)

        assert len(result["removed"]) == 0
        assert len(result["escalations"]) == 1
        assert "pkg100-test" in result["escalations"][0]
        assert "no pr" in result["escalations"][0].lower()


def test_dirty_worktree_case():
    """Dirty worktree: MERGED + in main but uncommitted changes → escalate."""
    worktrees_dir = ".claude/worktrees"
    ledger = {}

    wt_list_output = """worktree /repo/.claude/worktrees/pkg101
HEAD eee5555
branch refs/heads/pkg101-test

"""

    pr_view_output = json.dumps({
        "state": "MERGED",
        "mergeCommit": {"oid": "fff6666"},
        "mergedAt": "2026-05-21T12:00:00Z",
        "number": 126
    })

    with patch("subprocess.check_output") as mock_check, \
         patch("subprocess.call") as mock_call, \
         patch("subprocess.check_call") as mock_check_call:

        def check_output_side_effect(cmd, **kwargs):
            if cmd[0] == "git" and cmd[1] == "worktree" and cmd[2] == "list":
                return wt_list_output
            elif cmd[0] == "gh":
                return pr_view_output
            elif cmd[0] == "git" and "-C" in cmd and "status" in cmd:
                return " M scripts/something.py\n"  # Uncommitted changes
            raise subprocess.CalledProcessError(1, cmd)

        mock_check.side_effect = check_output_side_effect
        mock_call.return_value = 0  # merge-base passes

        result = gc_merged_worktrees(worktrees_dir, ledger)

        assert len(result["removed"]) == 0
        assert len(result["escalations"]) == 1
        assert "#126" in result["escalations"][0]
        assert "uncommitted" in result["escalations"][0].lower()


def test_unpushed_commits_case():
    """Unpushed commits: MERGED + in main but commits ahead of upstream → escalate."""
    worktrees_dir = ".claude/worktrees"
    ledger = {}

    wt_list_output = """worktree /repo/.claude/worktrees/pkg102
HEAD ggg7777
branch refs/heads/pkg102-test

"""

    pr_view_output = json.dumps({
        "state": "MERGED",
        "mergeCommit": {"oid": "hhh8888"},
        "mergedAt": "2026-05-21T12:00:00Z",
        "number": 127
    })

    with patch("subprocess.check_output") as mock_check, \
         patch("subprocess.call") as mock_call, \
         patch("subprocess.check_call") as mock_check_call:

        def check_output_side_effect(cmd, **kwargs):
            if cmd[0] == "git" and cmd[1] == "worktree" and cmd[2] == "list":
                return wt_list_output
            elif cmd[0] == "gh":
                return pr_view_output
            elif cmd[0] == "git" and "-C" in cmd and "status" in cmd:
                return ""  # Clean
            elif cmd[0] == "git" and "-C" in cmd and "log" in cmd:
                return "abc1234 Some unpushed commit\n"  # Has unpushed
            raise subprocess.CalledProcessError(1, cmd)

        mock_check.side_effect = check_output_side_effect
        mock_call.return_value = 0

        result = gc_merged_worktrees(worktrees_dir, ledger)

        assert len(result["removed"]) == 0
        assert len(result["escalations"]) == 1
        assert "#127" in result["escalations"][0]
        assert "unpushed" in result["escalations"][0].lower()


def test_content_not_in_main():
    """PR MERGED but merge commit not in origin/main → escalate."""
    worktrees_dir = ".claude/worktrees"
    ledger = {}

    wt_list_output = """worktree /repo/.claude/worktrees/pkg104
HEAD kkk1111
branch refs/heads/pkg104-test

"""

    pr_view_output = json.dumps({
        "state": "MERGED",
        "mergeCommit": {"oid": "lll2222"},
        "mergedAt": "2026-05-21T12:00:00Z",
        "number": 129
    })

    with patch("subprocess.check_output") as mock_check, \
         patch("subprocess.call") as mock_call, \
         patch("subprocess.check_call") as mock_check_call:

        def check_output_side_effect(cmd, **kwargs):
            if cmd[0] == "git" and cmd[1] == "worktree" and cmd[2] == "list":
                return wt_list_output
            elif cmd[0] == "gh":
                return pr_view_output
            elif cmd[0] == "git" and "-C" in cmd and "status" in cmd:
                return ""
            elif cmd[0] == "git" and "-C" in cmd and "log" in cmd:
                return ""
            raise subprocess.CalledProcessError(1, cmd)

        mock_check.side_effect = check_output_side_effect

        # Both merge-base checks fail
        mock_call.return_value = 1

        result = gc_merged_worktrees(worktrees_dir, ledger)

        assert len(result["removed"]) == 0
        assert len(result["escalations"]) == 1
        assert "#129" in result["escalations"][0]
        assert "not in origin/main" in result["escalations"][0]
