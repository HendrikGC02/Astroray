# Build Scripts

Build and packaging helpers live here. `build_cuda.bat` is the canonical Windows
CUDA development build (Ninja, `build_cuda/`). `build_blender_addon.py` builds
and stages the Blender 5.2 extension with CUDA by default; `--backend cpu` is
the explicit CPU-only option. All addon backends disable OpenMP.

Use [`../dev_addon.ps1`](../dev_addon.ps1) for the build/package/install/smoke
loop under a disposable Blender profile. `-Launch` explicitly installs into the
user profile and opens Blender. The test/dev and addon native artifacts are
separate builds; never load the OpenMP-enabled development module into Blender.
See [development setup](../../docs/DEVELOPMENT.md) and
[the dev loop guide](../../DEVELOPMENT.md).
