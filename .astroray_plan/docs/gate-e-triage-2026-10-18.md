<!-- Owner route (Codex out until 2026-11-04): two blind Claude raters (Sonnet 5.5, A and B), independent, same rubric. AGREE 8/8 on severity. Lead reconciliation below. -->
# Gate (e) blind rating, two Claude passes (Sonnet 5.5), 2026-10-18

Scope: the open issues unrated since the 2026-10-06 pass (#1108, #1111, #1117, #1120) plus the four filed tonight
(#1124 prod_attributes GPU, #1125 ReSTIR stale transparent limit, #1126 Disney delta-glass Schlick, #1127 row (d)
POSIX paths). Rubric (`KNOWN_ISSUES.md`): high = wrong image, crash, or a native setting silently ignored;
medium = degraded but flagged / narrow reach; low = cosmetic or tooling. Raw tables:
`astra_run\2026-10-18\gate-e\rating_A.md`, `rating_B.md`.

| # | Title | A | B | Severity | Fixed / PR | Rationale (both raters) |
|---|---|---|---|---|---|---|
| 1108 | Voronoi 3D: N-Sphere Radius, unclamped F2/Manhattan, Distance-to-Edge fractal deviate from Cycles | medium | medium | **medium** | open; #1110 ported 1D/2D/4D only | Unflagged values (1.56x / 0.90x / 1.12x) in specific feature × metric modes; narrow reach. Lane item 5. |
| 1111 | gate (c) Welch M1: GPU ~20 % dark prop; swatch edges | low | low | **low** | fixed: #1114 (A), #1113 (B), #1116 | Close once the formal Welch re-run (M1) confirms. |
| 1117 | Scanner: Pointiness stays DROPPED-SILENT although pkg322 handles it | low | low | **low** | open | Scanner bookkeeping; render unaffected. Lane item 4. |
| 1120 | GPU spectral transmission folds L.weight before upsample (coat_over_tinted_glass GPU/CPU 0.848) | medium | medium | **medium** | open | Unflagged 15 % GPU/CPU gap, bounded to chromatic-coat tinted glass; strict-xfail pinned. Lane item 1. |
| 1124 | prod_attributes GPU: instance0 G 2.15x Cycles (linked meshes, Object Info Random + Color Attribute) | high | high | **high** | open | Wrong GPU image, no warning, common linked-duplicate pattern; CPU correct. Lane item 2. |
| 1125 | ReSTIR leaves c_wfTransparentLimit stale; GPU transparent counter saturates at 31 | medium | medium | **medium** | open; #1118 fixed sibling bindings only | Native setting silently ignored but only after a ReSTIR render or above 31; same class as #1073/#1115. Lane item 9. |
| 1126 | Disney delta glass: Schlick without side-aware dielectric Fresnel | low | low | **low** | open; #1116 fixed Principled only | Custom Disney material; never reached by the Blender export. |
| 1127 | gate_manifest row (d) evidence_path uses Windows separators | low | low | **low** | open | CI/tooling hygiene. Lane item 10. |

## Counts

| severity | count |
|---|---|
| high | 1 (#1124) |
| medium | 3 (#1108, #1120, #1125) |
| low | 4 (#1111, #1117, #1126, #1127) |
| total | 8 |

Row (e) stays RED until #1124 is fixed or re-rated; the 10-06 pass found 0 open highs, so #1124 is the only
open high on 2026-10-18. The committed `acceptance_manifest.json` still carries the 10-05 snapshot (10 highs) and is
re-reduced from the live issue list in this session's closeout.
