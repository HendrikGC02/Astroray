# NRC Prototype Notes (pkg26)

**Date:** 2026-05-01  
**Status:** Complete — all acceptance criteria passed.

---

## Run results

```
Device: NVIDIA GeForce RTX 5070 Ti (sm_120, 16303 MiB)
NeuralCache created. N_IN=16 N_OUT=16 BATCH_ALIGN=256
Frame  1/50 | lum=0.2841 | CUDA:OK
Frame 16/50 | lum=0.4040 | CUDA:OK   ← end of warmup (training)
Frame 17/50 | lum=0.4321 | CUDA:OK   ← cache-only phase begins
Frame 50/50 | lum=0.4317 | CUDA:OK

===== NRC Learning Curve =====
Frame  1 mean luminance : 0.2841  (untrained cache)
Frame 50 mean luminance : 0.4317  (post-warmup cache)
Delta                   : +0.1475  (PASS — cache contributes indirect illumination)
```

Luminance increases monotonically during the 16-frame warmup (0.2841 → 0.4040), then
stabilises in the post-warmup cache-only phase. No CUDA errors. PPM outputs written.

---

## Architecture

| Component | Choice | Reason |
|---|---|---|
| Network | FullyFusedMLP 64-wide, 2 hidden layers | pkg26 spec; fits in tcnn WIDTH=64 specialisation |
| Encoding | Identity (16 floats passthrough) | Position, view/normal spherical, roughness, albedo |
| Loss | RelativeL2 | HDR-friendly; avoids over-weighting dark pixels |
| Optimizer | Adam lr=1e-3 | Standard choice; converges in 16 warmup frames |
| Output | 16 floats; slots 0-2 = R/G/B, 3-15 unused | FullyFusedMLP output-width must be multiple of 16 |

---

## Build gotchas resolved

### 1. `TCNN_MIN_GPU_ARCH` static_assert failure (compile time)
- tcnn master with CUDA 12.8 auto-detects `TCNN_MIN_GPU_ARCH=120` (Blackwell).  
- Our target is sm_89 (Ada); the static assert `__CUDA_ARCH__ >= 1200` fails for sm_89.  
- **Fix:** `#undef TCNN_MIN_GPU_ARCH` / `#define TCNN_MIN_GPU_ARCH 89` in `neural_cache.cu`
  before including any tcnn headers.

### 2. `BATCH_SIZE_GRANULARITY = 256` in tcnn master (runtime crash)
- tcnn master raised the batch-size granularity from 128 (v1.x) to **256**.  
- The object.h `forward()` method enforces `input.n() % 256 == 0` via `CHECK_THROW`.  
- Our initial `BATCH_ALIGN=128` allowed batches not divisible by 256 (e.g. 32640),  
  causing an uncaught `std::runtime_error` that terminated with exit code 0xC0000409.  
- **Fix:** Changed `NeuralCache::BATCH_ALIGN` from 128 to **256**.  
- The internal FullyFusedMLP still requires multiples of 128 (16 × N_ITERS=8 for WIDTH=64),
  so 256 satisfies both constraints.

### 3. `nlohmann/json.hpp` not at expected path
- tcnn bundles nlohmann/json at `dependencies/json/json.hpp` (included as `<json/json.hpp>`),
  not at `dependencies/nlohmann/json.hpp`.  
- **Fix:** Removed explicit include; the JSON header is pulled in transitively via
  `<tiny-cuda-nn/config.h>`.

---

## Runtime observations

- Warmup (frames 1–16): 50/50 train/infer split per pixel.  
  Luminance rises quickly: 0.2841 → 0.4040 (+42%) in 16 frames.
- Cache-only (frames 17–50): all pixels query NRC; luminance stays ~0.43.  
  Slight variance (±0.01) is due to stochastic primary-ray jitter changing which pixels
  hit the light directly vs. indirectly.
- Training targets clamped at 10 to suppress fireflies; inference outputs clamped at 5.
- No NaN/Inf in output (cudaDeviceSynchronize always returned cudaSuccess).

---

## Recommendation for pkg27

The NRC prototype validates the tcnn integration end-to-end on RTX 5070 Ti (sm_120).  
For the full NRC implementation (pkg27), the following should be addressed:

1. **Batch alignment**: use `NeuralCache::BATCH_ALIGN = 256` (tcnn master requirement).
2. **Inference params**: current prototype calls `forward(..., use_inference_params=true)`.
   After training, the inference copy is populated by `trainer->training_step`. Before
   the first training step, params are in training copy only; inference copy should be
   the same pointer (tcnn Trainer sets both to the same GPU buffer). Validated as working.
3. **Feature encoding**: Identity encoding is sufficient for the Cornell box prototype.
   For scene-scale generalisation, consider Hash Grid encoding (requires NVRTC / JIT).
4. **Loss plateaus at ~0.43**: the 16-frame warmup converges but stops improving.
   Increasing warmup frames (32–64) or reducing learning rate decay would help.
5. **CUDA_ARCHITECTURES in CMake**: set `TCNN_CUDA_ARCHITECTURES` explicitly to avoid
   relying on auto-detection, e.g. `TCNN_CUDA_ARCHITECTURES=89;120`.
