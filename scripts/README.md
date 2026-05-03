# Scripts

Developer utilities. None of these are required for a plain CMake build, but
they streamline common workflows.

## Blender addon packaging & testing

### `build_blender_addon.py`

Builds the pybind11 `astroray` module against a Python whose minor version
matches the target Blender's bundled Python, then stages the addon files
(`__init__.py`, `shader_blending.py`, `blender_manifest.toml`, compiled
`.pyd`/`.so`) into `dist/astroray/` and zips them to
`dist/astroray-<version>.zip`.

The script auto-detects the CMake generator (MinGW on MSYS2/MinGW systems,
MSVC default on Visual Studio machines) and always passes
`-DASTRORAY_ENABLE_CUDA=OFF -DASTRORAY_DISABLE_OPENMP=ON` for Blender
compatibility.

```bash
# Fully automatic: picks the newest Blender install and a matching Python
python scripts/build_blender_addon.py

# Target a specific Blender (Windows example)
python scripts/build_blender_addon.py --blender "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"

# Specify Python explicitly (when auto-detection picks the wrong one)
python scripts/build_blender_addon.py --python-exe /usr/bin/python3.13

# Also copy the staged addon into Blender's user_default extensions dir
python scripts/build_blender_addon.py --install
```

**Prerequisite: matching Python.** Blender does not ship Python development
headers, so the module cannot be built against Blender's bundled interpreter
directly. Install a separate Python whose minor version matches:

| Blender | Bundled Python |
| ------- | -------------- |
| 4.1–4.5 | 3.11           |
| 5.0     | 3.11           |
| 5.1+    | 3.13           |

Install with:
- Windows: `winget install Python.Python.3.13`
- macOS: `brew install python@3.13`
- Linux: `sudo apt install python3.13-dev`

### `render_test_scene.py`

Blender-side script invoked via `blender --background --python`. Enables the
`astroray` extension, forces `scene.render.engine = 'CUSTOM_RAYTRACER'`,
applies sampling overrides, and renders a single frame. Not meant to be run
directly — use `test_blender_addon.py` below.

### `test_blender_addon.py`

One-shot end-to-end smoke test: builds + packages + installs the addon, then
runs Blender headlessly against `blender_addon/Test_scene.blend` (or any other
`.blend` via `--scene`) and writes the resulting PNG under `test_results/`.

```bash
python scripts/test_blender_addon.py
python scripts/test_blender_addon.py --samples 8 --width 320 --height 240
python scripts/test_blender_addon.py --skip-build  # reuse the last staged build
```

Exit code 0 means Blender rendered the scene through Astroray and wrote a
non-empty PNG.

## Other helpers

- `autonomous_loop.sh` — local autonomous engineering loop helper.
- `build_cuda.bat` — Windows helper for CUDA-related builds.
- `benchmark_showcase.py` — renders canonical showcase scenes and a composite
  grid under `test_results/showcase/`.
- `convergence_tracker.py` — renders increasing-SPP sequences and writes an
  MSE plot plus convergence strip.
- `material_contact_sheet.py` — renders material swatches and records the
  selected backend plus capability/fallback reason per tile.
- `oidn_comparison.py` — renders noisy/denoised Cornell frames and a
  side-by-side PNG when OIDN is compiled in.
- `render_output_triage.py` — diagnostic PNG summary for `test_results/`.
  It reports image size, brightness, saturation, low color counts, and likely
  all-black outputs. This is for agent review, not a hard CI gate.

  ```bash
  python scripts/render_output_triage.py
  python scripts/render_output_triage.py --flagged-only
  ```

- `start_local_agent_server.sh` — WSL helper for starting a local
  OpenAI-compatible `llama.cpp` server. It sets `LD_LIBRARY_PATH` for the
  current user install and defaults to the safer Qwen2.5 Coder 14B model.

  ```bash
  # From WSL, in the repo root
  bash scripts/start_local_agent_server.sh

  # Larger, tighter model for planning/prototyping
  bash scripts/start_local_agent_server.sh --model qwen35-35b-q3 --ctx-size 16384

  # Client settings for Aider/Ralph-style tools
  export OPENAI_API_BASE=http://127.0.0.1:8080/v1
  export OPENAI_API_KEY=dummy
  ```

  On this workstation, WSL sees an RTX 5070 Ti with 16GB VRAM and 64GB RAM.
  The practical model order is:

  1. `qwen2.5-coder-14b-q5` — safest default for tool-calling and longer context.
  2. `qwen35-35b-q3` — worth testing for planning/reasoning, but tight on VRAM.
  3. `qwen3-coder-30b-q4` — already available through Ollama; direct
     `llama.cpp` use needs CPU MoE offload on a 16GB card.
