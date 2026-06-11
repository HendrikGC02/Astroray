#pragma once
// gpu_env_spectral.cuh — shared spectral environment-miss evaluation
// (pkg55-B' Session N+6).
//
// Factored VERBATIM out of src/gpu/multiwavelength_kernel.cu::tracePathMW's
// miss block (the pkg85-D spectral-tint form) so the wavefront stage_advance
// kernel and the MW megakernel evaluate environment misses through ONE
// implementation (spec design decision #9: single generator, never a second
// transcription). Mirrors CPU EnvironmentMap::evalSpectral +
// pathTraceSpectral's miss handling (include/raytracer.h:2339-2356).
//
// The MW kernel's luminance-band Rayleigh fallback stays at its call site
// (it needs the MW TU's rayleighScale table and has no CPU-wavefront twin).
// Only include from .cu files compiled by nvcc.

#include "gpu_types.h"
#include "gpu_materials.h"  // gpu_rgbToSampledSpectrum
#include "gpu_bvh.h"        // gpu_envmap_apply_rot

// Environment radiance for a missed ray: backgroundColor > env map > default
// sky gradient. Spectral upsampling matches the CPU pipeline (ILLUMINANT for
// emission-like sources, ALBEDO for the env tint — pkg85-D parity fix).
__device__ inline GSampledSpectrum gpu_env_miss_spectral(
    const GEnvMap& envMap,
    const GVec3& backgroundColor, bool hasBackgroundColor,
    const GVec3& dir, const GSampledWavelengths& lambdas)
{
    GSampledSpectrum envSpec(0.f);
    if (hasBackgroundColor) {
        envSpec = gpu_rgbToSampledSpectrum(backgroundColor, lambdas,
                                           GSPEC_RGB_ILLUMINANT);
    } else if (envMap.loaded) {
        // pkg85-D: mirror CPU EnvironmentMap::evalSpectral spectral tint path.
        // gpu_envmap_lookup applies colorTint as RGB multiply, but the CPU
        // applies it as a spectral multiply (RGBUnboundedSpectrum). For non-
        // grayscale tints these are inequivalent. Fetch raw RGB, convert to
        // spectral, then apply tint + strength spectrally.
        GVec3 d = gpu_envmap_apply_rot(envMap, dir);
        float theta = acosf(fminf(fmaxf(d.y, -1.f), 1.f));
        float phi   = atan2f(d.z, d.x);
        float u     = 0.5f + phi / (2.f * M_PI_F);
        float v     = 1.f - theta / M_PI_F;
        if (u < 0.f) u += 1.f; if (u >= 1.f) u -= 1.f;

        // Bilinear interpolation (same as gpu_envmap_lookup but without tint).
        float uP = u * envMap.width;
        float vP = v * envMap.height;
        int x0 = (int)uP; int x1 = x0 + 1;
        int y0 = (int)vP; int y1 = y0 + 1;
        x0 = x0 < 0 ? 0 : (x0 >= envMap.width  ? envMap.width-1  : x0);
        x1 = x1 < 0 ? 0 : (x1 >= envMap.width  ? envMap.width-1  : x1);
        y0 = y0 < 0 ? 0 : (y0 >= envMap.height ? envMap.height-1 : y0);
        y1 = y1 < 0 ? 0 : (y1 >= envMap.height ? envMap.height-1 : y1);
        float uf = uP - (int)uP, vf = vP - (int)vP;

        auto fetchSpec = [&](int x, int y) {
            int i = (y*envMap.width + x) * 3;
            GVec3 rgb(envMap.data[i], envMap.data[i+1], envMap.data[i+2]);
            return gpu_rgbToSampledSpectrum(rgb, lambdas, GSPEC_RGB_ILLUMINANT);
        };
        GSampledSpectrum s00 = fetchSpec(x0, y0);
        GSampledSpectrum s10 = fetchSpec(x1, y0);
        GSampledSpectrum s01 = fetchSpec(x0, y1);
        GSampledSpectrum s11 = fetchSpec(x1, y1);

        GSampledSpectrum s0 = s00 * (1.f - uf) + s10 * uf;
        GSampledSpectrum s1 = s01 * (1.f - uf) + s11 * uf;
        envSpec = (s0 * (1.f - vf) + s1 * vf) * envMap.strength;

        // Apply color tint as spectral multiply (RGBUnboundedSpectrum).
        // CPU: RGBUnboundedSpectrum uses RGBAlbedoSpectrum (JH sigmoid, no D65).
        if (envMap.colorTint[0] != 1.f || envMap.colorTint[1] != 1.f || envMap.colorTint[2] != 1.f) {
            GVec3 tint(envMap.colorTint[0], envMap.colorTint[1], envMap.colorTint[2]);
            GSampledSpectrum tintSpec = gpu_rgbToSampledSpectrum(tint, lambdas, GSPEC_RGB_ALBEDO);
            envSpec = envSpec * tintSpec;
        }
    } else {
        float t = 0.5f * (dir.y + 1.f);
        GVec3 bg = (GVec3(1.f) * (1.f - t) + GVec3(0.5f, 0.7f, 1.f) * t) * 0.2f;
        envSpec = gpu_rgbToSampledSpectrum(bg, lambdas, GSPEC_RGB_ILLUMINANT);
    }
    return envSpec;
}
