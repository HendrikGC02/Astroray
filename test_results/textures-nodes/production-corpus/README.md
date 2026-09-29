# production-corpus

What: eight production node-tree materials (car paint, wood, marble, PBR group, shader stack, attributes,
light path, curves + geometry) rendered Cycles (1024 spp) | Astroray CPU | Astroray GPU (64 spp, seed 278).
Sheets `prod_*_sheet.png` draw the gate ROIs; `band_utilisation_chart.png` = worst ROI-channel deviation / MC band
per material and backend (<= 1 is in band); `production_summary.json` = N/8; `silent_drops.json` = audit.
Verdict (baseline): CPU 0/8, GPU 0/8, silent-drop-free 0/8 (39 strict silent pairs, ~7 real). All 32 failing
tests are strict xfails tied to issues #988-#996, #955. Lane inspection: scenes, ROIs and references are sound.
Opus sign-off 2026-09-30 (lead): sheets valid; failures match filed issues (marble GPU flat = #994; car-paint facing-ratio tint missing = #989; light-path camera-vs-lit floor colour = #991); no scene/reference defect. Ranked backlog: `.astroray_plan/docs/pkg310-production-corpus-burndown.md`.
Provenance: pkg310, Cycles 5.2.0 LTS, Astroray on the pkg298 CUDA build + main f0f8b5f6 addon Python, 2026-09-30.
Regenerate: `python benchmarks/reference_corpus/report_tools.py production --work-dir <dir> --out-dir <dir>`.
