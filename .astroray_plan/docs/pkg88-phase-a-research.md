# pkg88 Phase A — Camera Motion Blur Research Notes

**Date:** 2026-05-14  
**Agent:** pkg88 implementer  
**Scope:** Phase A only (camera motion blur via T/R/S decomposition + quaternion slerp)

---

## Reference Papers

1. **Shoemake, K. (1985).** "Animating Rotation with Quaternion Curves." *SIGGRAPH '85*. DOI: 10.1145/325334.325242  
   - Canonical quaternion slerp algorithm for smooth rotation interpolation.
   - Used for interpolating camera rotation between shutter keyframes.

2. **Cook, R. L., Porter, T., Carpenter, L. (1984).** "Distributed Ray Tracing." *SIGGRAPH '84*. DOI: 10.1145/964965.808590  
   - Original paper establishing time-sampled ray tracing for motion blur.
   - Establishes the shutter-time sampling model we implement.

---

## Reference Implementations

### PBRT-v4 (Apache-2.0)

**Repository:** https://github.com/mmp/pbrt-v4  
**License:** Apache-2.0 (compatible with Astroray)  
**Files mirrored:**
- `src/pbrt/util/transform.h` — AnimatedTransform class definition
- `src/pbrt/util/transform.cpp` — Decompose() implementation (polar decomposition)
- PBRT-v3 `src/core/quaternion.cpp` — Slerp() implementation (PBRT-v4 uses similar approach)

**Algorithm Details:**

1. **T/R/S Decomposition (PBRT AnimatedTransform::Decompose):**
   - **Translation:** Direct extraction from matrix column 3 (m[0][3], m[1][3], m[2][3]).
   - **Rotation:** Iterative polar decomposition converging to orthogonal matrix R.
     - Start with M = input matrix (translation removed).
     - Iterate: `R_next = (R + Transpose(Inverse(R))) / 2` until convergence.
     - Convergence criterion: norm of difference < 0.0001, max 100 iterations.
   - **Scale:** `S = Inverse(R) * M`.

2. **Quaternion from Rotation Matrix:**
   - **High-trace path** (trace > 0):
     ```
     s = sqrt(trace + 1.0)
     w = s / 2
     x = (m[2][1] - m[1][2]) / (2*w)
     y = (m[0][2] - m[2][0]) / (2*w)
     z = (m[1][0] - m[0][1]) / (2*w)
     ```
   - **Low-trace path:** Find largest diagonal element, extract that component first.

3. **Quaternion Slerp (PBRT Quaternion::Slerp):**
   ```cpp
   Float cosTheta = Dot(q1, q2);
   if (cosTheta > 0.9995f)
       return Normalize((1 - t) * q1 + t * q2);  // Lerp fallback for near-parallel
   else {
       Float theta = acos(Clamp(cosTheta, -1, 1));
       Float thetap = theta * t;
       Quaternion qperp = Normalize(q2 - q1 * cosTheta);
       return q1 * cos(thetap) + qperp * sin(thetap);
   }
   ```
   - Threshold 0.9995 avoids numerical instability for small angles.
   - Shoemake 1985 §4 derives the spherical interpolation formula.

4. **Interpolate at time t:**
   - T_interp = (1-t) * T[0] + t * T[1]  (linear)
   - R_interp = Slerp(t, R[0], R[1])      (quaternion slerp)
   - S_interp = (1-t) * S[0] + t * S[1]  (linear matrix element interpolation)
   - Final transform = Translate(T_interp) * Rotate(R_interp) * Scale(S_interp)

**Why not matrix-element lerp:**
- Spec Q1 rationale: matrix-element lerp produces shear artifacts for rotations > ~5°.
- Rotating camera 30° during shutter (gate A4) would visibly fail with lerp.
- T/R/S decomposition + slerp is the canonical approach (PBRT, Mitsuba 0.6, Cycles).

---

## Astroray Implementation Plan (Phase A)

### 1. Data structures (include/raytracer.h Camera)

Add to Camera class:
```cpp
// pkg88-A: motion blur shutter keyframes (T/R/S decomposed)
Vec3 shutterStartT{0}, shutterEndT{0};        // Translation
Quaternion shutterStartR{1,0,0,0}, shutterEndR{1,0,0,0};  // Rotation (w,x,y,z)
Vec3 shutterStartS{1,1,1}, shutterEndS{1,1,1}; // Scale (uniform for camera, but stored as Vec3)
float shutter = 0.0f;  // Shutter duration in frames (0 = off, 0.5 = Cycles default)
enum class ShutterPosition { Start, Center, End } shutterPosition = ShutterPosition::Center;
```

**Note:** Astroray doesn't have a `Quaternion` type yet. Implement minimal quaternion struct in raytracer.h:
```cpp
struct Quaternion {
    float w, x, y, z;
    Quaternion() : w(1), x(0), y(0), z(0) {}
    Quaternion(float w, float x, float y, float z) : w(w), x(x), y(y), z(z) {}
    // Needed methods: dot, normalize, slerp, toMatrix
};
```

### 2. Camera::getRay signature change

**Old:**
```cpp
Ray getRay(float s, float t, std::mt19937& gen) const
```

**New:**
```cpp
Ray getRay(float s, float t, float time, std::mt19937& gen) const
```

**Implementation:**
- If `shutter == 0.0f`, use current camera basis (pre-pkg88 path, gates A3).
- Otherwise:
  - Compute T_interp, R_interp, S_interp at `time` using PBRT algorithm above.
  - Reconstruct camera origin/u/v/w_axis from interpolated transform.
  - Generate ray from interpolated camera.

### 3. Time sampling (Renderer::renderFrame)

Per spec Q5 (owner decision Q-Owner-4 → **independent Halton**):
- Each spp samples `time` from Halton dimension 8.
- Map raw Halton value `xi` in [0,1] to shutter window based on `shutterPosition`:
  - `Start`: time ∈ [0, shutter]
  - `Center`: time ∈ [-shutter/2, +shutter/2]
  - `End`: time ∈ [-shutter, 0]
- Pass `time` to `getRay(s, t, time, gen)`.

### 4. Blender addon (blender_addon/__init__.py convert_scene)

Detect `scene.render.use_motion_blur`:
- Read `scene.render.motion_blur_shutter` → `camera.shutter`.
- Read `scene.render.motion_blur_position` → `camera.shutterPosition` (enum: START=0, CENTER=1, END=2).
- Compute pre-shutter subframe and post-shutter subframe based on position.
- Call `engine.frame_set(frame, subframe)` twice to capture both camera matrices.
- Decompose both matrices into T/R/S using the PBRT algorithm.
- Upload both keyframes to Camera.

### 5. GPU path (src/gpu/cuda_renderer.cu + path_trace_kernel.cu)

**GCameraParams extension:**
```cpp
struct GCameraParams {
    // ... existing fields ...
    // pkg88-A: shutter keyframes
    Vec3 shutterStartT, shutterEndT;
    float shutterStartR[4], shutterEndR[4];  // quaternion (w,x,y,z)
    Vec3 shutterStartS, shutterEndS;
    float shutter;
    int shutterPosition;  // 0=Start, 1=Center, 2=End
};
```

**Device-side interpolation:**
- `init_rng` samples time from Halton dim 8.
- Device-side `interpolateCameraTransform(time)` reconstructs camera basis at `time`.
- Device-side `getRay` uses interpolated basis.

---

## License Compatibility Verification

| Source | License | Status |
|--------|---------|--------|
| PBRT-v4 `util/transform.{h,cpp}` | Apache-2.0 | ✅ Compatible |
| PBRT-v3 `core/quaternion.cpp` | Apache-2.0 | ✅ Compatible |
| Shoemake 1985 paper | Academic paper (cite-only) | ✅ Citation permitted |
| Cook et al. 1984 paper | Academic paper (cite-only) | ✅ Citation permitted |

No GPL dependencies. All code mirrored from Apache-2.0 sources.

---

## Acceptance Gates (Phase A)

- **A1:** Pan-camera streak test — horizontal pan over shutter=0.5; vertical edge ≥ N pixels matching analytical arc; SSIM vs 2048-spp ≥ 0.97.
- **A2:** Time-uniformity — `ray.time` histogram uniform within 1% per bin at 1024 spp.
- **A3:** Zero-shutter regression — `shutter=0` produces bit-identical pixels vs pre-pkg88 baseline across full test suite. **CRITICAL:** every `getRay` caller must pass correct `time`.
- **A4:** Rotating camera (30° during shutter) — rotationally-symmetric streaks prove T/R/S slerp correctness.

---

## Files Modified (Phase A scope)

1. `include/raytracer.h` — Camera T/R/S fields, Quaternion struct, getRay signature.
2. `src/cpu/integrators/` — all integrator `getRay` call sites updated.
3. `src/gpu/cuda_renderer.cu` — GCameraParams upload.
4. `src/gpu/path_trace_kernel.cu` — device-side time sampling + interpolation.
5. `blender_addon/__init__.py` — detect motion blur settings, decompose camera matrices.
6. `tests/scenes/motion_blur_camera_pan.py` — Phase A validation scene (NEW).

---

## References

- [PBRT-v4 GitHub Repository](https://github.com/mmp/pbrt-v4)
- [PBRT-v3 quaternion.cpp](https://github.com/mmp/pbrt-v3/blob/master/src/core/quaternion.cpp)
- [PBRT-v3 transform.cpp](https://github.com/mmp/pbrt-v3/blob/master/src/core/transform.cpp)
- [Shoemake 1985 SIGGRAPH](https://dl.acm.org/doi/10.1145/325334.325242)
- Physically Based Rendering 4th ed., §2.9 "Animating Transformations"

---

**End of Phase A research notes.**
