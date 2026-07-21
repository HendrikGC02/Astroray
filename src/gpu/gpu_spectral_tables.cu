// gpu_spectral_tables.cu — pkg55 Phase C Session C1.
//
// Definitions for the shared spectral-tables layer declared in
// gpu_spectral_tables.h. Extracted verbatim from multiwavelength_kernel.cu so
// the layer survives the megakernel deletion planned for pkg55 Phase C Session
// C7; behaviour-preserving (byte-identical renders is the C1 gate).
//
// The __constant__ / __device__ table symbols are DEFINED here and read
// cross-TU via the extern declarations in gpu_spectral_tables.h; this works
// because astroray_cuda is built with relocatable device code
// (CUDA_SEPARABLE_COMPILATION + CUDA_RESOLVE_DEVICE_SYMBOLS).

#include "gpu_spectral_tables.h"
#include "astroray/spectrum.h"  // jhEvalSpectrumF + JH LUT accessors (pkg54c)

#include <cuda_runtime.h>
#include <cstdio>
#include <stdexcept>

// ---------------------------------------------------------------------------
// pkg54a: Device-side spectral profile table (constant memory).
//
// One flat buffer of G_MAX_PROFILES * G_PROFILE_SAMPLES floats. Slot i covers
// reflectance of profile i at lambda = G_PROFILE_LAMBDA_MIN +
// s * G_PROFILE_LAMBDA_STEP. -1 in GMaterial.profileIndex means "no profile";
// the kernel then mirrors the CPU `Material::evalSpectralExt` no-profile
// fallback (zero outside [380, 780]). The lookup (gpu_profile_reflectance) is
// inline in gpu_spectral_tables.h.
// ---------------------------------------------------------------------------
__constant__ float g_profileTable[G_MAX_PROFILES * G_PROFILE_SAMPLES];

__global__ void gpu_profile_lookup_kernel(int profileIndex, float lambda, float* out) {
    if (blockIdx.x == 0 && threadIdx.x == 0 && out) {
        *out = gpu_profile_reflectance(profileIndex, lambda);
    }
}

float launchProfileLookup(int profileIndex, float lambda) {
    float* d_out = nullptr;
    float out = 0.0f;

    cudaError_t err = cudaMalloc(reinterpret_cast<void**>(&d_out), sizeof(float));
    if (err != cudaSuccess) {
        fprintf(stderr, "profile lookup allocation failed: %s\n", cudaGetErrorString(err));
        throw std::runtime_error(cudaGetErrorString(err));
    }

    gpu_profile_lookup_kernel<<<1, 1>>>(profileIndex, lambda, d_out);
    err = cudaGetLastError();
    if (err == cudaSuccess) err = cudaDeviceSynchronize();
    if (err == cudaSuccess) {
        err = cudaMemcpy(&out, d_out, sizeof(float), cudaMemcpyDeviceToHost);
    }

    cudaError_t freeErr = cudaFree(d_out);
    if (err != cudaSuccess) {
        fprintf(stderr, "profile lookup failed: %s\n", cudaGetErrorString(err));
        throw std::runtime_error(cudaGetErrorString(err));
    }
    if (freeErr != cudaSuccess) {
        fprintf(stderr, "profile lookup free failed: %s\n", cudaGetErrorString(freeErr));
        throw std::runtime_error(cudaGetErrorString(freeErr));
    }
    return out;
}

// Host-callable upload entry; copies up to G_MAX_PROFILES profiles into
// constant memory. Called from cuda_renderer.cu after buildSceneArrays().
void uploadProfileTable(const float* host, int count) {
    if (!host || count <= 0) return;
    int n = count > G_MAX_PROFILES ? G_MAX_PROFILES : count;
    size_t bytes = size_t(n) * G_PROFILE_SAMPLES * sizeof(float);
    cudaError_t err = cudaMemcpyToSymbol(
        g_profileTable, host, bytes, 0, cudaMemcpyHostToDevice);
    if (err != cudaSuccess) {
        fprintf(stderr, "uploadProfileTable failed: %s\n", cudaGetErrorString(err));
        throw std::runtime_error(cudaGetErrorString(err));
    }
}

// ---------------------------------------------------------------------------
// pkg54b: CIE 1964 10° CMF tables in constant memory — same data as the CPU
// `cieCmf1964_10deg` lookup in src/spectrum.cpp, so visible-band CPU vs GPU
// XYZ values match within float-precision instead of the ~5 % observer bias
// the previous Wyman/Sloan/Shirley 2013 1931 2° fits introduced.
//
// Tables are 471 samples × 3 channels × 4 bytes = 5.6 KB (well under the
// 64 KB constant-memory budget). Layout matches data/spectra/cie_cmf.inc:
// 1 nm step over [360, 830] nm. The table geometry constants (G_CMF_COUNT,
// G_CMF_LAMBDA_*) live in gpu_spectral_tables.h.
// ---------------------------------------------------------------------------
__constant__ float g_cmfX[G_CMF_COUNT];
__constant__ float g_cmfY[G_CMF_COUNT];
__constant__ float g_cmfZ[G_CMF_COUNT];

// Pull in the same baked tables the CPU uses. The .inc declares
// `static constexpr float kCieCmfX[471] = {...}` etc.; we host-side-copy
// them to the constant-memory mirrors above via uploadCmfTables().
namespace cmf_baked {
#include "data/spectra/cie_cmf.inc"
}  // namespace cmf_baked

// Pull in the same D65 SPD the CPU uses (data/spectra/illuminant_d65.inc),
// so RGBIlluminantSpectrum-mode emission can mirror src/spectrum.cpp::sampleD65.
namespace d65_baked {
#include "data/spectra/illuminant_d65.inc"
}  // namespace d65_baked

// D65 SPD samples (raw CIE units) and the inverse normalization constant
// k = 1 / ∫D65·cmfY dλ over [360,830]. Together these give
// sampleD65(λ) = kD65Spd(λ) * k, mirroring src/spectrum.cpp::sampleD65.
__constant__ float g_d65SPD[G_CMF_COUNT];
__constant__ float g_d65NormFactor;

// pkg142 hardware-verifier regression (2026-07-2x): photometric anchor for
// RGBUnbounded EMISSION use only. k = 1 / ∫cmfY dλ over [360,830] (bare,
// no D65 weighting) -- mirrors src/spectrum.cpp::cieYIntegral()/
// sampleUnboundedEmission(). Without this, GSPEC_RGB_UNBOUNDED emission came
// out ~116x too bright (unlike GSPEC_RGB_ILLUMINANT, whose gpu_sampleD65
// factor folds this same anchor in together with the D65 chromaticity tilt).
__constant__ float g_cieYNormFactor;

void uploadCmfTables() {
    static bool uploaded = false;
    if (uploaded) return;
    cudaError_t e1 = cudaMemcpyToSymbol(g_cmfX, cmf_baked::kCieCmfX,
                                        sizeof(cmf_baked::kCieCmfX));
    cudaError_t e2 = cudaMemcpyToSymbol(g_cmfY, cmf_baked::kCieCmfY,
                                        sizeof(cmf_baked::kCieCmfY));
    cudaError_t e3 = cudaMemcpyToSymbol(g_cmfZ, cmf_baked::kCieCmfZ,
                                        sizeof(cmf_baked::kCieCmfZ));
    if (e1 != cudaSuccess || e2 != cudaSuccess || e3 != cudaSuccess) {
        fprintf(stderr, "uploadCmfTables failed: %s / %s / %s\n",
                cudaGetErrorString(e1), cudaGetErrorString(e2),
                cudaGetErrorString(e3));
        throw std::runtime_error("CMF table upload failed");
    }

    // Upload D65 SPD and compute the matching norm factor (mirrors
    // computeD65Normalization() / d65NormFactor() in src/spectrum.cpp).
    cudaError_t eD = cudaMemcpyToSymbol(g_d65SPD, d65_baked::kD65Spd,
                                        sizeof(d65_baked::kD65Spd));
    if (eD != cudaSuccess) {
        fprintf(stderr, "D65 SPD upload failed: %s\n", cudaGetErrorString(eD));
        throw std::runtime_error("D65 SPD upload failed");
    }
    double yInt = 0.0;
    for (int i = 0; i + 1 < d65_baked::kD65Count; ++i) {
        double dLam = static_cast<double>(cmf_baked::kCieCmfLambdaStep);
        double a = d65_baked::kD65Spd[i]     * cmf_baked::kCieCmfY[i];
        double b = d65_baked::kD65Spd[i + 1] * cmf_baked::kCieCmfY[i + 1];
        yInt += 0.5 * dLam * (a + b);
    }
    float d65NormF = 1.0f / static_cast<float>(yInt);
    cudaError_t eN = cudaMemcpyToSymbol(g_d65NormFactor, &d65NormF, sizeof(float));
    if (eN != cudaSuccess) {
        fprintf(stderr, "D65 norm upload failed: %s\n", cudaGetErrorString(eN));
        throw std::runtime_error("D65 norm upload failed");
    }

    // pkg142 hardware-verifier regression: compute + upload the bare CIE-Y
    // photometric anchor (mirrors src/spectrum.cpp::computeCieYIntegral(),
    // same trapezoid integration, no D65 weighting).
    double cieYInt = 0.0;
    for (int i = 0; i + 1 < cmf_baked::kCieCmfCount; ++i) {
        double dLam = static_cast<double>(cmf_baked::kCieCmfLambdaStep);
        double a = cmf_baked::kCieCmfY[i];
        double b = cmf_baked::kCieCmfY[i + 1];
        cieYInt += 0.5 * dLam * (a + b);
    }
    float cieYNormF = 1.0f / static_cast<float>(cieYInt);
    cudaError_t eY = cudaMemcpyToSymbol(g_cieYNormFactor, &cieYNormF, sizeof(float));
    if (eY != cudaSuccess) {
        fprintf(stderr, "CIE-Y norm upload failed: %s\n", cudaGetErrorString(eY));
        throw std::runtime_error("CIE-Y norm upload failed");
    }
    uploaded = true;
}

// ---------------------------------------------------------------------------
// pkg54c: Jakob-Hanika 2019 RGB→spectrum sigmoid coefficient LUT on the GPU.
//
// Reference: Jakob & Hanika, "A Low-Dimensional Function Space for Efficient
// Spectral Upsampling", Eurographics 2019 (DOI: 10.1111/cgf.13626);
// reference implementation https://github.com/mitsuba-renderer/rgb2spec
// (BSD-3-Clause). The sRGB LUT shipped at data/spectra/rgb_to_spectrum_srgb
// .coeff is 64³ × 3 channels × 3 coefficients ≈ 9 MB — too large for the
// 64 KB __constant__ cap, so we keep it in device global memory and read
// via __device__ pointers populated once at first render.
//
// gpu_jhLookupCoeffs / gpu_jhEvalSpectrum mirror JakobHanikaLut::lookup +
// evalSigmoidCoeffs in src/spectrum.cpp; bit-exact parity is the pkg54c
// SSIM ≥ 0.999 visible-band gate.
// ---------------------------------------------------------------------------
__device__ const float* g_jhLutScale  = nullptr;  // [res]
__device__ const float* g_jhLutCoeffs = nullptr;  // flat [3][res][res][res][3]
__device__ int          g_jhLutRes    = 0;

// Host-side ownership of the device allocation; freed only on process exit
// because the LUT is read-only and re-uploads would be wasteful.
static float* s_jhLutScaleDev  = nullptr;
static float* s_jhLutCoeffsDev = nullptr;

void uploadJakobHanikaLut() {
    static bool uploaded = false;
    if (uploaded) return;

    int          res    = astroray::jakobHanikaLutRes();
    const float* hScale = astroray::jakobHanikaLutScale();
    const float* hCoeff = astroray::jakobHanikaLutCoeffs();
    if (res <= 0 || !hScale || !hCoeff) {
        throw std::runtime_error("Jakob-Hanika LUT host data unavailable");
    }

    size_t scaleBytes  = size_t(res) * sizeof(float);
    size_t coeffsBytes = size_t(3) * size_t(res) * res * res * 3 * sizeof(float);

    cudaError_t e = cudaMalloc(reinterpret_cast<void**>(&s_jhLutScaleDev),
                               scaleBytes);
    if (e == cudaSuccess) {
        e = cudaMalloc(reinterpret_cast<void**>(&s_jhLutCoeffsDev), coeffsBytes);
    }
    if (e == cudaSuccess) {
        e = cudaMemcpy(s_jhLutScaleDev, hScale, scaleBytes,
                       cudaMemcpyHostToDevice);
    }
    if (e == cudaSuccess) {
        e = cudaMemcpy(s_jhLutCoeffsDev, hCoeff, coeffsBytes,
                       cudaMemcpyHostToDevice);
    }
    if (e == cudaSuccess) {
        e = cudaMemcpyToSymbol(g_jhLutScale,  &s_jhLutScaleDev,
                               sizeof(float*));
    }
    if (e == cudaSuccess) {
        e = cudaMemcpyToSymbol(g_jhLutCoeffs, &s_jhLutCoeffsDev,
                               sizeof(float*));
    }
    if (e == cudaSuccess) {
        e = cudaMemcpyToSymbol(g_jhLutRes, &res, sizeof(int));
    }
    if (e != cudaSuccess) {
        fprintf(stderr, "uploadJakobHanikaLut failed: %s\n",
                cudaGetErrorString(e));
        throw std::runtime_error(cudaGetErrorString(e));
    }
    uploaded = true;
}

// Trilinear interpolation in the JH coefficient cube. Mirrors
// JakobHanikaLut::lookup() in src/spectrum.cpp exactly. TU-local: only
// gpu_jhEvalSpectrum below uses it.
__device__ inline void gpu_jhLookupCoeffs(
    float r, float g, float b, float& c0, float& c1, float& c2)
{
    int res = g_jhLutRes;
    if (res <= 0) { c0 = 0.f; c1 = 0.f; c2 = -1e20f; return; }

    // Clamp to [0, 1] (CPU RGBAlbedoSpectrum constructor does the same).
    r = fminf(fmaxf(r, 0.f), 1.f);
    g = fminf(fmaxf(g, 0.f), 1.f);
    b = fminf(fmaxf(b, 0.f), 1.f);

    int   i    = 0;
    float vMax = r;
    if (g > vMax) { i = 1; vMax = g; }
    if (b > vMax) { i = 2; vMax = b; }
    if (vMax <= 1e-8f) { c0 = 0.f; c1 = 0.f; c2 = -1e20f; return; }

    float comp[3] = { r, g, b };
    int   o0 = (i + 1) % 3;
    int   o1 = (i + 2) % 3;
    float x  = comp[o0] / vMax;
    float y  = comp[o1] / vMax;
    float z  = vMax;

    int   resM1 = res - 1;
    const float* scale = g_jhLutScale;

    // Locate k such that scale[k] <= z <= scale[k+1].
    int k = 0;
    while (k + 1 < resM1 && scale[k + 1] < z) ++k;
    float denomZ = scale[k + 1] - scale[k];
    float tz = (denomZ > 0.f) ? (z - scale[k]) / denomZ : 0.f;
    tz = fminf(fmaxf(tz, 0.f), 1.f);

    float fx = x * float(resM1);
    float fy = y * float(resM1);
    int   x0 = (int)fx;  if (x0 < 0) x0 = 0;  if (x0 > resM1 - 1) x0 = resM1 - 1;
    int   y0 = (int)fy;  if (y0 < 0) y0 = 0;  if (y0 > resM1 - 1) y0 = resM1 - 1;
    float tx = fminf(fmaxf(fx - float(x0), 0.f), 1.f);
    float ty = fminf(fmaxf(fy - float(y0), 0.f), 1.f);

    // Flat layout: coeffs[i][z][y][x][comp]
    const float* coeffs = g_jhLutCoeffs;
    auto entry = [&] __device__ (int zi, int yi, int xi) -> const float* {
        size_t idx = (((size_t(i) * res + zi) * res + yi) * res + xi) * 3;
        return coeffs + idx;
    };
    const float* p000 = entry(k,     y0,     x0    );
    const float* p100 = entry(k,     y0,     x0 + 1);
    const float* p010 = entry(k,     y0 + 1, x0    );
    const float* p110 = entry(k,     y0 + 1, x0 + 1);
    const float* p001 = entry(k + 1, y0,     x0    );
    const float* p101 = entry(k + 1, y0,     x0 + 1);
    const float* p011 = entry(k + 1, y0 + 1, x0    );
    const float* p111 = entry(k + 1, y0 + 1, x0 + 1);

    float out[3];
    #pragma unroll
    for (int comp_i = 0; comp_i < 3; ++comp_i) {
        float cLow  = (p000[comp_i] * (1.f - tx) + p100[comp_i] * tx) * (1.f - ty)
                    + (p010[comp_i] * (1.f - tx) + p110[comp_i] * tx) * ty;
        float cHigh = (p001[comp_i] * (1.f - tx) + p101[comp_i] * tx) * (1.f - ty)
                    + (p011[comp_i] * (1.f - tx) + p111[comp_i] * tx) * ty;
        out[comp_i] = cLow * (1.f - tz) + cHigh * tz;
    }
    c0 = out[0];  c1 = out[1];  c2 = out[2];
}

// Per-wavelength upsampled reflectance, mirroring CPU
// RGBAlbedoSpectrum::sample → evalSigmoidCoeffs.
__device__ float gpu_jhEvalSpectrum(const GVec3& rgb, float lambda) {
    float c0, c1, c2;
    gpu_jhLookupCoeffs(rgb.x, rgb.y, rgb.z, c0, c1, c2);
    return astroray::jhEvalSpectrumF(c0, c1, c2, lambda);
}

// Mirror of astroray::sampleD65 in src/spectrum.cpp — linear lookup into
// the D65 SPD scaled by the normalization factor so unit white emission
// integrates to Y = 1 against the CIE 1964 10° observer.
__device__ float gpu_sampleD65(float lambda) {
    if (lambda < G_CMF_LAMBDA_MIN || lambda > G_CMF_LAMBDA_MAX) return 0.f;
    float idx = (lambda - G_CMF_LAMBDA_MIN) / G_CMF_LAMBDA_STEP;
    int   i   = (int)idx;
    if (i >= G_CMF_COUNT - 1) return g_d65SPD[G_CMF_COUNT - 1] * g_d65NormFactor;
    float t = idx - (float)i;
    float v = g_d65SPD[i] * (1.f - t) + g_d65SPD[i + 1] * t;
    return v * g_d65NormFactor;
}

// pkg142 hardware-verifier regression: photometric anchor for RGBUnbounded
// EMISSION use (GSPEC_RGB_UNBOUNDED branch in gpu_materials.h), mirroring
// CPU astroray::cieYIntegral(). See g_cieYNormFactor's doc comment above.
__device__ float gpu_cieYNormFactor() {
    return g_cieYNormFactor;
}

// pkg55-B' Session N+6: non-inline export of spectrumToXYZ for the wavefront
// stage_advance TU (linked via -rdc=true). The inline spectrumToXYZ in
// gpu_spectral_tables.h is TU-local over the constant CMF tables; this wrapper
// is the ONE cross-TU entry so the wavefront's Russian-roulette luminance uses
// the identical CMF integration the megakernel uses.
__device__ GVec3 gpu_spectrum_to_xyz(
    const GSampledSpectrum& s, const GSampledWavelengths& wl)
{
    return spectrumToXYZ(s, wl);
}
