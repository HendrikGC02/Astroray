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

## Writing material plugins

### `evalSpectral` is required (pure virtual since pkg14)

`Material::evalSpectral` is pure virtual. Every material plugin **must** override it:

```cpp
astroray::SampledSpectrum evalSpectral(
    const HitRecord& rec, const Vec3& wi, const Vec3& wo,
    const astroray::SampledWavelengths& lambdas) const override {
    // return your BRDF weighted by cos(theta) / pdf, in spectral units
}
```

Light-source materials that scatter nothing should return `astroray::SampledSpectrum(0.0f)`.

### `Material::eval` is gone (removed in pkg14)

The `virtual Vec3 eval(const HitRecord&, const Vec3&, const Vec3&) const` method no
longer exists on the `Material` base class. Plugins that previously relied on it as an
internal helper may keep a private non-virtual `eval()` (Disney and Phong do this), but
the `override` keyword must be removed and the method must not be called polymorphically.

### `BSDFSample::f` (Vec3) for delta-lobe fallback

Plugins' `sample()` methods should still populate `BSDFSample::f` with the Vec3 BRDF
value. The spectral path tracer uses `bs.f` when `evalSpectral` returns zero for perfect
delta lobes (mirror/glass) — the Vec3 value is upsampled once per bounce as a fallback.

## Pull requests

1. Keep changes focused and minimal.
2. Title format: `feat: <description>` or `fix: <description>`.
3. Include rendered evidence for visual changes when practical.
4. Update docs when build steps or workflows change.
5. Ensure build and tests pass locally before opening a PR.
