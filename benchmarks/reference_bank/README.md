# Visual Reference Bank (pkg104)

A scene+gate harness for catching visual regressions before they ship.
Complements `cycles-parity/` (pkg71): that one compares Astroray to Cycles
on scenes both engines can render; this one compares Astroray to its own
*vision* on scenes Astroray uniquely targets (spectral dispersion, GR,
astrophysics).

See `.astroray_plan/packages/pkg104-visual-reference-bank.md` for the
full spec, rationale, and reference citations.

## Status

Phase 1 scaffolding only — runner + metrics + harness self-test landed.
Owner-curated vision scenes are blocked on the Q1+Q2 scene-selection gate
in the spec.

## Quick start

```powershell
# Re-bless the harness self-test reference (do this once on a known-good commit).
python -m benchmarks.reference_bank.runner --scenes cornell-mini --bless

# Run the bank against all blessed references.
python -m benchmarks.reference_bank.runner

# Smoke mode (PR-gate scope; very fast).
python -m benchmarks.reference_bank.runner --mode smoke

# Run a specific scene.
python -m benchmarks.reference_bank.runner --scenes cornell-mini
```

Exit codes: 0 if all gates pass, 1 otherwise.

## Layout

- `runner.py` — CLI entry point.
- `metrics/` — one file per metric. All take linear scene-referred RGB and
  return `(scalar, debug_artifact)`. Pure-Python, no native deps.
  - `ssim.py` — Wang 2004 structural similarity, clip-to-99.9-percentile.
  - `delta_e_2000.py` — CIEDE2000 perceptual color difference (Sharma 2005).
  - `phash.py` — DCT-based 64-bit perceptual hash + Hamming distance.
  - `hue_spread.py` — circular variance of hue in a bright ROI ("rainbow present").
  - `bright_coverage.py` — fraction of bright pixels in ROI ("caustic present").
  - `dark_disk.py` — fraction of dark pixels in ROI ("BH shadow present").
- `scenes/<name>/` — one directory per pinned scene:
  - `scene.py` — Python module exporting `NAME, WIDTH, HEIGHT, SAMPLES, MAX_DEPTH, SEED, make_scene(astroray)`.
  - `gates.toml` — declarative gate config.
  - `notes.md` — owner-authored description of what the scene is *supposed* to look like.
  - `reference.png` — owner-blessed reference (display-referred, sRGB-encoded).
- `refs/MANIFEST.sha256` — checksum manifest (populated when LFS references land).
- `results/<timestamp>-<sha>/<scene>/` — per-run artifacts (gitignored):
  `actual.png`, `reference.png`, `diff.png`, `report.md`.
- `history.csv` — append-only CSV of every runner invocation's outcome.

## Adding a scene (Phase 2 — needs owner Q1/Q2 first)

1. Decide scene name (kebab-case, e.g. `prism-rainbow-bk7`).
2. `mkdir benchmarks/reference_bank/scenes/<name>/`
3. Write `scene.py` exporting the required attributes + `make_scene(astroray)`.
4. Write `notes.md` describing the vision.
5. Render once at high quality on a known-good commit and `--bless` to capture
   the reference, OR provide a `reference.png` produced by Cycles/Mitsuba/PBRT-v4.
6. Write `gates.toml` with the gate set + thresholds.
7. Verify: `python -m benchmarks.reference_bank.runner --scenes <name>` exits 0.
8. Commit `scene.py`, `gates.toml`, `notes.md`, `reference.png` (LFS for large refs).

## Adding a metric

1. Implement `metrics/<name>.py` exposing one `compute_<name>(...) -> (float, debug)` function.
2. Re-export from `metrics/__init__.py`.
3. Add a dispatch branch in `runner.py::_evaluate_gate`.
4. Document the gate semantics (direction = `ge` or `le`) and add a unit test
   exercising signal vs no-signal cases in `tests/test_reference_bank_smoke.py`.

## CI policy (Phase 4 — not yet wired)

- `reference-bank-smoke` on every PR (Cornell-only, <60s).
- `reference-bank-full` nightly on self-hosted RTX runner.
- Failure attaches diff artifacts to the PR comment.

## Why this is separate from `cycles-parity/`

- `cycles-parity/` is a **ceiling test**: it compares Astroray against Cycles
  on Blender Foundation `.blend` scenes (Cornell + Classroom + Junkshop +
  BMW27). Those scenes have known forward-compat issues with Blender 5.1
  (broken shader nodes, missing textures) and pkg71 owns that fight.
- `reference_bank/` is a **vision test**: it compares Astroray against the
  *owner's intent* for the renderer. Every scene is Python-constructed via
  the astroray API — no Blender Foundation asset dependency. The default
  reference for every scene is an owner-blessed Astroray render at a known-
  good commit; optional one-shot cross-checks against PBRT-v4 / Mitsuba 3
  are supported but are not gates and are not required.

The two run independently. `cycles-parity` answers "does Astroray match
Cycles where Cycles can render the scene?" `reference_bank` answers "does
Astroray still match itself, on the scenes that define what it's *for*?"
