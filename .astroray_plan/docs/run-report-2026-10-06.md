# Run report: long haul 2026-10-05 → 10-07 (checkpoint)

Lead: Opus 5.5. Lanes: Sonnet 5.5 and Opus 5.5 (i1–i19). Reviews: blind Opus agents plus opencode GLM-5.3, the owner-approved route while Codex is out until 2026-11-04. Two architect runs: `architect-plan-2026-10-06.md` and `-06b.md`. Owner decisions are in memory `owner-decisions-2026-10-06`.

## Stage 0 gates at the checkpoint
| Row | State |
|---|---|
| (a) latency | **GREEN**: formal `--mode gate_a` on build beda188, worker ON, 1200 edits. Pooled p95 78.2 / p99 109.7 ms (thresholds 100/150; was 102.1 RED). The worker-OFF table (all 6 cells PASS, 0 chain errors) was re-measured under #1050's raw-event binding: 100k material p95 157.3 → 69.6 ms. #875's 100k move < 20 ms target still fails (77.7 ms) |
| (b) coverage | Unmeasured; needs a re-freeze. #1101 (scanner, reviewed), #1104 (Emission two-sided; the checker witness passes on CPU, SSIM 0.9855) and #1113 (scene re-freeze) all landed. Next: a new scanner-integration receipt, then re-freeze v4 on corpus v2 + production (owner population) |
| (c) trio | **GREEN** under the adopted Welch-1b metric (owner decision; #1121 pending CI). 80 hash-pinned seed legs on the integration build: 0 rejected tiles in every role, ROI max 0.73 %, 0 evidence errors. M1 found two real defects first, #1111 (GPU glass Fresnel side; card z-fight), fixed in #1114 and #1113 |
| (d) panels | GREEN |
| (e) triage | 10-06 blind rating (Sonnet + GLM, 12/12 agree): the only high, #1070, was closed by #1094. New highs this session: none open |
| (f) install | Unmeasured. Owner: run `gate-f-other-pc-runbook.md` on a second PC (ZIP sha in the runbook) |
| (g) node score | **RED**, first measurement. CPU 2/8 and GPU 1/8 (threshold 6/8 on both, owner). The 1 silent pair per backend is #1117, a scanner false negative on Pointiness |

Committed manifest: (d) and (e) only. Evidence for (a)/(c)/(g) is local (`%LOCALAPPDATA%\astroray-evidence\2026-10-06\`), pending the owner's evidence-storage decision.

## Headline numbers
| What | Before | After | PR |
|---|---|---|---|
| 100k material edit (engine) | 44 ms | 4.2 ms | #1083 |
| Instanced transform edit, 7.8M tris | 700 ms | 1–4 ms | #1096 |
| GPU rough-glass furnace rim (IOR 1.8, r 1.0) | 0.41 | 0.94 | i16 (pending) |
| GPU lit glass furnace | 0.957 (strict xfail) | in band | #1114 |
| Hair melanin tuft vs Cycles | 0.786 | 1.002 | #1093 |
| Bent hair strand vs Cycles (sun in plane) | 0.33 | 1.00 | #1119 |
| Cornell parity SSIM | 0.93 | 0.9994 | #1074 |
| Gate (a) instrument output per run | 9.75 GB | 75 MB | #1066 |
| Disk: old measurement output | — | 56 GB moved to `~\Astroray_TO_DELETE_2026-10-05` | — |

## Merged: 36 PRs
- **Gate (e) highs:** #1069, #1071, #1076, #1078, #1079, #1091, #1093
- **Gate (a):** #1066, #1068, #1083, #1096, #1106
- **Gate tooling:** #1086, #1090, #1101, #1109
- **Parity fixes:**
  - #1074 (cornell), #1094 (reference firefly), #1095, #1097, #1098, #1102
  - #1103 (Glass tint), #1104 (Emission two-sided), #1110 (Voronoi ND)
  - #1113 (scene z-fight), #1114 (GPU glass Fresnel), #1118 (ReSTIR OOB write), #1119 (strand self-skip)
- **GR:** #1064, #1080, #1107 (redshift referenced to infinity, owner)
- **Tests:** #1065. **Docs:** #1062, #1077, #1100

Issues: 35 closed. 21 filed (11 already closed): #1108, #1112, #1117 and #1120 are open follow-ups.

## Pending at the checkpoint
- **CI only:** #1105 (pkg322 Pointiness), #1116 (#1112 smooth-glass Fresnel), #1121 (gate (c) Welch). All three were in the integration sweep.
- **Rough glass (i16, branch `batch-i16/cycles-multiggx-glass`):**
  - Cycles 5.2 MULTI_GGX is the default on CPU+GPU (owner); the pkg265 walk is kept behind `rough_glass_walk=1`.
  - The furnace is within 0.008 of Cycles on CPU, and the GPU reads 0.94–1.00.
  - The Cycles-parity review is APPROVE-WITH-FIXES. M1 (GPU leg) is done: 40/41, and the pkg188 row stays xfail on #1120.
  - M3 (engine A/B attribution of the r ≥ 0.85 gap to Cycles' invalid-refraction light leak) is running as lane i19.
  - The shade kernels hold REG 254, with STACK +240–272 B. PR after M3.

## Verification
- **Integration sweep:** main 37cbdb45 plus #1118/#1114/#1116/#1119/#1105/#1109/#1110, full CPU+GPU (slow included). **4726 passed, 0 failed**, 20 xfailed, 4 XPASS (non-strict), 52 min. The previous full sweep (4c5b5326) had 18 failures.
- cuobjdump on every device PR: the shade kernels stay REG 254.

## Lessons (memory updated)
- **GPU results are test-order dependent.** A "#1093 × #1097 regression" was really an out-of-bounds write from ReSTIR's stale guide binding (#1115, fixed in #1118), and the bisect had compared different test selections. Run identical selections when bisecting.
- **A strict xfail can hide the real cause.** The GPU glass furnace deficit that was blamed on the missing walk was a Fresnel-side bug (#1111). Its strict xfail flipped once that was fixed.
- **`gate_manifest.py --out <existing>`** reads the old file as `--existing` and flags honest status changes as hand edits. Use a fresh `--out`.
- **Measurement frames are pruned by default** (#1066; owner rule: keep summaries, not bulk frames).

## Owner items
1. Gate (f): run the runbook on the second PC and bring `evidence\` back.
2. Evidence storage for (a)/(c)/(g) legs: git, LFS or local.
3. README prism exposure (carried over).
4. Row (g) threshold is 6/8 (set); gate (b) re-freeze is next session's first job.
