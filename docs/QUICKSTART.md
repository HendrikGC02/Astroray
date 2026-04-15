# Quickstart

## Prerequisites

- **C++17 compiler**: MSVC 2019+ (Windows), GCC 10+, or Clang 12+
- **CMake** 3.18+
- **Python** 3.11+ (3.13 recommended — matches Blender 5.x)
- **pybind11**, **OpenImageIO**, **OpenEXR** (or install via `requirements.txt`)

```bash
python3 -m pip install -r requirements.txt
```

---

## 1) Build — Python module + standalone binary

### Linux / macOS

```bash
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)
```

### Windows (MSVC — recommended)

Open a **Developer Command Prompt for VS** (or any terminal with MSVC on PATH), then:

```cmd
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release -DASTRORAY_ENABLE_CUDA=OFF
cmake --build . --config Release -j
```

> **Note on CUDA:** Pass `-DASTRORAY_ENABLE_CUDA=OFF` unless you have a fully
> configured CUDA toolkit. The GR/spectral headers currently use GCC-style
> attributes that NVCC rejects.

> **Note on the output path:** On Windows with a multi-config generator (Visual
> Studio), the module lands in `build/Release/astroray.cp*-win_amd64.pyd`.
> The test suite's `conftest.py` looks in both `build/` and `build/Release/`, so
> copy it up if needed:
> ```cmd
> copy build\Release\astroray.cp313-win_amd64.pyd build\
> ```

### Windows (MinGW / MSYS2)

```bash
mkdir build && cd build
cmake .. -G "MinGW Makefiles" -DCMAKE_BUILD_TYPE=Release -DASTRORAY_ENABLE_CUDA=OFF
cmake --build . -j$(nproc)
```

### Build outputs

| Artifact | Linux/macOS | Windows (MSVC) |
|---|---|---|
| Python module | `build/astroray.cpython-*.so` | `build/Release/astroray.cp*-win_amd64.pyd` |
| Standalone binary | `build/bin/raytracer` | `build/Release/raytracer.exe` |

---

## 2) Test

```bash
# Full suite
python3 -m pytest tests/ -v --tb=short

# Focused suites
python3 -m pytest tests/test_python_bindings.py -v
python3 -m pytest tests/test_material_properties.py -v
python3 -m pytest tests/test_standalone_renderer.py -v
```

Test artifacts (rendered PNGs) are written to `test_results/` (gitignored).

---

## 3) Standalone CLI

```bash
# Linux/macOS
./build/bin/raytracer --scene 1 --width 800 --height 600 --samples 64 --depth 50 --output output.png

# Windows
build\Release\raytracer.exe --scene 1 --width 800 --height 600 --samples 64 --depth 50 --output output.png
```

CLI flags: `--scene`, `--width`, `--height`, `--samples`, `--depth`, `--output`, `--help`

---

## 4) Blender addon

The addon packages `__init__.py`, `shader_blending.py`, `blender_manifest.toml`, and the compiled `.pyd`/`.so` into an installable `.zip`.

### Requirements

Blender ships its own Python **without** development headers, so the C++ module must be built against a **matching system Python** (same major.minor version):

| Blender version | Bundled Python | Required system Python |
|---|---|---|
| 5.1+ | 3.13 | `python3.13` / `Python.Python.3.13` |
| 4.x | 3.11 | `python3.11` / `Python.Python.3.11` |

Install if needed:
```bash
# Windows
winget install Python.Python.3.13

# macOS
brew install python@3.13

# Debian/Ubuntu
sudo apt install python3.13-dev
```

### Build

```bash
# Auto-detect Blender + matching Python
python scripts/build_blender_addon.py

# Target a specific Blender install
python scripts/build_blender_addon.py --blender "C:/Program Files/Blender Foundation/Blender 5.1/blender.exe"

# Specify Python explicitly (if auto-detection fails)
python scripts/build_blender_addon.py --python-exe C:/Python313/python.exe

# Build AND install directly into Blender's extensions directory
python scripts/build_blender_addon.py --install

# Clean rebuild
python scripts/build_blender_addon.py --clean
```

The script auto-detects whether to use MinGW or MSVC based on what's available in `PATH`. It always passes `-DASTRORAY_ENABLE_CUDA=OFF` and `-DASTRORAY_DISABLE_OPENMP=ON` for Blender compatibility.

### Output

```
dist/
├── astroray-<version>.zip   ← install via Blender > Preferences > Get Extensions
└── astroray/                ← staged dir (also used for --install)
```

### Install in Blender

**Option A — Extension installer (recommended):**
1. `Edit > Preferences > Get Extensions`
2. Click the dropdown (top-right) → `Install from Disk...`
3. Select `dist/astroray-<version>.zip`

**Option B — Manual:**
Unzip `dist/astroray-<version>.zip` into Blender's `extensions/user_default/` directory.

---

## 5) Issue tracking (`bd`)

```bash
bd ready --json
bd update <id> --claim --json
bd close <id> --reason "Completed" --json
```
