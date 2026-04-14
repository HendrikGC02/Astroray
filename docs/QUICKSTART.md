# Quickstart

## 1) Build

```bash
python3 -m pip install -r requirements.txt
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)
```

## 2) Test

```bash
# Full suite
python3 -m pytest tests/ -v --tb=short

# Focused suites
python3 -m pytest tests/test_python_bindings.py -v
python3 -m pytest tests/test_material_properties.py -v
python3 -m pytest tests/test_standalone_renderer.py -v
```

## 3) Run standalone CLI

```bash
./build/bin/raytracer --scene 1 --width 800 --height 600 --samples 64 --depth 50 --output output.png
```

CLI flags supported:
`--scene`, `--width`, `--height`, `--samples`, `--depth`, `--output`, `--help`

## 4) Issue tracking (`bd`)

```bash
bd ready --json
bd update <id> --claim --json
bd close <id> --reason "Completed" --json
```
