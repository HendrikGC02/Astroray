import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from roadmap_orchestrator.queue import pkg_of, order_hw_queue

PRIORITY = ["pkg94", "pkg95", "pkg96"]

def _pr(n, title, created):
    return {"number": n, "title": title, "headRefName": "b", "createdAt": created}

def test_pkg_of_matches_title_token():
    assert pkg_of(_pr(1, "feat: pkg95 camera", "x"), PRIORITY) == "pkg95"

def test_pkg_of_none_when_unknown():
    assert pkg_of(_pr(2, "chore: tidy", "x"), PRIORITY) is None

def test_order_by_priority_then_created():
    prs = {
        1: _pr(1, "pkg96 work", "2026-01-01T00:00:00Z"),
        2: _pr(2, "pkg94 work", "2026-01-03T00:00:00Z"),
        3: _pr(3, "unknown",    "2026-01-02T00:00:00Z"),
        4: _pr(4, "pkg94 also", "2026-01-01T00:00:00Z"),
    }
    # pkg94 (idx0) before pkg96 (idx2) before unknown; within pkg94 older createdAt first
    assert order_hw_queue([1, 2, 3, 4], prs, PRIORITY) == [4, 2, 1, 3]
