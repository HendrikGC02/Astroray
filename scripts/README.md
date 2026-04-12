# Scripts

Developer utilities. None of these are required for a plain CMake build, but
they streamline common workflows.

## Blender addon packaging & testing

### `build_blender_addon.py`

Builds the pybind11 `astroray` module against a Python whose minor version
matches the target Blender's bundled Python, then stages the addon files
(`__init__.py`, `blender_manifest.toml`, compiled `.pyd`/`.so`) into
`dist/astroray/` and zips them to `dist/astroray-<version>.zip`.

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
