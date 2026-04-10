# Quickstart

## Build

```bash
python3 -m pip install -r requirements.txt
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j8
```

## Test

```bash
python3 -m pytest tests/ -v
```

## Issue tracking (bd)

```bash
bd ready --json
bd update <id> --claim --json
bd close <id> --reason "Completed" --json
```
