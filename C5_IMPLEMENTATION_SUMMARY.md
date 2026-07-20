# pkg55-C5 Implementation Summary

## Objective
Port spectral photon-map caustics from MW megakernel to GPU wavefront, passing SSIM≥0.80 gate.

## Implementation (4 commits on feat/pkg55-c5-photon-caustics)

### 1. Thread photon structures through driver + shade (f7642dc)
- Added `buildCausticAim` helper to wavefront driver (mirrors cuda_renderer.cu:662)
- Build photon caustic grid in `cuda_wavefront_render` via `cuda_photon_caustic_build`
- Thread `photonGrid/hasPhotonGrid/photonScale` through:
  * cuda_wavefront_render → launchStageShadeBucketed
  * stageShadeBucketedKernel → shadePathSlot
- Free caustic grid via `cuda_photon_caustic_free` after render
- Include `gpu_photon_store.h` for photonGridGatherKnn

### 2. Simplified photon hack (5d9408f) - SUPERSEDED by commit 4
Added photon XYZ to spectral color.v[0..2] (wrong approach).

### 3. Manual test script (de474fc)
`test_c5_photon_wavefront.py` renders glass-sphere with wavefront_path_tracer vs path_tracer baseline.

### 4. Clean photon_xyz SoA approach (fb5a03f) - CURRENT
**Key insight:** MW kernel accumulates in XYZ space; wavefront accumulates in spectral.
To match MW without breaking spectral model, added 3 new SoA fields:

**New SoA fields (GPUWavefrontState):**
- `float* photon_xyz_x/y/z` — XYZ photon contrib from primary hit

**Allocation/free (wavefront_state.cu):**
- Allocate in `allocateGPUWavefrontState`
- Free in `freeGPUWavefrontState`

**Zero at render start (gpu_wavefront_snapshot.cu:1458):**
```cuda
cudaMemset(state.photon_xyz_x/y/z, 0, total_paths * sizeof(float));
```

**Write in shadePathSlot (stage_advance.cu:~440):**
```cuda
if (bounce == 0 && hasPhotonGrid && !useLuminanceOutput && photonGrid.numPhotons > 0) {
    if (mat.emissionIntensity <= 0.0f) {
        int found = 0;
        GVec3 E = photonGridGatherKnn(photonGrid, rec.point, 50, 1.1f, found);
        if (found > 0) {
            GVec3 alb = mat.baseColor;
            GVec3 photonContrib = GVec3(alb.x * E.x, alb.y * E.y, alb.z * E.z) * photonScale;
            state.photon_xyz_x[idx] = photonContrib.x;
            state.photon_xyz_y[idx] = photonContrib.y;
            state.photon_xyz_z[idx] = photonContrib.z;
        }
    }
}
```

**Add to accumulation in stageRegenKernel (stage_advance.cu:~1212):**
```cuda
atomicAdd(&accum_xyz[pixel * 3 + 0], xyz.x);  // spectral color converted to XYZ
atomicAdd(&accum_xyz[pixel * 3 + 1], xyz.y);
atomicAdd(&accum_xyz[pixel * 3 + 2], xyz.z);
// Add photon XYZ (if any)
float photon_x = state.photon_xyz_x[idx];
float photon_y = state.photon_xyz_y[idx];
float photon_z = state.photon_xyz_z[idx];
if (photon_x != 0.f || photon_y != 0.f || photon_z != 0.f) {
    atomicAdd(&accum_xyz[pixel * 3 + 0], photon_x);
    atomicAdd(&accum_xyz[pixel * 3 + 1], photon_y);
    atomicAdd(&accum_xyz[pixel * 3 + 2], photon_z);
}
```

## MW Kernel Parity

**MW kernel flow (multiwavelength_kernel.cu:440-507):**
1. Trace path → spectral radiance `rad`
2. Convert to XYZ: `sample = spectrumToXYZ(rad, lambdas)`
3. Gather photons at primary: `sample += albedo·E·photonScale` (XYZ + XYZ)
4. Accumulate `sample` to framebuffer

**WF flow:**
1. Shade path → spectral radiance `color`
2. At bounce==0: gather photons → write to `photon_xyz`
3. At regen: convert to XYZ `xyz = spectrumToXYZ(color, lambdas)`
4. Accumulate `xyz + photon_xyz` to accum_xyz

**Result:** Same XYZ accumulation, different timing. MW does XYZ conversion + photon add per sample; WF does them separately but adds both to accum.

## Build & Test Plan

**Build:**
```bash
cd ../Astroray-pkg55-c5
cmake --build build_cuda --config Release --target astroray
```

**Test:**
```bash
python test_c5_photon_wavefront.py
```

**Gate:** SSIM ≥ 0.80 between wavefront_path_tracer and path_tracer (MW baseline).

**Full test suite:**
```bash
pytest tests/test_gpu_caustic_parity.py::test_gpu_glass_sphere_caustic_parity -v
```
(May need to modify test to use wavefront_path_tracer or run both integrators.)

## Known Issues / Notes

- Photon contrib uses component-wise multiply `alb.{RGB} * E.{XYZ}` which treats sRGB baseColor as XYZ (physically wrong but matches MW kernel).
- Photon gather only happens at primary hit (bounce==0); multi-bounce caustics not supported (matches MW kernel scope).
- SMS caustics (pkg64) not ported (xfail, out of C5 scope).

## Citations

- MW kernel: multiwavelength_kernel.cu:936-962 (pre-pass), :490-507 (gather)
- pkg113 photon store: gpu_photon_store.h photonGridGatherKnn
- Jensen 2000 Eq. 8 (photon density estimate)
- Cycles integrate_surface_direct_light (shade-then-shadow structure)
