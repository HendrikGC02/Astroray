# Fix Three Renderer Bugs

## Context
Read docs/agent-context/lessons-learned.md before starting.
All source code is in apps/ and module/ directories (not src/).

## Bug 1: Missing Gamma Correction (HIGHEST PRIORITY)
The renderer saves linear float pixel values directly to PNG with no
gamma correction. PNG viewers expect sRGB gamma (approximately 2.2).

Fix: Before writing each pixel channel to PNG, apply:
  corrected = pow(linear_value, 1.0f / 2.2f)
  or use the standard sRGB formula if available

This should be applied in the final image write step, after all
sampling is complete but before clamping to [0,1] and converting to
uint8. Do NOT apply it per-sample or per-bounce — only once at output.

## Bug 2: Broken Tests (HIGH PRIORITY)
All tests in tests/test_standalone_renderer.py use `return result`
instead of `assert result`. This means they always pass regardless of
whether the render is correct.

Fix: Replace every `return some_condition` with `assert some_condition, "description"`
Do not change what is being tested — only change return to assert.
After fixing, run the tests — some may now actually fail, which is correct.

## Bug 3: Blocky Brightness Artifacts
The rendered Cornell box shows patches of inconsistent brightness
that form a rough grid pattern. Likely causes:
  - MIS weight normalisation error in powerHeuristic
  - Random seed correlation between image regions
  - Thread-local RNG not properly seeded per-pixel

Investigate the render loop and MIS implementation in raytracer.h.
Check that each pixel uses an independently seeded RNG, not a shared one.
Check that powerHeuristic weights sum to 1.0 across a full sample.

## Test Command
python -m pytest tests/ -x -q --tb=short

## Definition of Done
- Rendered Cornell box has no blown-out ceiling light
- Rendered Cornell box has no blocky brightness patches
- All tests use assert not return
- Tests actually validate image correctness (fail on broken renders)
- python -m pytest tests/ -x -q exits 0
