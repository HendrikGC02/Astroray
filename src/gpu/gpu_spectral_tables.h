#pragma once
// gpu_spectral_tables.h — pkg55 Phase C Session C1 (extracted from
// multiwavelength_kernel.cu; behaviour-preserving).
//
// The shared spectral-tables layer: the pkg54a/54b/54c constant-memory tables
// (per-material reflectance profiles, CIE 1964 10° CMF + D65 SPD, Jakob-Hanika
// sRGB sigmoid LUT) plus the device helpers that read them. This layer is
// consumed cross-TU by cuda_renderer.cu, the wavefront driver
// (gpu_wavefront_snapshot.cu / stage_advance.cu), and — until pkg55 Phase C
// Session C7 deletes them — both megakernels. It was housed inside
// multiwavelength_kernel.cu, so deleting that file would link-break the
// wavefront; C1 moves it to its own translation unit first.
//
// __constant__ symbols are per-TU: they are DEFINED once in
// gpu_spectral_tables.cu and declared `extern __constant__` here. Cross-TU
// constant-memory access works because astroray_cuda is built with
// CUDA_SEPARABLE_COMPILATION + CUDA_RESOLVE_DEVICE_SYMBOLS (relocatable device
// code). This is the same mechanism that already backs path_trace_kernel.cu's
// `extern __constant__ g_cmfX` reads and the cross-TU gpu_spectrum_to_xyz call
// from the wavefront stage_advance.
//
// The table-reading helpers stay `__device__ inline` so every consumer inlines
// byte-identical code — only the translation unit that OWNS the __constant__
// symbols changed. Include only from .cu files compiled by nvcc.

#include "astroray/gpu_types.h"
#include "astroray/gpu_materials.h"

#include <cuda_runtime.h>

#ifndef M_PI_F
#  define M_PI_F 3.14159265358979323846f
#endif

// ---------------------------------------------------------------------------
// pkg54b: CIE 1964 10° CMF + D65 table geometry. Layout matches
// data/spectra/cie_cmf.inc: 1 nm step over [360, 830] nm.
// ---------------------------------------------------------------------------
static constexpr int   G_CMF_COUNT       = 471;
static constexpr float G_CMF_LAMBDA_MIN  = 360.0f;
static constexpr float G_CMF_LAMBDA_MAX  = 830.0f;
static constexpr float G_CMF_LAMBDA_STEP = 1.0f;

// __constant__ tables owned by gpu_spectral_tables.cu (see file header for the
// relocatable-device-code rationale that makes these cross-TU reads valid).
extern __constant__ float g_cmfX[G_CMF_COUNT];
extern __constant__ float g_cmfY[G_CMF_COUNT];
extern __constant__ float g_cmfZ[G_CMF_COUNT];

// D65 SPD samples (raw CIE units) and the inverse normalization constant
// k = 1 / ∫D65·cmfY dλ over [360,830]. Together these give
// sampleD65(λ) = kD65Spd(λ) * k, mirroring src/spectrum.cpp::sampleD65.
extern __constant__ float g_d65SPD[G_CMF_COUNT];
extern __constant__ float g_d65NormFactor;

// pkg54a: per-material spectral profile reflectance table. One flat buffer of
// G_MAX_PROFILES * G_PROFILE_SAMPLES floats; populated by scene_upload.cu via
// uploadProfileTable(). -1 in GMaterial.profileIndex means "no profile".
extern __constant__ float g_profileTable[G_MAX_PROFILES * G_PROFILE_SAMPLES];

// pkg54c: the Jakob-Hanika sRGB LUT (64³ × 3 × 3 ≈ 9 MB) is too large for the
// 64 KB __constant__ cap, so it lives in device global memory and is read via
// these __device__ pointers populated once by uploadJakobHanikaLut().
extern __device__ const float* g_jhLutScale;   // [res]
extern __device__ const float* g_jhLutCoeffs;  // flat [3][res][res][res][3]
extern __device__ int          g_jhLutRes;

// ---------------------------------------------------------------------------
// Host-callable uploads / probe (defined in gpu_spectral_tables.cu).
// ---------------------------------------------------------------------------
// pkg54b — one-time copy of CIE 1964 10° CMF + D65 tables into constant memory.
void uploadCmfTables();
// pkg54c — one-time copy of the Jakob-Hanika sRGB sigmoid LUT into device
// global memory; required before any gpu_jhEvalSpectrum call.
void uploadJakobHanikaLut();
// pkg54a — copies per-material spectral profiles into constant memory.
void uploadProfileTable(const float* host, int count);
// pkg55-C7: number of profiles currently resident on the device (0 = none).
int uploadedProfileCount();
// pkg54d — single-lookup probe binding (tests/test_gpu_profile_lookup.py).
float launchProfileLookup(int profileIndex, float lambda);

// ---------------------------------------------------------------------------
// Cross-TU __device__ export (defined in gpu_spectral_tables.cu).
// gpu_sampleD65 / gpu_jhEvalSpectrum are already forward-declared in
// gpu_materials.h (called from the inline gpu_rgbToSampledSpectrum); their
// definitions also live in gpu_spectral_tables.cu.
// ---------------------------------------------------------------------------
// pkg55-B' Session N+6: the ONE cross-TU XYZ entry the wavefront's Russian
// roulette + accumulation calls, so the CMF integration is identical to the
// megakernel's.
__device__ GVec3 gpu_spectrum_to_xyz(
    const GSampledSpectrum& s, const GSampledWavelengths& wl);

// ---------------------------------------------------------------------------
// Table-reading device helpers (inline so every consumer emits identical
// code). Mirror the CPU references cited on each function.
// ---------------------------------------------------------------------------

// Linear-interpolated profile reflectance lookup. Mirrors
// astroray::SpectralProfile::reflectance() exactly, just on the device grid.
__device__ inline float gpu_profile_reflectance(int profileIndex, float lambda_nm) {
    if (profileIndex < 0 || profileIndex >= G_MAX_PROFILES) return 0.f;
    float t = (lambda_nm - G_PROFILE_LAMBDA_MIN) / G_PROFILE_LAMBDA_STEP;
    int   i = (int)t;
    float f = t - (float)i;
    const float* row = &g_profileTable[profileIndex * G_PROFILE_SAMPLES];
    if (i < 0)                       return row[0];
    if (i >= G_PROFILE_SAMPLES - 1)  return row[G_PROFILE_SAMPLES - 1];
    return row[i] * (1.f - f) + row[i + 1] * f;
}

// Linearly-interpolated table lookup; mirrors astroray::sampleTable() in
// src/spectrum.cpp (returns 0 outside the grid).
__device__ inline float cmfSample(const float* table, float lambda) {
    if (lambda < G_CMF_LAMBDA_MIN || lambda > G_CMF_LAMBDA_MAX) return 0.f;
    float idx = (lambda - G_CMF_LAMBDA_MIN) / G_CMF_LAMBDA_STEP;
    int   i   = (int)idx;
    if (i >= G_CMF_COUNT - 1) return table[G_CMF_COUNT - 1];
    float t = idx - (float)i;
    return table[i] * (1.f - t) + table[i + 1] * t;
}

// Project a sampled spectrum to CIE XYZ via Monte Carlo CMF integration.
// Mirrors astroray::SampledSpectrum::toXYZ exactly.
__device__ inline GVec3 spectrumToXYZ(
    const GSampledSpectrum& s, const GSampledWavelengths& wl)
{
    float X = 0.f, Y = 0.f, Z = 0.f;
    for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) {
        float p = wl.pdf[i];
        if (p == 0.f) continue;
        float lam = wl.lambda[i];
        float cx = cmfSample(g_cmfX, lam);
        float cy = cmfSample(g_cmfY, lam);
        float cz = cmfSample(g_cmfZ, lam);
        float w = s.v[i] / p;
        X += w * cx;  Y += w * cy;  Z += w * cz;
    }
    float norm = 1.f / float(G_SPECTRUM_SAMPLES);
    return GVec3(X * norm, Y * norm, Z * norm);
}

// ---------------------------------------------------------------------------
// pkg157 — wavefront port of the deleted MW megakernel's gpu_clampContribMW
// (multiwavelength_kernel.cu, removed by pkg55-C7 commit 1af7eca / PR #524).
// Ports Cycles `film_clamp_light`'s bounce-indexed clamp selection
// (src/kernel/film/light_passes.h, Apache-2.0): bounce==0 (direct, including
// delta-light NEE) -> clampDirect, bounce>0 (indirect) -> clampIndirect;
// limit<=0 disables (Cycles semantics). Mirrors CPU Renderer::clampContribSpectral
// (include/raytracer.h) and the same-named helper the RGB megakernel carried
// (path_trace_kernel.cu::gpu_clampContrib) before both were deleted in C7.
// The brightness metric mirrors the wavefront's own final accumulation
// (stageRegenKernel): mean of the spectral samples when useLuminanceOutput
// (non-visible bands carry no CIE CMF signal, so XYZ.Y would be ~0 and never
// clamp), else XYZ.Y via spectrumToXYZ above.
// ---------------------------------------------------------------------------
__device__ inline GSampledSpectrum gpu_clampContribMW(
        const GSampledSpectrum& contrib, const GSampledWavelengths& lambdas,
        int bounce, float clampDirect, float clampIndirect, bool useLuminanceOutput) {
    float limit = (bounce > 0) ? clampIndirect : clampDirect;
    if (limit <= 0.f) return contrib;
    float lum;
    if (useLuminanceOutput) {
        float avg = 0.f;
        for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) avg += contrib.v[i];
        lum = avg / float(G_SPECTRUM_SAMPLES);
    } else {
        lum = spectrumToXYZ(contrib, lambdas).y;
    }
    if (lum > limit && lum > 0.f) return contrib * (limit / lum);
    return contrib;
}

// CIE XYZ (D65) → linear sRGB. Mirrors include/astroray/spectral.h.
__device__ inline GVec3 xyzToLinearSRGB_dev(const GVec3& xyz) {
    float r =  3.2406f * xyz.x - 1.5372f * xyz.y - 0.4986f * xyz.z;
    float g = -0.9689f * xyz.x + 1.8758f * xyz.y + 0.0415f * xyz.z;
    float b =  0.0557f * xyz.x - 0.2040f * xyz.y + 1.0570f * xyz.z;
    float minC = fminf(fminf(r, g), b);
    if (minC < 0.f) { r -= minC; g -= minC; b -= minC; }
    return GVec3(r, g, b);
}
