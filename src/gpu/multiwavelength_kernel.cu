// multiwavelength_kernel.cu — pkg54 / pkg54a / pkg54b
// GPU port of multiwavelength_path_tracer.
//
// Megakernel that mirrors the CPU integrator
// (plugins/integrators/multiwavelength_path_tracer.cpp): naive spectral path
// tracing with sampled wavelengths in a configurable [lambdaMin, lambdaMax]
// band, no NEE, emissive-on-hit termination. Output is either:
//   * luminance-grey (mean of the 4 sampled radiances) for non-visible bands,
//   * linear sRGB derived from CIE 1964 10° XYZ for bands inside the visible
//     range. The CMF tables are the same baked data the CPU integrator uses
//     (data/spectra/cie_cmf.inc), uploaded once to constant memory — this is
//     the pkg54b parity fix that replaced an earlier Wyman/Sloan/Shirley 2013
//     1931 2° analytic fit.
//
// Spectral profile dispatch (pkg54a) honours `Material::setSpectralProfile`
// on-device: per-material profileIndex into a constant-memory reflectance
// table populated by scene_upload.cu; the spectral evaluation step mirrors
// `Material::evalSpectralExt` (visible λ → RGB-to-spectrum; non-visible λ →
// profile.reflectance(λ)·cosθ/π, or 0 when no profile is attached).

#include "astroray/gpu_types.h"
#include "astroray/gpu_materials.h"
#include "astroray/gpu_bvh.h"
#include "light_tree_device.cuh"  // pkg86-B: gpu_light_tree_pick
#include "astroray/gpu_env_spectral.cuh"  // pkg55-B' N+6: shared env-miss eval
#include "astroray/spectrum.h"  // jhEvalSpectrumF + JH LUT accessors (pkg54c)
#include "astroray/manifold/sms_attempt_device.cuh"  // pkg64-gpu Phase 2
#include "astroray/gpu_photon_store.h"  // pkg113 Phase 3: GPhotonGrid + photonGridGather
#include "profile.h"  // pkg55-A: env-gated CUDA-event + NVTX instrumentation

#include <cuda_runtime.h>
#include <curand_kernel.h>
#include <cstdio>
#include <stdexcept>

#ifndef M_PI_F
#  define M_PI_F 3.14159265358979323846f
#endif

// ---------------------------------------------------------------------------
// pkg54a: Device-side spectral profile table (constant memory).
//
// One flat buffer of G_MAX_PROFILES * G_PROFILE_SAMPLES floats. Slot i covers
// reflectance of profile i at lambda = G_PROFILE_LAMBDA_MIN +
// s * G_PROFILE_LAMBDA_STEP. -1 in GMaterial.profileIndex means "no profile";
// the kernel then mirrors the CPU `Material::evalSpectralExt` no-profile
// fallback (zero outside [380, 780]).
// ---------------------------------------------------------------------------
__constant__ float g_profileTable[G_MAX_PROFILES * G_PROFILE_SAMPLES];

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
// Sampled wavelengths in [lmin, lmax] — stratified hero-wavelength sampler,
// matches the CPU SampledWavelengths::sampleUniform(u, lmin, lmax) layout.
// ---------------------------------------------------------------------------
__device__ inline GSampledWavelengths gpu_sampleBandWavelengths(
    curandState* rng, float lmin, float lmax)
{
    // Hero-wavelength layout MUST match CPU SampledWavelengths::sampleUniform
    // (src/spectrum.cpp:82) and the wavefront sampler (stage_init.cu:64):
    //   hero    = lmin + u*span          (hero spans the FULL band)
    //   lam[i]  = hero + i*step          (stratified secondaries)
    //   lam[i] -= span  if lam[i] > lmax (wrap into range)
    // The previous `(u+i)/N` form confined the hero lam[0] to the first 1/N of
    // the band (violet/blue with a [380,780] prism band) — the SMS caustic
    // colorizes off lam[0], so that produced a violet caustic instead of a
    // full rainbow. See pkg64-gpu-session2-research.md (afternoon update).
    GSampledWavelengths wl;
    float u    = curand_uniform(rng);
    float span = lmax - lmin;
    float step = span / float(G_SPECTRUM_SAMPLES);
    float hero = lmin + u * span;
    float pdf  = 1.f / span;
    for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) {
        float lam = hero + float(i) * step;
        if (lam > lmax) lam -= span;
        wl.lambda[i] = lam;
        wl.pdf[i]    = pdf;
    }
    return wl;
}

// ---------------------------------------------------------------------------
// pkg54b: CIE 1964 10° CMF tables in constant memory — same data as the CPU
// `cieCmf1964_10deg` lookup in src/spectrum.cpp, so visible-band CPU vs GPU
// XYZ values match within float-precision instead of the ~5 % observer bias
// the previous Wyman/Sloan/Shirley 2013 1931 2° fits introduced.
//
// Tables are 471 samples × 3 channels × 4 bytes = 5.6 KB (well under the
// 64 KB constant-memory budget). Layout matches data/spectra/cie_cmf.inc:
// 1 nm step over [360, 830] nm.
// ---------------------------------------------------------------------------
static constexpr int   G_CMF_COUNT      = 471;
static constexpr float G_CMF_LAMBDA_MIN = 360.0f;
static constexpr float G_CMF_LAMBDA_MAX = 830.0f;
static constexpr float G_CMF_LAMBDA_STEP = 1.0f;

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
// JakobHanikaLut::lookup() in src/spectrum.cpp exactly.
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

// pkg55-B' Session N+6: non-inline export of spectrumToXYZ for the wavefront
// stage_advance TU (linked via -rdc=true). The inline function above is
// TU-local over the constant CMF tables; this wrapper is the ONE cross-TU
// entry so the wavefront's Russian-roulette luminance uses the identical
// CMF integration the megakernel uses.
__device__ GVec3 gpu_spectrum_to_xyz(
    const GSampledSpectrum& s, const GSampledWavelengths& wl)
{
    return spectrumToXYZ(s, wl);
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

// ---------------------------------------------------------------------------
// Rayleigh sky scale — λ^-4 relative to 550 nm, matches CPU integrator.
// ---------------------------------------------------------------------------
__device__ inline float rayleighScale(float lambda_nm) {
    float r = 550.f / lambda_nm;
    return r * r * r * r;
}

__device__ inline bool isInsideVisible(float lmin, float lmax) {
    return lmin >= 380.f - 0.5f && lmax <= 780.f + 0.5f;
}

// ---------------------------------------------------------------------------
// MIS power heuristic — mirrors CPU pathTraceSpectral (raytracer.h:2420)
//   wt = a*a / (a*a + b*b + 1e-8) ; and path_trace_kernel.cu::powerHeuristic.
// ---------------------------------------------------------------------------
__device__ inline float gpu_mw_powerHeuristic(float a, float b) {
    return (a * a) / (a * a + b * b + 1e-8f);
}

// ---------------------------------------------------------------------------
// Spectral next-event estimation — mirrors CPU Renderer::pathTraceSpectral
// area-light NEE (include/raytracer.h:2405-2424): power-weighted light
// selection, area-light point/solid-angle sampling, occlusion test, spectral
// f * L, and an MIS power heuristic against the BSDF pdf. The area-light
// geometric sampling (sphere solid angle, triangle area->solid-angle pdf)
// reuses the exact construction already validated in
// src/gpu/path_trace_kernel.cu::sampleDirectGPU (same codebase, CPU-faithful
// port of Renderer::sampleDirect). CLAUDE.md §6 — no new algorithm.
//
// This closes the ~2x deficit caused by the previous "no NEE" megakernel:
// the emissive-on-hit term is gated by (bounce==0 || wasSpecular) exactly
// like the CPU, so without NEE all diffuse->emitter direct light was dropped.
// ---------------------------------------------------------------------------
__device__ GSampledSpectrum sampleDirectSpectralMW(
    const GHitRecord& rec, const GVec3& wo,
    const GSampledWavelengths& lambdas,
    const GTLASNode*  tlas,        // pkg114
    const GInstance*  instances,   // pkg114
    const GBLAS*      blas,        // pkg114
    const GBVHNode*  bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const GMaterial*  materials,
    const GLight*     lights, int numLights, float totalLightPower,
    GLightTreeView    lightTree,  // pkg86-B
    float             time,         // pkg88-C.0: path shutter time for shadow rays
    const GVec3*      motionVerts,  // pkg88-C.0 (nullptr = static)
    curandState*      rng)
{
    GSampledSpectrum direct(0.f);
    if (rec.isDelta || numLights <= 0 || totalLightPower <= 0.f) return direct;

    const GMaterial& mat = materials[rec.materialId];

    // Light selection: tree-importance descent (pkg86-B, Conty 2018 via
    // Cycles kernel/light/tree.h) when the tree is resident, else the
    // power-weighted CDF (mirrors LightList::sample).
    int   li = 0;
    float selPdf;
    if (lightTree.enabled) {
        float treePdf = 0.f;
        int eIdx = gpu_light_tree_pick(lightTree, rec.point, rec.normal,
                                       curand_uniform(rng), &treePdf);
        if (eIdx < 0 || treePdf <= 0.f) return direct;
        li = lightTree.emitters[eIdx].lightIndex;
        selPdf = treePdf;
    } else {
        float u = curand_uniform(rng) * totalLightPower;
        for (int i = 0; i < numLights; ++i) { if (u <= lights[i].cumulativePower) { li = i; break; } li = i; }
        selPdf = lights[li].power / totalLightPower;
    }
    int primIdx  = lights[li].primitiveIndex;
    if (primIdx < 0) return direct;

    const GPrimitive& lp = prims[primIdx];
    if (lp.type == GPRIM_SKIP) return direct;

    GVec3 wi;
    float lightPdf;     // solid-angle pdf (incl. selPdf), mirrors LightList::sample s.pdf
    float maxDist;      // shadow-ray extent
    int   lightMatId;
    bool  lightFront;

    if (lp.type == GPRIM_SPHERE) {
        const GSphere& s = spheres[lp.index];
        GVec3 toC    = s.center - rec.point;
        float distSq = toC.length2();
        if (distSq <= s.radius * s.radius + 1e-8f) return direct;
        GVec3 dir   = toC.normalized();
        float cosTM = sqrtf(fmaxf(0.f, 1.f - s.radius * s.radius / distSq));
        if (cosTM >= 1.f) return direct;
        float z   = 1.f + curand_uniform(rng) * (cosTM - 1.f);
        float phi = 2.f * M_PI_F * curand_uniform(rng);
        GVec3 tu, tv; gpu_buildONB(dir, tu, tv);
        float sinTh = sqrtf(fmaxf(0.f, 1.f - z * z));
        wi          = (tu * cosf(phi) * sinTh + tv * sinf(phi) * sinTh + dir * z).normalized();
        lightPdf    = (1.f / (2.f * M_PI_F * (1.f - cosTM))) * selPdf;
        maxDist     = 1e30f;       // hit-the-sphere check below bounds it
        lightMatId  = s.materialId;
        GHitRecord sh;
        if (!gpu_tlas_hit(tlas, instances, blas, bvhNodes, prims, tris, spheres,
                         GRay(rec.point, wi, time), 0.001f, maxDist, sh, motionVerts) ||
            sh.materialId != lightMatId)
            return direct;
        lightFront = sh.frontFace;
    } else {
        const GTriangle& t = tris[lp.index];
        float r1 = curand_uniform(rng), r2 = curand_uniform(rng);
        if (r1 + r2 > 1.f) { r1 = 1.f - r1; r2 = 1.f - r2; }
        GVec3 lpos = t.v0 + (t.v1 - t.v0) * r1 + (t.v2 - t.v0) * r2;
        GVec3 d    = lpos - rec.point;
        float dist = d.length();
        wi         = d * (1.f / fmaxf(dist, 1e-8f));
        GVec3 e1   = t.v1 - t.v0, e2 = t.v2 - t.v0;
        float area = e1.cross(e2).length() * 0.5f;
        float NdotWi = fabsf(t.n0.dot(wi));
        if (NdotWi < 1e-8f || area < 1e-8f) return direct;
        lightPdf   = (dist * dist) / (NdotWi * area) * selPdf;
        maxDist    = dist - 0.001f;
        lightMatId = t.materialId;
        lightFront = true;
        GHitRecord sh;
        if (gpu_tlas_hit(tlas, instances, blas, bvhNodes, prims, tris, spheres,
                        GRay(rec.point, wi, time), 0.001f, maxDist, sh, motionVerts))
            return direct;          // occluded
    }

    if (lightPdf <= 0.f) return direct;

    // Spectral BSDF and emission — mirrors CPU pathTraceSpectral lines
    // 2414-2421:  f_spec = evalSpectral ; L_spec = emission_spec (illuminant).
    GSampledSpectrum f_spec =
        gpu_material_eval_spectral(mat, const_cast<GHitRecord&>(rec), wo, wi, lambdas);
    GSampledSpectrum L_spec =
        gpu_material_emitted_spectral(materials[lightMatId], lightFront, lambdas);
    if (f_spec.maxValue() <= 0.f || L_spec.maxValue() <= 0.f) return direct;

    float bsdfPdf = gpu_material_pdf(mat, rec, wo, wi);
    float wt      = gpu_mw_powerHeuristic(lightPdf, bsdfPdf);
    // color += throughput * f_spec * L_spec * (wt / (ls.pdf + 0.001f))
    return f_spec * L_spec * (wt / (lightPdf + 0.001f));
}

// ---------------------------------------------------------------------------
// Spectral path trace — area-light NEE + MIS, mirroring the CPU
// Renderer::pathTraceSpectral integrator (the CPU `path_tracer` selects this;
// see plugins/integrators/spectral_path_tracer.cpp). The emissive-on-hit term
// stays gated by (bounce==0 || wasSpecular) — the BSDF-sampling half of MIS —
// while sampleDirectSpectralMW supplies the area-light direct term.
// Returns raw per-sample SampledSpectrum radiance.
// ---------------------------------------------------------------------------
__device__ GSampledSpectrum tracePathMW(
    GRay ray, int maxDepth,
    int worldMaxBounces,  // pkg55-B' N+6 follow-up: env gate, raytracer.h:2412
    GSampledWavelengths& lambdas,
    bool useLuminanceOutput,
    bool enableNEE,
    bool useCaustics,  // pkg64-gpu Phase 2
    const GTLASNode*  tlas,        // pkg114
    const GInstance*  instances,   // pkg114
    const GBLAS*      blas,        // pkg114
    const GBVHNode*  bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const GMaterial*  materials,
    const GLight*     lights, int numLights, float totalLightPower,
    GLightTreeView    lightTree,  // pkg86-B
    const astroray::manifold::device::GSMSCaster* smsCasters, int numSMSCasters,  // pkg64-gpu Phase 2
    const GEnvMap&    envMap,
    const GVec3&      backgroundColor,
    bool              hasBackgroundColor,
    GRay              primaryRay,  // pkg64-gpu Phase 2: needed for SMS wo_eye
    const GVec3*      motionVerts,  // pkg88-C.0 (nullptr = static)
    curandState*      rng)
{
    const int rrDepth = 3;
    GSampledSpectrum color(0.f);
    GSampledSpectrum throughput(1.f);
    bool wasSpecular = true;

    for (int bounce = 0; bounce < maxDepth; ++bounce) {
        GHitRecord rec;
        if (!gpu_tlas_hit(tlas, instances, blas, bvhNodes, prims, tris, spheres,
                         ray, 0.001f, 1e30f, rec, motionVerts)) {
            // Environment / background contribution. The bg/envmap/sky chain
            // is factored into gpu_env_miss_spectral (gpu_env_spectral.cuh,
            // pkg55-B' Session N+6) so the wavefront stage_advance shares ONE
            // implementation; the luminance-band Rayleigh fallback stays here
            // (needs this TU's rayleighScale, no CPU-wavefront twin).
            //
            // Gated by worldMaxBounces (pkg55-B' N+6 follow-up): mirrors CPU
            // pathTraceSpectral (raytracer.h:2412) and the CPU/GPU wavefront
            // (path_kernel.cpp:192) — the path dies on miss either way; env
            // radiance is only accumulated for bounce <= gate.
            if (bounce > worldMaxBounces) break;
            GSampledSpectrum envSpec(0.f);
            GVec3 dir = ray.direction.normalized();
            if (useLuminanceOutput && !hasBackgroundColor && !envMap.loaded) {
                // Rayleigh sky fallback for outside-visible bands.
                for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) {
                    float scale = rayleighScale(lambdas.lambda[i]);
                    float horizonFade = 0.5f * (dir.y + 1.f);
                    envSpec.v[i] = 0.08f * scale * (0.5f + horizonFade);
                }
            } else {
                envSpec = gpu_env_miss_spectral(
                    envMap, backgroundColor, hasBackgroundColor, dir, lambdas);
            }
            color += throughput * envSpec;
            break;
        }

        const GMaterial& mat = materials[rec.materialId];

        // Emission — mirrors CPU path: terminates path on emissive hit.
        GSampledSpectrum Le = gpu_material_emitted_spectral(mat, rec.frontFace, lambdas);
        if (Le.maxValue() > 0.f) {
            if (bounce == 0 || wasSpecular)
                color += throughput * Le;
            break;
        }

        GVec3 wo = -ray.direction.normalized();

        // Area-light NEE (MIS via power heuristic). Skipped on delta lobes.
        // Mirrors CPU pathTraceSpectral (include/raytracer.h:2405-2424).
        // enableNEE is false when the kernel mirrors the naive no-NEE
        // MultiwavelengthPathTracer (gated by integrator name in
        // module/blender_module.cpp).
        if (enableNEE && !rec.isDelta && numLights > 0) {
            color += throughput * sampleDirectSpectralMW(
                rec, wo, lambdas, tlas, instances, blas, bvhNodes, prims, tris, spheres, materials,
                lights, numLights, totalLightPower, lightTree,
                ray.time, motionVerts,  // pkg88-C.0
                rng);
        }

        // pkg64-gpu Phase 2: SMS caustic attempt at non-delta vertices.
        // Mirrors CPU pathTraceSpectral (include/raytracer.h:2427-2437):
        // disjoint-strategy additive MIS (w_sms ≈ 1, w_nee ≈ 1 for their
        // respective sample sets; balance heuristic reduction).
        if (useCaustics && !rec.isDelta && numSMSCasters > 0 && numLights > 0) {
            // Sample one caster uniformly (mirrors CPU gatherSphereCasters + pick).
            int cIdx = (int)(curand_uniform(rng) * numSMSCasters);
            if (cIdx >= numSMSCasters) cIdx = numSMSCasters - 1;
            const auto& C = smsCasters[cIdx];
            float casterPickPdf = 1.0f / float(numSMSCasters);

            // Sample one light (mirrors CPU hook's light sampling).
            // Power-weighted selection via CDF (same pattern as sampleDirectSpectralMW).
            float u = curand_uniform(rng) * totalLightPower;
            int lIdx = numLights - 1;
            for (int li = 0; li < numLights; ++li) {
                if (u < lights[li].cumulativePower) { lIdx = li; break; }
            }
            const GLight& lt = lights[lIdx];
            int primIdx = lt.primitiveIndex;
            if (primIdx < 0 || primIdx >= (int)~0u) {
                // Invalid light index; skip SMS.
            } else {
                const GPrimitive& lp = prims[primIdx];
                astroray::manifold::device::GLightSample ls;
                ls.pdf = 0.0f;

                if (lp.type == GPRIM_SPHERE) {
                    const GSphere& lsph = spheres[lp.index];
                    // Uniform sphere surface sample
                    float u1 = curand_uniform(rng);
                    float u2 = curand_uniform(rng);
                    float z = 1.0f - 2.0f * u1;
                    float r = sqrtf(fmaxf(0.0f, 1.0f - z * z));
                    float phi = 2.0f * M_PI_F * u2;
                    GVec3 localP(r * cosf(phi), r * sinf(phi), z);
                    ls.position = lsph.center + localP * lsph.radius;
                    ls.normal = localP;
                    ls.pdf = 1.0f / (4.0f * M_PI_F * lsph.radius * lsph.radius);
                    // Emission
                    const GMaterial& lmat = materials[lsph.materialId];
                    GSampledSpectrum emitSpec = gpu_material_emitted_spectral(lmat, true, lambdas);
                    GVec3 xyz = spectrumToXYZ(emitSpec, lambdas);
                    // Convert XYZ to linear sRGB for GLightSample.emission
                    float r_ =  3.2406f * xyz.x - 1.5372f * xyz.y - 0.4986f * xyz.z;
                    float g_ = -0.9689f * xyz.x + 1.8758f * xyz.y + 0.0415f * xyz.z;
                    float b_ =  0.0557f * xyz.x - 0.2040f * xyz.y + 1.0570f * xyz.z;
                    ls.emission = GVec3(r_, g_, b_);
                } else {
                    // Triangle or other primitive — skip for Phase 2 (sphere caster only).
                    ls.pdf = 0.0f;
                }

                if (ls.pdf > 0.0f) {
                    // Get caster material IOR at hero wavelength.
                    // C.primId is index into prims[]; prims[C.primId].index is the sphere index.
                    float eta = 1.0f;
                    const GPrimitive& casterPrim = prims[C.primId];
                    if (casterPrim.type == GPRIM_SPHERE) {
                        const GSphere& casterSph = spheres[casterPrim.index];
                        const GMaterial& casterMat = materials[casterSph.materialId];
                        if (casterMat.type == GMAT_DIELECTRIC) {
                            eta = 1.0f / casterMat.ior;
                        }
                    }

                    astroray::manifold::device::GSMSConfig cfg;
                    cfg.seeds = 1;
                    cfg.maxIterations = 20;
                    cfg.tolerance = 1e-4f;
                    cfg.contribClamp = 4.0f;

                    float r1 = curand_uniform(rng);
                    float r2 = curand_uniform(rng);

                    GSampledSpectrum fSpec;
                    float w = 0.0f, Tr = 0.0f;
                    GVec3 Le(0.0f), wi(0.0f);

                    if (astroray::manifold::device::runSMSAttemptDevice(
                            bvhNodes, prims, tris, spheres, materials,
                            rec, primaryRay, lambdas, r1, r2, C, eta, casterPickPdf,
                            ls, cfg, fSpec, w, Le, Tr, wi)) {
                        // Clamp and accumulate hero-channel contribution
                        float fHero = fSpec.v[0];
                        // Convert Le (linear sRGB) to spectral
                        GSampledSpectrum LeSpec = gpu_rgbToSampledSpectrum(Le, lambdas, GSPEC_RGB_ILLUMINANT);
                        float LeHero = LeSpec.v[0];
                        float sampleHero = fHero * LeHero * Tr * w;
                        if (sampleHero > cfg.contribClamp) sampleHero = cfg.contribClamp;
                        if (sampleHero < 0.0f) sampleHero = 0.0f;

                        // Additive MIS: write contribution to hero channel only (matches CPU hook).
                        GSampledSpectrum smsContrib(0.0f);
                        smsContrib.v[0] = sampleHero;
                        color += throughput * smsContrib;
                    }
                }
            }
        }

        // Russian roulette
        if (bounce > rrDepth) {
            float p;
            if (useLuminanceOutput) {
                float avg = 0.f;
                for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) avg += throughput.v[i];
                p = fminf(0.95f, fmaxf(0.f, avg / float(G_SPECTRUM_SAMPLES)));
            } else {
                GVec3 thrXYZ = spectrumToXYZ(throughput, lambdas);
                p = fminf(0.95f, fmaxf(0.f, thrXYZ.y));
            }
            if (curand_uniform(rng) > p) break;
            if (p > 0.f) throughput *= (1.f / p);
        }

        // BSDF sample.
        GBSDFSample bs = gpu_material_sample_spectral(mat, rec, wo, lambdas, rng);
        if (bs.pdf <= 0.f) break;
        wasSpecular = bs.isDelta;

        // pkg54a: profile-aware spectral override for non-delta paths.
        // Mirrors CPU `Material::evalSpectralExt`:
        //   * visible λ → keep gpu_rgbToSampledSpectrum result (bs.fSpectral),
        //   * non-visible λ + profile → reflectance(λ) * cosθ / π,
        //   * non-visible λ + no profile → 0.
        // Delta materials (specular) keep the RGB-derived spectrum unchanged.
        if (!bs.isDelta) {
            float cosTheta = fmaxf(0.f, rec.normal.dot(bs.wi));
            for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) {
                float lam = lambdas.lambda[i];
                if (lam < 380.f || lam > 780.f) {
                    if (mat.profileIndex >= 0) {
                        bs.fSpectral.v[i] =
                            gpu_profile_reflectance(mat.profileIndex, lam)
                            * cosTheta / M_PI_F;
                    } else {
                        bs.fSpectral.v[i] = 0.f;
                    }
                }
            }
        }

        throughput *= bs.fSpectral * (1.f / (bs.pdf + 0.001f));

        // Throughput clamp (firefly guard, matches CPU).
        float maxC = throughput.maxValue();
        if (maxC > 10.f) throughput *= (10.f / maxC);

        // pkg88-C.0: bounce rays inherit the path's shutter time.
        ray = GRay(rec.point, bs.wi, ray.time);
    }

    return color;
}

// ---------------------------------------------------------------------------
// Multiwavelength megakernel
// ---------------------------------------------------------------------------
// pkg88-C.0: base-2 radical inverse for the per-spp shutter time. Same
// sampler as the RGB megakernel's Phase-A camera time (path_trace_kernel.cu
// haltonBase2) — TU-local copy because both kernels keep device helpers
// file-static.
__device__ inline float gpu_mw_haltonBase2(int index) {
    float result = 0.0f;
    float f = 1.0f;
    int i = index;
    while (i > 0) {
        f = f / 2.0f;
        result += f * (i % 2);
        i = i / 2;
    }
    return result;
}

__global__ void multiwavelengthKernel(
    float* framebuffer, int width, int height,
    int samplesPerPixel, int maxDepth,
    int worldMaxBounces,  // pkg55-B' N+6 follow-up: env gate, raytracer.h:2412
    float lambdaMin, float lambdaMax,
    bool  useLuminanceOutput,
    bool  enableNEE,
    bool  useCaustics,  // pkg64-gpu Phase 2
    const GTLASNode*  tlas,        // pkg114
    const GInstance*  instances,   // pkg114
    const GBLAS*      blas,        // pkg114
    const GBVHNode*  bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const GMaterial*  materials,
    const GLight*     lights, int numLights, float totalLightPower,
    GLightTreeView    lightTree,  // pkg86-B
    const astroray::manifold::device::GSMSCaster* smsCasters, int numSMSCasters,  // pkg64-gpu Phase 2
    GEnvMap envMap,
    GCameraParams cam,
    GVec3 backgroundColor, bool hasBackgroundColor,
    astroray::photon::gpu::GPhotonGrid photonGrid, bool hasPhotonGrid,  // pkg113 Phase 3
    float photonScale,                                                   // pkg113 Phase 3
    const GVec3* d_motionVertices,  // pkg88-C.0 (nullptr = static scene)
    curandState* rngStates)
{
    int pixelIdx = blockIdx.x * blockDim.x + threadIdx.x;
    int totalPixels = width * height;
    if (pixelIdx >= totalPixels) return;

    int px = pixelIdx % width;
    int py = pixelIdx / width;

    curandState localRng = rngStates[pixelIdx];

    // pkg85-D: accumulate in XYZ (or luminance-triplet) across SPP, then convert
    // to linear sRGB ONCE at the end. The CPU integrator does the same:
    //   raytracer.h:2548  sCol = finiteVecOrZero(XYZ)
    //   raytracer.h:2550  firefly clamp on XYZ.Y > 20
    //   raytracer.h:2552  color += sCol     (XYZ accumulation)
    //   raytracer.h:2579  color /= samples
    //   raytracer.h:2595  color = xyzToLinearSRGB(color)   (single conversion)
    // The prior order (per-sample xyzToLinearSRGB → average) does not commute
    // with averaging because xyzToLinearSRGB's negative-channel lift is
    // non-linear; bluish HDRI samples produce negative R that the lift adds
    // to G/B every sample, biasing green/blue upward. SSIM-killer.
    GVec3 colorAccum(0.f);
    for (int s = 0; s < samplesPerPixel; ++s) {
        float u = (px + curand_uniform(&localRng)) / (width  - 1);
        float v = 1.f - (py + curand_uniform(&localRng)) / (height - 1);

        GVec3 rd     = gpu_randomInUnitDisk(&localRng) * cam.lensRadius;
        GVec3 offset = cam.u * rd.x + cam.v * rd.y;
        GVec3 dir    = cam.lowerLeft + cam.horizontal*u + cam.vertical*v
                       - cam.origin - offset;
        GRay ray(cam.origin + offset, dir);
        // pkg88-C.0: per-spp shutter time for deformation motion (independent
        // Halton base-2, same policy as the RGB megakernel / Phase A; spec
        // Q-Owner-4: ONE consistent policy). NOTE: the MW kernel's camera is
        // not shutter-interpolated (Phase-A camera MB lives in the RGB kernel
        // only) — geometry motion works here, camera motion is a known gap.
        ray.time = gpu_mw_haltonBase2(s + 1);

        GSampledWavelengths lambdas =
            gpu_sampleBandWavelengths(&localRng, lambdaMin, lambdaMax);

        GSampledSpectrum rad = tracePathMW(
            ray, maxDepth, worldMaxBounces,
            lambdas, useLuminanceOutput, enableNEE, useCaustics,
            tlas, instances, blas,  // pkg114
            bvhNodes, prims, tris, spheres, materials,
            lights, numLights, totalLightPower,
            lightTree,  // pkg86-B
            smsCasters, numSMSCasters,
            envMap, backgroundColor, hasBackgroundColor,
            ray,  // primaryRay for SMS wo_eye
            d_motionVertices,  // pkg88-C.0
            &localRng);

        GVec3 sample;
        if (useLuminanceOutput) {
            float L = 0.f;
            for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) L += rad.v[i];
            L = fmaxf(0.f, L / float(G_SPECTRUM_SAMPLES));
            sample = GVec3(L, L, L);
        } else {
            // XYZ tristimulus (linear, additive, matches CPU sCol).
            sample = spectrumToXYZ(rad, lambdas);
        }

        // pkg113 Phase 3: photon-map caustic gather at the primary first hit,
        // added in XYZ space — the device twin of spectral_path_tracer.cpp::
        // sampleFull (l.207-221), which re-hits the first surface after the
        // spectral path trace and adds albedo·E·causticScale to the XYZ. The grid
        // gather returns E = (1/πr²)Σpower (Jensen 2000 Eq. 8); causticScale folds
        // the Lambertian 1/π. Only meaningful for the visible-band (XYZ) output.
        if (hasPhotonGrid && !useLuminanceOutput && photonGrid.numPhotons > 0) {
            GHitRecord pr;
            // pkg88-C.0: re-hit the primary at its shutter time (ray carries it).
            if (gpu_tlas_hit(tlas, instances, blas, bvhNodes, prims, tris, spheres,
                            ray, 0.001f, 1e30f, pr, d_motionVertices)) {
                const GMaterial& pmat = materials[pr.materialId];
                if (pmat.emissionIntensity <= 0.0f) {
                    int found = 0;
                    GVec3 E = astroray::photon::gpu::photonGridGatherKnn(
                        photonGrid, pr.point, 50, 1.1f, found);
                    if (found > 0) {
                        GVec3 alb = pmat.baseColor;
                        sample += GVec3(alb.x * E.x, alb.y * E.y, alb.z * E.z)
                                  * photonScale;
                    }
                }
            }
        }

        // finiteVecOrZero — replace NaN/Inf with zero (matches CPU).
        sample.x = isfinite(sample.x) ? sample.x : 0.f;
        sample.y = isfinite(sample.y) ? sample.y : 0.f;
        sample.z = isfinite(sample.z) ? sample.z : 0.f;

        // Per-sample firefly clamp on XYZ.Y (photometric luminance, matches CPU
        // raytracer.h:2550). For useLuminanceOutput the triplet is (L,L,L) so
        // .y == L; same clamp applies.
        float sLum = sample.y;
        if (sLum > 20.f) sample *= (20.f / sLum);

        colorAccum += sample;
    }

    colorAccum /= float(samplesPerPixel);

    // Single XYZ→sRGB conversion (skipped for useLuminanceOutput — already
    // luminance triplet). Mirrors CPU raytracer.h:2595.
    GVec3 colorRGB = useLuminanceOutput ? colorAccum
                                        : xyzToLinearSRGB_dev(colorAccum);
    colorRGB.x = fmaxf(colorRGB.x, 0.f);
    colorRGB.y = fmaxf(colorRGB.y, 0.f);
    colorRGB.z = fmaxf(colorRGB.z, 0.f);

    framebuffer[pixelIdx*3 + 0] = colorRGB.x;
    framebuffer[pixelIdx*3 + 1] = colorRGB.y;
    framebuffer[pixelIdx*3 + 2] = colorRGB.z;

    rngStates[pixelIdx] = localRng;
}

// ---------------------------------------------------------------------------
// Launcher — called from cuda_renderer.cu
// ---------------------------------------------------------------------------
void launchMultiwavelengthKernel(
    float* d_framebuffer, int width, int height,
    int samplesPerPixel, int maxDepth,
    int worldMaxBounces,  // pkg55-B' N+6 follow-up: env gate, raytracer.h:2412
    float lambdaMin, float lambdaMax, bool useLuminanceOutput,
    bool enableNEE,
    bool useCaustics,  // pkg64-gpu Phase 2
    const GTLASNode*  d_tlas, const GInstance* d_instances, const GBLAS* d_blas,  // pkg114
    const GBVHNode*  d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const GMaterial*  d_materials,
    const GLight*     d_lights, int numLights, float totalLightPower,
    GLightTreeView lightTree,  // pkg86-B
    const astroray::manifold::device::GSMSCaster* d_smsCasters, int numSMSCasters,  // pkg64-gpu Phase 2
    GEnvMap envMap,
    GCameraParams cam,
    GVec3 backgroundColor, bool hasBackgroundColor,
    astroray::photon::gpu::GPhotonGrid photonGrid, bool hasPhotonGrid,  // pkg113 Phase 3
    float photonScale,                                                   // pkg113 Phase 3
    const GVec3* d_motionVertices,  // pkg88-C.0
    curandState* d_rngStates)
{
    int totalPixels    = width * height;
    int threadsPerBlock = 256;
    int blocks         = (totalPixels + threadsPerBlock - 1) / threadsPerBlock;

    {
        astroray::gpu_profile::ScopedTimer _t(
            "multiwavelength_megakernel",
            (const void*)multiwavelengthKernel, blocks, threadsPerBlock);
        multiwavelengthKernel<<<blocks, threadsPerBlock>>>(
            d_framebuffer, width, height, samplesPerPixel, maxDepth,
            worldMaxBounces,
            lambdaMin, lambdaMax, useLuminanceOutput, enableNEE, useCaustics,
            d_tlas, d_instances, d_blas,  // pkg114
            d_bvhNodes, d_prims, d_tris, d_spheres, d_materials,
            d_lights, numLights, totalLightPower,
            lightTree,  // pkg86-B
            d_smsCasters, numSMSCasters,
            envMap, cam, backgroundColor, hasBackgroundColor,
            photonGrid, hasPhotonGrid, photonScale,  // pkg113 Phase 3
            d_motionVertices,  // pkg88-C.0
            d_rngStates);

        cudaError_t err = cudaGetLastError();
        if (err != cudaSuccess) {
            fprintf(stderr, "MW kernel launch error: %s\n", cudaGetErrorString(err));
            throw std::runtime_error(cudaGetErrorString(err));
        }
        // pkg85-B: check the post-launch sync. A discarded error here (e.g.
        // illegal memory access surfaced asynchronously) becomes latent
        // device state that contaminates the next test/renderer.
        cudaError_t syncErr = cudaDeviceSynchronize();
        if (syncErr != cudaSuccess) {
            fprintf(stderr, "MW kernel runtime error: %s\n",
                    cudaGetErrorString(syncErr));
            throw std::runtime_error(cudaGetErrorString(syncErr));
        }
    }
}
