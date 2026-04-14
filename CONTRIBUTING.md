# Contributing to Astroray

Thanks for contributing.

## Prerequisites

- CMake 3.18+
- C++17 compiler
- Python 3.7+
- OpenMP

## Local setup

```bash
python3 -m pip install -r requirements.txt
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)
```

## Validation

Run tests before opening a PR:

```bash
python3 -m pytest tests/ -v --tb=short
```

Useful focused runs:

```bash
python3 -m pytest tests/test_python_bindings.py -v
python3 -m pytest tests/test_material_properties.py -v
python3 -m pytest tests/test_standalone_renderer.py -v
```

## Pull requests

1. Keep changes focused and minimal.
2. Update docs when behavior/build steps/workflows change.
3. Ensure build and tests pass locally before opening a PR.
4. Include rendered evidence for visual rendering changes when practical.
