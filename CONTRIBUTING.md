# Contributing to Astroray

Thanks for contributing.

## Prerequisites

- CMake 3.18+
- C++17 compiler (MSVC 2019+, GCC 10+, or Clang 12+)
- Python 3.11+
- OpenMP (optional — disable with `-DASTRORAY_DISABLE_OPENMP=ON`)

## Local setup

```bash
python3 -m pip install -r requirements.txt
```

### Linux / macOS

```bash
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)
```

### Windows (MSVC)

Open a Developer Command Prompt for Visual Studio, then:

```cmd
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release -DASTRORAY_ENABLE_CUDA=OFF
cmake --build . --config Release -j
```

The module lands in `build/Release/astroray.cp*-win_amd64.pyd`. Copy it to `build/` before running tests.

## Validation

Run the full test suite before opening a PR:

```bash
python3 -m pytest tests/ -v --tb=short
```

Focused runs:

```bash
python3 -m pytest tests/test_python_bindings.py -v
python3 -m pytest tests/test_material_properties.py -v
python3 -m pytest tests/test_standalone_renderer.py -v
```

## Pull requests

1. Keep changes focused and minimal.
2. Title format: `feat: <description>` or `fix: <description>`.
3. Include rendered evidence for visual changes when practical.
4. Update docs when build steps or workflows change.
5. Ensure build and tests pass locally before opening a PR.
