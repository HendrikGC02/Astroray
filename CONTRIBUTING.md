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
make -j8
```

## Run tests

```bash
python3 -m pytest tests/ -v
```

## Pull requests

1. Keep changes focused and minimal.
2. Update docs when behavior/build steps change.
3. Ensure build and tests pass locally before opening a PR.
