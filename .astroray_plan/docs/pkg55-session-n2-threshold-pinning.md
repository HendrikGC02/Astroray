# pkg55-B' Session N+2 — Threshold Pinning + CUDA-Port Preflight

**Status:** done (PR #334, 2026-05-21)  
**Spec:** `.astroray_plan/packages/pkg55-wavefront-soa-refactor.md` §4.2 GATE-THRESHOLDS-PINNED

---

## Goal

Fulfill the GATE-THRESHOLDS-PINNED blocker that blocks Sessions N+2..M (CUDA port) per spec §4.2 and PR #296 §4.2:

> "The first CUDA-port session (pkg55-B' Session N+2) **MUST pin the numeric ULP bound (PostInit/PostIntersect geometry), the p99.9 relative-error percentile bound (Post-Shade/LightSample/RR), and the SSIM floor BEFORE any CUDA code change in that session.**"

**This session delivers the measurement harness and threshold structure. NO CUDA kernel changes yet** — Session N+3 is the first kernel port.

---

## Deliverables

### 1. Pinned threshold file: `.astroray_plan/packages/pkg55_cuda_thresholds.yaml`

Two-tier gate definition:

- **CPU oracle ↔ CPU wavefront baseline** (Sessions 2c-N+1, measured on origin/main):
  - `max_abs_diff: 0.0`
  - `total_diverging_fields: 0`
  - `ssim: 1.0`
  - Scene: `session_n1_envmap_cornell` (7 materials + env-map miss)
  - Resolution: 16×16, 1 spp, seed 424242
  - Measured: origin/main, 2026-05-21

- **CPU wavefront ↔ CUDA wavefront structure** (Sessions N+3..M):
  - **PostInit/PostIntersect** (geometry-only): `max_ulp: 4` per spec §4.2
  - **PostShade/LightSample/RR** (transcendentals): `p99_9_relative_error: 1e-4` (conservative placeholder)
  - **Final image**: `ssim_visible: 0.985`, `ssim_nir: 0.97` (Phase B/C gate)
  - All placeholder p99.9 values documented as **"to be measured in Session N+3"**

**Rationale for placeholders:** Session N+2 cannot measure GPU thresholds before CUDA code exists. The spec's "measured and pinned in Session N+2" + "BEFORE any CUDA code change" creates a chicken-and-egg problem. Resolution: pin the *structure* now with conservative placeholders; Session N+3 measures actual values and updates the YAML.

### 2. CI gate test: `tests/wavefront_diff/test_pkg55_cuda_threshold_gate.py`

- `test_cpu_to_cpu_baseline_bit_identity()`: enforces CPU↔CPU baseline (0.0 / 0 / 1.0). This gate MUST pass on origin/main (Sessions 2c-N+1 established bit-identity by shared-kernel construction).
- `test_cpu_to_gpu_threshold_gate()`: **skipped in Session N+2** (no CUDA kernel yet). Un-skipped in Session N+3.

### 3. Measurement harness: `tests/wavefront_diff/measure_thresholds.py`

Standalone script for threshold measurement and documentation:

```bash
# Session N+2: measure CPU↔CPU baseline (should be 0.0 / 0 / 1.0)
python tests/wavefront_diff/measure_thresholds.py --mode cpu_baseline

# Session N+3: measure CPU↔GPU thresholds (placeholder in N+2)
python tests/wavefront_diff/measure_thresholds.py --mode gpu_port
```

Computes:
- ULP distance (cite: Goldberg 1991 "What Every Computer Scientist Should Know About Floating-Point Arithmetic")
- p99.9 percentile relative error `|a-b| / (|a| + ε)`
- SSIM (cite: Wang 2004 "Image Quality Assessment: From Error Visibility to Structural Similarity")

Outputs YAML for copy-paste into `pkg55_cuda_thresholds.yaml`.

### 4. Spec update: `.astroray_plan/packages/pkg55-wavefront-soa-refactor.md`

Session N+2 completion record added after Session N+1, documenting:
- Threshold structure pinned (CPU↔CPU measured: 0.0 / 0 / 1.0)
- CPU↔GPU structure pinned (placeholders for Session N+3)
- No CUDA kernel changes in this session
- Unblocks Sessions N+3..M

---

## CPU↔CPU Baseline (origin/main, 2026-05-21)

**Measured on:** session_n1_envmap_cornell (7 materials: lambertian, metal, dielectric, disney, thin_glass, diffuse_light, closure_graph + env-map miss), 16×16, 1 spp, seed 424242.

**Results:**
- `max_abs_diff: 0.0`
- `total_diverging_fields: 0`
- `ssim: 1.0` (exact bit-identity)

**Interpretation:** Confirms Sessions 2c-N+1 shared-kernel construction achieves exact bit-identity (same code, same bytes, same order → exact 0.0 snapshot diff at all 5 stages: PostInit, PostIntersect, PostShade, PostLightSample, PostRR).

---

## Two-Tier Gate Rationale (PR #296 §4.1, §4.2)

**Why not exact bit-identity for CPU↔GPU?**

Exact host↔device equality is physically impossible:
- nvcc FMA fusion differs from host SSE2 (`-ffp-contract=fast` default on PTX)
- CUDA `sinf`/`expf`/`__fdividef` are not IEEE-correctly-rounded (hardware intrinsics optimized for throughput, not ULP accuracy)
- PTX intermediate rounding differs from SSE2 (32-bit vs 64-bit intermediates)
- Host `-ffast-math` / `/fp:fast` reassociation has no PTX equivalent

Chasing bit-identity on GPU would re-trigger the Session-2c whack-a-mole (ULP drift in every transcendental), one layer out in vendor libm where it's worse (no source, no fix).

**The CPU↔GPU gate's job is LOCALIZATION (which stage widened), not exact equality.**

Per-stage ULP + p99.9 bounds catch regressions (a stage that was 2 ULP suddenly becomes 100 ULP = bug). Final SSIM gate validates whole-program correctness.

---

## Handoff to Session N+3 (first CUDA kernel port)

Session N+3 TODO:
1. Implement CUDA wavefront stage kernels (`src/gpu/wavefront/stage_init.cu`, `stage_intersect.cu`, etc.)
2. Implement `cuda_wavefront_snapshot_diff()` pybind11 binding (mirrors `cpu_wavefront_snapshot_diff()`)
3. Run `python tests/wavefront_diff/measure_thresholds.py --mode gpu_port` to measure actual ULP / p99.9 / SSIM on first CUDA port
4. Update `pkg55_cuda_thresholds.yaml` with measured values (replace the 1e-4 placeholders)
5. Un-skip `test_cpu_to_gpu_threshold_gate()` and enforce thresholds
6. Subsequent sessions (N+4..M) enforce the pinned thresholds; any stage that widens beyond its p99.9 bound is a regression

**The threshold file is append-only after Session N+3.** If a later session needs to widen a threshold, that's a red flag (implementation regressed) — investigate before updating.

---

## References

- Spec: `.astroray_plan/packages/pkg55-wavefront-soa-refactor.md` §4.2 Sessions N+2..M
- Design rationale: PR #296 §4.1 (why bounded, not exact), §4.2 (two-tier structure), §4.4 (GATE-THRESHOLDS-PINNED blocker)
- Goldberg 1991 "What Every Computer Scientist Should Know About Floating-Point Arithmetic" (ULP definition): https://docs.oracle.com/cd/E19957-01/806-3568/ncg_goldberg.html
- Wang, Bovik, Sheikh, Simoncelli 2004 "Image Quality Assessment: From Error Visibility to Structural Similarity" IEEE Trans. Image Proc. DOI: 10.1109/TIP.2003.819861 (SSIM)
