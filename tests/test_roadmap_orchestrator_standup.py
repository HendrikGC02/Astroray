import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from roadmap_orchestrator.standup import render_standup, upsert_standup, finalize_previous

PLAN = {"dispatch": ["pkg94"], "fixers": [{"pr": 5, "kind": "ci"}],
        "hw_dispatch": 7, "merges": [3], "hw_failed": [9],
        "buckets": {"in_progress": [11], "rebase_needed": [], "ci_failing": [5],
                    "hw_untested": [7], "hw_failed": [9], "ready": [3]}}

def test_render_contains_all_sections():
    md = render_standup(PLAN, gpu_holder=None, hw_queue=[7])
    for h in ["Shipped today", "In-flight", "Blocked", "Hardware gate",
              "CI under repair", "Action items"]:
        assert h in md
    assert "pkg94" in md and "#3" in md and "#9" in md
    assert "debt ledger" not in md.lower()

def test_upsert_writes_dated_file(tmp_path):
    upsert_standup(str(tmp_path), "2026-05-16", PLAN, gpu_holder=None, hw_queue=[])
    f = tmp_path / "2026-05-16.md"
    assert f.exists() and "Hardware gate" in f.read_text(encoding="utf-8")

def test_upsert_is_idempotent_overwrite(tmp_path):
    upsert_standup(str(tmp_path), "2026-05-16", PLAN, None, [])
    upsert_standup(str(tmp_path), "2026-05-16", PLAN, None, [])
    assert (tmp_path / "2026-05-16.md").read_text(encoding="utf-8").count("# Standup") == 1

def test_finalize_previous_appends_footer_once(tmp_path):
    (tmp_path / "2026-05-15.md").write_text("# Standup 2026-05-15\n", encoding="utf-8")
    finalize_previous(str(tmp_path), "2026-05-16")
    txt = (tmp_path / "2026-05-15.md").read_text(encoding="utf-8")
    assert "<!-- finalized -->" in txt
    finalize_previous(str(tmp_path), "2026-05-16")  # second call no-ops
    assert (tmp_path / "2026-05-15.md").read_text(encoding="utf-8").count("<!-- finalized -->") == 1
