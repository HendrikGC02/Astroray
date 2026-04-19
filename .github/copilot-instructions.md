# Astroray — Copilot Agent Instructions

You are working on Astroray: a C++/CUDA physically-based path tracer
with a Blender 5.1 addon. Read this file before doing anything.

## Project layout

```
Astroray/
├── include/
│   ├── raytracer.h          ← core types and Material base class
│   └── advanced_features.h  ← GR integrator, spectral, advanced BSDFs
├── src/
│   └── renderer.cpp         ← Renderer, PyRenderer, path tracer
├── plugins/                 ← one file per plugin (see below)
│   ├── materials/
│   ├── shapes/
│   ├── textures/
│   ├── integrators/
│   └── passes/
├── tests/
│   └── test_*.py            ← pytest test suite
├── blender_addon/           ← Blender 5.1 Python addon
├── CMakeLists.txt
└── .astroray_plan/          ← development plan (read-only for you)
```

## How to build

```bash
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
```

## How to run tests

```bash
pytest tests/ -v
```

All tests must pass before you open a PR. A PR with failing tests will
be closed without review.

## The simplicity tax

Every abstraction must have a concrete caller today. If you are
tempted to create a helper, a base class, or a utility function that
is only called from one place: don't. Inline it. A veteran engineer
reading your diff should say "yeah, that's how I'd do it" — not
"clever."

## What you are allowed to do

Your task is described in the GitHub issue that triggered this session.
You may only:

- Create files under `plugins/` as specified in the issue.
- Create or extend test files under `tests/`.
- Modify `CMakeLists.txt` **only** if the issue explicitly says so.

## What you must not touch

- `include/raytracer.h` — unless the issue explicitly says so.
- `include/advanced_features.h` — unless the issue explicitly says so.
- `src/renderer.cpp` — unless the issue explicitly says so.
- `blender_addon/` — not your concern in plugin issues.
- Any file not mentioned in the issue spec.

If you think a file outside the issue scope needs changing, stop and
leave a PR comment explaining why. Do not make the change.

## Plugin pattern

Every plugin file ends with exactly one registration macro:

```cpp
ASTRORAY_REGISTER_MATERIAL("name", ClassName)   // for materials
ASTRORAY_REGISTER_SHAPE("name", ClassName)      // for shapes
ASTRORAY_REGISTER_TEXTURE("name", ClassName)    // for textures
ASTRORAY_REGISTER_INTEGRATOR("name", ClassName) // for integrators
ASTRORAY_REGISTER_PASS("name", ClassName)       // for passes
```

The constructor takes `const ParamDict&`. Use `getFloat`, `getVec3`,
`getInt`, `getBool`, `getString` with sensible defaults.

## Work package spec location

The work package that describes your task is in
`.astroray_plan/packages/`. The issue will tell you which package.
Read it, but do not modify it.

## Physics invariants (never alter these)

- GR capture threshold: `r < 2.5M` — validated. Do not change.
- Dormand-Prince Butcher tableau coefficients are ported exactly from
  the Python reference. Do not "clean up" the numbers.
- Double precision in the GR integrator, float everywhere else.
- Auto-exposure: 99th-percentile luminance scaled to 0.8.
