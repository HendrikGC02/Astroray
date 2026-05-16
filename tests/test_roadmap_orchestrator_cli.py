import os, sys, json, subprocess

ROOT = os.path.join(os.path.dirname(__file__), "..")

def test_cli_emits_plan_json(tmp_path):
    prs = [{"number": 1, "title": "pkg94 x", "headRefName": "b", "headRefOid": "s1",
            "isDraft": False, "mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN",
            "statusCheckRollup": [{"__typename": "CheckRun", "status": "COMPLETED",
                                   "conclusion": "SUCCESS"}],
            "createdAt": "2026-05-15T00:00:00Z"}]
    pj = tmp_path / "prs.json"; pj.write_text(json.dumps(prs), encoding="utf-8")
    nsr = tmp_path / "nsr.md"
    nsr.write_text("## 2. set\n1. pkg94\n## 3. prompts\n", encoding="utf-8")
    led = tmp_path / "led.json"; led.write_text("{}", encoding="utf-8")
    out = subprocess.check_output(
        [sys.executable, "-m", "roadmap_orchestrator.cli", "--dry-run",
         "--prs-json", str(pj), "--ledger", str(led),
         "--next-stage-report", str(nsr),
         "--eligible", "pkg94", "--in-flight", "0"],
        cwd=os.path.join(ROOT, "scripts"), text=True)
    plan = json.loads(out)
    assert plan["plan"]["hw_dispatch"] == 1
    assert "Hardware gate" in plan["standup_md"]
    # dry-run must not have created/modified the ledger content
    assert led.read_text(encoding="utf-8") == "{}"
