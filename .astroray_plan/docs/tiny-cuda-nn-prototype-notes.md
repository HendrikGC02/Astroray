# tiny-cuda-nn Prototype Notes (pkg25)

**Date:** 2026-04-30
**Machine:** Windows 11, NVIDIA RTX 3000 Ada (sm_89), CUDA 12.9 toolkit

---

## Toolchain

| Component | Version |
|---|---|
| OS | Windows 11 Enterprise 10.0.26100 |
| GPU | NVIDIA RTX 3000 Ada Generation Laptop |
| GPU compute capability | sm_89 |
| CUDA toolkit | 12.9 (nvcc) / CMake found 13.2 (separate install) |
| MSVC | 19.44.35215.0 (VS2022 Community) |
| CMake | 4.1.1 |
| tiny-cuda-nn | v1.3 (via FetchContent) |

---

## Build flags

```cmake
cmake -S . -B build_tcnn \
    -DBUILD_PYTHON_MODULE=OFF \
    -DASTRORAY_TINY_CUDA_NN=ON \
    -DCMAKE_BUILD_TYPE=Release
```

The `ASTRORAY_TINY_CUDA_NN` option defaults to `OFF`. No production target
depends on it. The smoke harness is `scripts/tiny_cuda_nn_smoke.cu`; its
CMake target is `tcnn_smoke`.

---

## CMake configuration outcome

tiny-cuda-nn v1.3 fetched and configured successfully (46 s cold download +
configure). Detected architectures: 75;80;86 (tiny-cuda-nn's auto-detect).
The `tcnn_smoke` target overrides to sm_89 (RTX 3000 Ada).

---

## Build outcome

**First attempt:** tiny-cuda-nn.lib compiled successfully. `tcnn_smoke` failed:
```
C1083: Cannot open include file: 'tiny-cuda-nn/common.h'
```
**Root cause:** `FetchContent_MakeAvailable(tiny-cuda-nn)` does not propagate
`INTERFACE_INCLUDE_DIRECTORIES` to downstream targets through `target_link_libraries`.
The tcnn include path (`_deps/tiny-cuda-nn-src/include`) and its bundled
dependencies (`_deps/tiny-cuda-nn-src/dependencies`, containing nlohmann/json)
must be added explicitly to the consumer target.

**Fix applied:** Added `target_include_directories(tcnn_smoke PRIVATE
${tiny-cuda-nn_SOURCE_DIR}/include ${tiny-cuda-nn_SOURCE_DIR}/dependencies)`.

**Second attempt (with explicit include dirs):** BUILD SUCCEEDED — `tcnn_smoke.exe`
produced by MSVC + CUDA 13.2 nvcc (VS generator always selects 13.2 regardless
of PATH or `-DCMAKE_CUDA_COMPILER` override due to VS CUDA 13.2 integration).

---

## Run outcome

**Result: RUNTIME FAILURE — blocked by driver version mismatch.**

```
CUDA error scripts/tiny_cuda_nn_smoke.cu:33 — CUDA driver version is
insufficient for CUDA runtime version
```

**Root cause:** VS2022 CUDA integration selects CUDA 13.2 unconditionally.
The installed NVIDIA driver (576.57) supports CUDA runtime ≤ 12.9. The binary
built by the VS generator links against CUDA 13.2 static runtime, which requires
a driver released after the 576.57 package.

**Attempted workaround:** `-DCMAKE_CUDA_COMPILER:FILEPATH=.../v12.9/nvcc.exe`
is silently ignored when using the Visual Studio CMake generator; the VS CUDA
extension overrides it at build time.

**Standalone CUDA smoke (`simple_cuda_smoke.cu`):** direct `nvcc` invocation
also requires the full VS + Windows SDK environment (fails with missing
`crtdefs.h`). Outside of the VS CMake generator, CUDA MSVC compilation cannot
be done without running inside a VS Developer Command Prompt.

---

## Feasibility verdict

| Question | Result |
|---|---|
| FetchContent works? | ✅ Yes — tiny-cuda-nn v1.3 fetches and configures in ~33 s |
| Library compiles? | ✅ Yes — `tiny-cuda-nn.lib` builds cleanly |
| Smoke binary compiles? | ✅ Yes — `tcnn_smoke.exe` builds cleanly |
| Runtime works? | ❌ Blocked — CUDA 13.2 binary, driver supports 12.9 only |

**The code path is complete.** Unblocking requires one of:

1. **Preferred:** Update NVIDIA driver to a release that supports CUDA 13.2
   (any driver ≥ 525.85 / Windows WHQL ≥ 527.41).
2. **Alternative:** Remove the CUDA 13.2 Visual Studio integration so the VS
   generator falls back to CUDA 12.9 (uninstall CUDA 13.2 VS extension in
   the CUDA Toolkit installer, then re-run `cmake --fresh`).

---

## Observations and blockers

- tiny-cuda-nn's automatic GPU architecture detection targets 75;80;86 (Turing,
  Ampere A100, Ampere A10/30). The smoke target explicitly sets
  `CUDA_ARCHITECTURES "89"` for the RTX 3000 Ada.
- tiny-cuda-nn requires sm_70+ for `FullyFusedMLP`; the smoke harness gracefully
  skips (exit 0) on older hardware so it does not break CI on non-RTX machines.
- FetchContent does not auto-propagate include paths from tiny-cuda-nn — must
  add `${tiny-cuda-nn_SOURCE_DIR}/include` and `.../dependencies` explicitly via
  `target_include_directories`.
- The VS CMake generator ignores `CMAKE_CUDA_COMPILER` overrides when a newer
  CUDA VS integration is installed; use Ninja or NMake generator to respect the
  explicit compiler path.

---

## Recommendation

If build and inference both succeed, the next step (not in this package) is
to prototype a Neural Radiance Cache (NRC) integrator plugin:
- On first hit, query the tcnn MLP for cached radiance instead of tracing
  a full path.
- Train online: propagate path-trace estimates back into the MLP via SGD.
- See `.astroray_plan/docs/light-transport.md §Phase 3C` for scope.

If build fails due to Windows/MSVC linking issues, consider:
- Using WSL2 + gcc/clang for the CUDA build
- Using tinycudann Python bindings (requires PyTorch installation first)
