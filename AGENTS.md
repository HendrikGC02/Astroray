## Project Structure

```
Astroray/
├── apps/                    # Standalone CLI entrypoint
├── blender_addon/           # Blender RenderEngine addon + shader_blending.py
├── docs/                    # Project docs, ADRs, agent context
├── plugins/                 # Plugin implementations compiled into both targets
├── include/                 # Header-only renderer core
│   ├── raytracer.h          # Core: Vec3, Ray, Materials, BVH, Camera, Renderer
│   ├── advanced_features.h  # DisneyBRDF, textures, transforms, volumes
│   └── astroray/            # GR physics, spectral pipeline, metric
├── module/                  # pybind11 Python bindings (blender_module.cpp)
├── scripts/                 # build_blender_addon.py and utilities
├── src/                     # C++ implementation units
├── tests/                   # pytest suite (~1590 collected tests as of 2026-08-07)
└── CMakeLists.txt
```

## Agent Operating Model

- `AGENTS.md` is the shared repo contract for coding agents.
- `CLAUDE.md` remains Claude Code's behavioral guide. Do not delete or replace it.
  Its durable rules are also summarised below for every harness, including
  Codex; when its detailed rule is relevant, read it before acting.
- **Live planning hierarchy (read before proposing or dispatching work):**
  1. `.astroray_plan/docs/STATUS.md` — latest factual project state.
  2. `.astroray_plan/docs/NEXT_STAGE_REPORT.md` — current handoff and
     deployable next work.
  3. `.astroray_plan/docs/ROADMAP.md` — especially **Current sequencing**,
     owner priorities, and pause directives.
  Then confirm the candidate package's own `Status:`/dependencies and current
  git/GitHub state. Do not route from old handoffs, archived plans, or an
  apparent empty queue alone.
- `KNOWLEDGE.md` is the repo routing map — it documents `scripts/project_index.py`
  (`query`/`owns`/`script`/`deps`/`whatis`) for answering "who owns this file",
  "what package does X", and "is there already a script for this task". Consult it
  before grepping blind.
- Keep agent-specific notes additive. If a rule belongs to all agents, put it here.
- **Before writing any new script, check `scripts/README.md` (the canonical
  per-task script index) and grep `scripts/`, `benchmarks/`, `tools/` for an
  existing script that already does the job. Extend the canonical script;
  do not create a parallel one-off. New reusable scripts must be registered
  in `scripts/README.md` in the same commit.**

## Shared Operating Discipline

- Work on Windows with PowerShell. Avoid Bash/cmd escaping, reserved PowerShell
  automatic variables, and non-UTF-8 output.
- Make the smallest change that satisfies the assigned goal. Do not refactor,
  format, or clean up unrelated code; every changed line must trace to the task.
- For non-trivial physics, sampling, or numerical algorithms, use the
  `cite-algorithm` workflow before coding. Prefer a cited published method and
  a license-compatible reference over invention.
- Code-writing subagents require a verified isolated worktree. Their first
  action must confirm `git rev-parse --show-toplevel` is that worktree; abort
  rather than writing if it is not. Keep implementation concurrency to three
  or fewer and serialize CUDA-heavy builds/renders with the project GPU lock.
- Before GPU verification, check the `.pyd` timestamp against `HEAD`, rebuild
  if stale, and confirm `astroray.__file__` resolves to the intended build
  output. A root or test-directory `.pyd` can silently shadow a fresh build.
- Before pushing, list changed function/class signatures and inspect all
  callers, including tests, mocks, and bindings. A green delegated narrative or
  CI-only result is not evidence of GPU/runtime correctness.
- **Autonomous delivery:** once the package's documented gates and required
  independent reviews pass, agents are authorized to commit, push, open PRs,
  and merge through the canonical workflow. Escalate only when the proposed
  work changes owner priority, package scope, or an explicit pause directive.
- **Visual evidence is a release input.** Any change with a visual render,
  viewport, material, spectral, or image-output effect must save representative
  output and receive a qualitative inspection by a visual-capable high-tier
  agent (Astra or Claude) in addition to numerical gates. A visual regression
  is a gate failure even when scalar checks pass. Conversely, investigate a
  failed test or stale reference image rather than assuming the new rendering
  code is wrong.
- **Continuous-improvement lane:** record a worthwhile out-of-scope finding as
  a tightly scoped follow-up package or delegate it as a bounded, isolated
  maintenance task. Do not hide a tangent in an unrelated package diff. This
  applies to renderer performance, build/test throughput, skills, hooks, MCPs,
  project indexing, tracker automation, documentation, repository hygiene,
  benchmarks, and test-suite quality.

## Agent Drivers (opencode primary, Claude Code fallback, Codex supported)

- **opencode** (Go, `opencode-ai` v1.18.x) is the primary agent driver. Config:
  `opencode.jsonc` (defaults) + `.opencode/agents/*.md` (per-agent model/permission)
  + `.opencode/plugins/astroray-hooks.ts` (ported `.claude/hooks/*` guards).
- **Model routing (hybrid):** Astra owns orchestration and can perform the
  judgment seats; open-weight models draft/implement/review bounded work;
  `claude -p` provides an independent last-line sign-off for architect specs,
  gate-failure root-cause, cpp-abi-guard, Cycles parity, PR SIGN-OFF/BLOCK, and
  visual inspection when required. There is **no Anthropic API key** — the
  `sign-off` agent shells out to the `claude` CLI (subscription). Never hardcode model ids in
  skill/hook bodies; routing lives in `.opencode/agents/*` frontmatter +
  `.claude/skills/delegate/config/tiers.json`.
- The 15 skills in `.claude/skills/` remain the canonical shared workflow
  definitions for Claude Code and opencode. Codex uses the discoverable
  `.agents/skills/astroray-workflows/` bridge to load the matching canonical
  body, avoiding a second, drifting copy.
- Claude Code (`.claude/`, `CLAUDE.md`) remains untouched and fully functional —
  switch back any time; it is the fallback and last-line-of-defense layer.
- **Codex** uses `.codex/` for project configuration, lifecycle hooks, and
  focused subagents, plus `.agents/skills/` for the index/workflow bridge.
  Codex model and provider choice stays user-level so it can evolve. For cheap
  external-model work, `astroray-opencode-delegator` reads the current mapping
  from `.claude/skills/delegate/config/tiers.json`; never hard-code those model
  IDs in agents, hooks, or task prompts.

## Build & Test Commands

```bash
# Linux / macOS
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)

# Windows (MinGW/MSYS2 or Ninja)
cmake -B build -DCMAKE_BUILD_TYPE=Release -DASTRORAY_ENABLE_CUDA=OFF
cmake --build build -j

# Windows (MSVC) — open a Developer Command Prompt first
cmake -B build -DCMAKE_BUILD_TYPE=Release -DASTRORAY_ENABLE_CUDA=OFF
cmake --build build --config Release -j

# Run all tests (from repo root)
pytest tests/ -v --tb=short

# Focused suites
pytest tests/test_python_bindings.py -v      # ~45 tests, Python API
pytest tests/test_material_properties.py -v  # material parameter tests
pytest tests/test_standalone_renderer.py -v  # standalone binary tests
pytest tests/test_spectral_*.py -v           # spectral pipeline tests

# Cycles parity benchmark framework
python scripts/run_parity.py --scene cornell --engine astroray-cpu

# Standalone binary CLI (supported flags only)
./build/bin/raytracer --scene 1|2 --width N --height N --samples N --depth N --output file.png --help
```

> **Windows note:** On MSVC the module lands in `build/Release/astroray.cp*-win_amd64.pyd`.
> Copy it to `build/` before running tests, or `conftest.py` won't find it.

## Domain Context

C++ path tracer with physically-based rendering. Key concepts:
Vec3, Ray, Material, Hittable, BVH, Monte Carlo estimation (NOT ML).
Python module (`astroray`) via pybind11. Module is at `build/astroray.cpython-*.so` (Linux) or `build/astroray.cp*-win_amd64.pyd` (Windows).

Pillars 1 and 2 are complete: plugin architecture and the spectral core are
now the baseline. Do NOT rely on this file for the active queue — use the live
planning hierarchy above. The standing owner directive is Blender/DCC
integration-first; Pillar 4 astrophysics remains PAUSED until an explicit owner
unpause.

## Product Direction

Astroray is becoming a production-capable, Blender/DCC-native renderer with a
fast interactive GPU viewport and trustworthy CPU fallback, measured against
Cycles where that is the right baseline. Correctness, visual fidelity, and
physical robustness come before raw speed; the RTX 5070 Ti is the principal
hardware gate, while CPU rendering and portable CUDA behavior remain first-class
compatibility paths.

The long-term target is research-grade astrophysical simulation as well as
scientific visualization: outputs may ultimately include radiance, spectra,
photon counts, and observables for theoretical instruments and phenomena such
as nebulae, HMXBs, and relativistic lensing. That future constrains present
design: the spectral pipeline, dispersion, infrared/band-aware rendering,
physically grounded transport, and DCC interoperability are core foundations,
not optional embellishments. Do not resume paused astrophysics packages without
an owner directive; preserve their requirements while advancing the renderer and
viewport baseline.

## Test Structure

- `tests/conftest.py` — pytest path setup (adds build/, tests/, project root)
- `tests/base_helpers.py` — shared helpers: `create_renderer()`, `setup_camera()`, `render_image()`, `create_cornell_box()`, `assert_valid_image()`
- `tests/test_python_bindings.py` — main suite covering materials, Cornell box, Blender feature parity, GR black hole, AOVs, pixel filters, seed determinism
- `tests/test_material_properties.py` — material parameter validation
- `tests/test_standalone_renderer.py` — C++ binary (correct CLI flags only)
- `tests/test_spectral_*.py` and `tests/test_spectrum.py` — spectral pipeline, spectral materials/textures/env maps
- `tests/test_*_plugins.py` — registry/plugin contract coverage

All tests write images/charts to `test_results/` (gitignored).

## Furnace/energy tests

Any test whose name matches `*furnace*` or `*energy*` MUST render linear —
`renderer.render(..., apply_gamma=False)` (or `render_image(..., apply_gamma=False)`)
— and assert BOTH a floor and a ceiling. `apply_gamma` defaults to `True`, which
clamps output to `[0, 1]`, so a gamma-rendered furnace can only ever detect energy
LOSS, never GAIN: pkg160's white-metal conductor created energy up to **4.139** in
linear (18,338 of 27,648 pixels above 1.0) yet every gamma furnace suite read a max
of exactly **1.000000** and stayed green (PR #527, 2026-07-26). A floor-only assert
is still half-blind even in linear — the ceiling is the half that catches a gain.
This is enforced at test time by an autouse fixture (`tests/conftest.py` +
`tests/_linear_render_guard.py`, pkg166): a furnace/energy test that renders gamma
fails at the render call, not merely by convention.

## Rendering Notes

- `Material::eval(rec, wo, wi)` returns **brdf × NdotL** (cosine INCLUDED). Do NOT multiply by NdotL again.
- `sampleDirect()` returns the combined NEE+MIS estimate. Do NOT multiply by NdotL in the caller.
- Gamma correction (1/2.2) is applied ONCE inside `Renderer::render()`. Do not apply it in test code.
- The firefly clamp is `luminance > 20.0f` in the per-sample accumulation.
- Emissive light from direct hits is only added when `wasSpecular=true` or `bounce==0` to avoid double-counting NEE.
- `BSDFSample` has NO default initialization of `pdf` or `isDelta`. Always set every field.
- Y is up (matches Blender). GR integrator uses `double`; all other rendering math uses `float`.

## Important Files

- `include/raytracer.h` — core data structures; do not refactor casually
- `include/advanced_features.h` — textures, transforms, Disney BRDF, mesh support
- `include/astroray/` — GR subsystem (metric, integrator, accretion disk, spectral)
- `plugins/` — material, texture, shape, integrator, and pass plugins
- `blender_addon/shader_blending.py` — must be packaged with the addon (see `scripts/build/build_blender_addon.py`)

## Current Known Rendering/Test Gaps

- Standalone black-hole smoke can pass with a fully black output; it currently
  verifies crash-freedom more than visible GR correctness.
- GR shadow tests are xfailed after the spectral path-tracer flip until GR
  dispatch is ported into the current integrator path.
- Some older "RGB vs spectral" wording is stale because `path_tracer` is now
  spectral-first and the legacy RGB path was deleted in pkg14.

## Issue Tracking

Issues are tracked on GitHub: https://github.com/HendrikGC02/Astroray/issues

```bash
# List open issues
gh issue list

# Create an issue
gh issue create --title "feat: ..." --body "..."

# Close an issue with a comment
gh issue close <number> --comment "Implemented in PR #..."
```

## Session Completion

1. Run tests — ensure no regressions
2. Stage and commit changes
3. Update issue status (`gh issue close`)
4. Push: `git push`
