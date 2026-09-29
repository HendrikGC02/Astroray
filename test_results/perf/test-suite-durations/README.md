# Test-suite durations: before vs after the speed work
Per-area, per-file and per-test pytest junit durations, before (serial `pytest tests`) vs after (`run_split.py`). After-series CPU-pass times are divided by the 4 xdist workers, so bars are wall-equivalent seconds.
Before: serial, 45.2 min wall (2711 s), 4587 cases.
After, full profile (`run_split.py`): 23.8 min wall (CPU pass 451 s + GPU pass 977 s); every test still runs.
After, fast profile (`run_split.py --fast`): 7.2 min wall (143 + 291 s), 3593 of 4646 tests.
Verdict: full is -47 %. The 15-min full target and the 5-min fast target were NOT met. The floor is the serial GPU pass: 977 s full, 291 s fast, of which ~1130 sub-second tests make up ~200 s.
Charts: full_* and fast_* by_area, by_file (top 30), top_tests (top 30); each has a JSON sidecar with the rows.
Provenance: RTX 5070 Ti, 8 cores, OMP 8. Before build al-293 (2026-09-29 13:47); after build am-962 (22:58).
Directive: .astroray_plan/docs/test-suite-speed-directive.md.
Regenerate: `python scripts/test/run_split.py --junit DIR` (plus `--fast`), then `durations_report.py`.
