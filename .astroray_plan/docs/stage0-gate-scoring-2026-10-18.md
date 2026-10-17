# Stage 0 gate scoring, 2026-10-18 (overnight session, Fable lead)

Build under test: main `3bb710b8` (= #1123 merged + the 10-07 PRs), staged addon module
`3bb710b+20261017T134944Z` (`dist/astroray`, sha256 `0dbf6b51…c62489`), `build_cuda` at the same
HEAD. Machine: RTX 5070 Ti, Ryzen 7 7800X3D 8C/16T (SMT on since 2026-10-18). Evidence root:
`%LOCALAPPDATA%\astroray-evidence\2026-10-18\`.

| Row | Status | Value | Evidence | Note |
|---|---|---|---|---|
| (c) trio | **GREEN** | Welch-1b 0 rejected tiles in all roles (materials_hall 0/7920, textures_mapping 0/24116, world_sky terrace 0/5940); ROI channel-mean max 0.73 %; SSIM informational min 0.769 (terrace, noise-limited) | `c-welch\row_c_welch.json`, `acceptance_manifest.c.json` (VALID, (c) green) | First formal run on a stamped main build; the 10-06 run was on a `dev` integration build. Closes #1111. |
| (e) triage | RED → 1 open high | Two blind Sonnet raters, AGREE 8/8 (`gate-e-triage-2026-10-18.md`); #1047 closed (items landed / re-tracked as #1125); the only open high is #1124 (lane item 2 tonight) | `astra_run\2026-10-18\gate-e\rating_{A,B}.md` | The committed manifest still carries the 10-05 snapshot (10 highs); re-reduce at closeout from a fresh snapshot + a ratings file covering all 69 open issues. |
