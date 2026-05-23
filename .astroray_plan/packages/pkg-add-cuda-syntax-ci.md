# pkg-add-cuda-syntax-ci — CUDA syntax check in Linux CI

**Pillar:** 0 (Infrastructure)
**Track:** Track A (CI/build infrastructure)
**Status:** in-progress
**Estimated effort:** ~2 hours (spec + CI workflow + test)
**Depends on:** none

---

## Goal

**Before:** Linux CI runs without the CUDA toolkit. `.cu` and `.cuh` files are
never compiled on CI, only on the RTX dev machine. CUDA syntax errors (undefined
symbols, wrong field names, namespace collisions, template mismatches) ship to
main "green" and break the hardware build, requiring 3–5 fix rounds before clean.

**After:** A new Linux CI job `cuda-syntax-check` compiles all `.cu` and `.cuh`
files with `nvcc -c` (parse + typecheck, no linking) on every PR. CUDA syntax
errors fail CI before merge.

---

## Context

### Round 13 Lesson (from NEXT_STAGE_REPORT.md line 146-148)

> pkg-add-cuda-syntax-ci (not yet spec'd) — Linux CI matrix job building CUDA
> paths to catch syntax errors before main. Round 13 Lesson: pkg87b's broken
> CUDA paths shipped to main (Linux CI green) and bit pkg55 #343 (5 build-fix
> rounds) + pkg64-gpu Phase 2.

Pattern observed repeatedly this round:

- Linux CI green (no CUDA toolkit → no `.cu` compilation)
- RTX hardware build hits syntax errors post-merge
- 3–5 fix commits before clean

### Specific examples (pkg87b → pkg64-gpu + pkg55 N+4)

| Error | File | PR impact |
|-------|------|-----------|
| `gpu_sampledSpectrumToXYZ` undefined (renamed to `spectrumToXYZ`) | `multiwavelength_kernel.cu` | pkg64-gpu Phase 2 build failure |
| `rec.primType` / `rec.primIndex` → wrong field names | `wavefront/stage_intersect.cu` | pkg64-gpu Phase 2 build failure |
| `GAreaLight` incomplete-type (forward-decl shadowing global namespace) | `stage_shade_lambertian.cu` | pkg55 N+4 Session 1 |
| `cross()` / `dot()` free-function vs member | `stage_shade_lambertian.cu` | pkg55 N+4 Session 1 |
| `mat.base_color` vs `mat.baseColor` | `stage_shade_lambertian.cu` | pkg55 N+4 Session 1 |

All of these errors are **frontend syntax/type errors** that `nvcc -c` catches
without device execution or linking.

---

## Reference

### Internal

- [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) — current Linux CI workflow
- Round 13 NEXT_STAGE_REPORT.md §2 "pkg-add-cuda-syntax-ci" entry

### External

- [NVIDIA CUDA Compiler Driver (NVCC) documentation](https://docs.nvidia.com/cuda/cuda-compiler-driver-nvcc/) — compilation phases, `-c` flag semantics
- [Jimver/cuda-toolkit GitHub Action](https://github.com/Jimver/cuda-toolkit) — GHA setup action for CUDA toolkit on Ubuntu runners (v0.2.35, supports CUDA 12.x/13.x)
- Standard CUDA CI pattern: compile with `-c` to catch syntax without GPU execution. See [ptheywood/cuda-cmake-github-actions](https://github.com/ptheywood/cuda-cmake-github-actions) for reference workflows.

---

## Specification

### Scope

**In scope:**
- Install CUDA toolkit on Linux CI runner (Ubuntu 20.04/22.04)
- Compile every `.cu` and `.cuh` file with `nvcc -c` (syntax + typecheck only)
- Fail CI if any compilation fails

**Out of scope:**
- Linking (the runner has no GPU, we can't execute kernels)
- Device-code execution tests (covered by RTX hardware verification)
- CMake full-build integration (this is a **syntax-only** check, parallel to the main build)

### CUDA version

Match the RTX dev machine: **CUDA 12.8** (per recent hardware verify reports and
CMakeLists.txt line 54 comment "sm_120 requires CUDA 12.8+").

### Implementation

Add a new job to `.github/workflows/ci.yml`:

```yaml
cuda-syntax-check:
  runs-on: ubuntu-latest
  steps:
    - name: Checkout
      uses: actions/checkout@v4

    - name: Install CUDA toolkit
      uses: Jimver/cuda-toolkit@v0.2.35
      with:
        cuda: '12.8.0'
        method: 'network'  # smaller download, faster CI
        sub-packages: '["nvcc"]'

    - name: Compile CUDA sources (syntax check only)
      run: |
        set -e
        # Find all .cu and .cuh files
        cuda_files=$(find src include -type f \( -name "*.cu" -o -name "*.cuh" \))
        
        # Compile each .cu file with -c (no linking)
        # Use -arch=sm_75 (Turing baseline) for syntax compatibility
        for cu_file in $(echo "$cuda_files" | grep '\.cu$'); do
          echo "Compiling $cu_file..."
          nvcc -c "$cu_file" \
            -std=c++17 \
            -arch=sm_75 \
            -I include \
            -I third_party/tiny-cuda-nn/include \
            -I third_party/tiny-cuda-nn/dependencies \
            --expt-relaxed-constexpr \
            -o /tmp/$(basename "$cu_file").o
        done
        
        # For .cuh headers, verify they parse by including them in a trivial .cu
        # (Skip if this adds complexity — headers are checked transitively by .cu compilation)
```

### Alternative: simpler approach

If the above is too fragile (missing includes, third-party dependencies not
available), use `nvcc --device-syntax-check` (if available in CUDA 12.8) or
just compile a representative subset (e.g., `src/gpu/path_trace_kernel.cu`
which transitively includes most headers).

**Chosen approach:** compile all `.cu` files with `-c`. Headers are checked
transitively. If third-party includes break, add them to the checkout or skip
`-I third_party/...` and accept that we only catch errors in Astroray-authored
code.

### Files to modify

| File | Change |
|------|--------|
| `.github/workflows/ci.yml` | Add `cuda-syntax-check` job after `build-and-test` |

### Acceptance criteria

- [ ] CI workflow runs on every push/PR
- [ ] CUDA toolkit 12.8 installs successfully on Ubuntu runner
- [ ] All `.cu` files in `src/gpu/` and `src/` compile with `nvcc -c`
- [ ] A known-bad commit (e.g., one of the pkg87b/pkg55 errors) fails the check
- [ ] Current `main` passes the check
- [ ] CI run time increases by < 3 minutes (CUDA install ~1 min, compilation ~1 min)

### Hard non-goals

- **No GPU execution.** The runner has no NVIDIA GPU. This is syntax-only.
- **No full linking.** We don't need a working executable, just frontend validation.
- **No CMake integration.** This is a parallel check, not a replacement for the RTX build.
- **Not a required check initially.** Make it visible in CI but don't block merges
  until we verify it's stable (1-2 PRs). After that, make it required.

---

## Why this matters

Round 13 burned ~8 hours of human + agent time on CUDA syntax errors that
shipped to main green. Every CUDA error that reaches the RTX build requires:
1. Hardware build attempt (5-10 min)
2. Diagnosis (10-30 min)
3. Fix commit (5-15 min)
4. Re-verify on hardware (5-10 min)
5. Repeat 3-5 times per package

This CI job catches all frontend errors in ~2 minutes, before merge.

---

## Lessons

(To be filled after implementation)
