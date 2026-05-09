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
    GSampledWavelengths wl;
    float u = curand_uniform(rng);
    float span = lmax - lmin;
    float pdf = 1.f / span;
    for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) {
        float offset = (u + float(i)) / float(G_SPECTRUM_SAMPLES);
        offset -= floorf(offset);
        wl.lambda[i] = lmin + offset * span;
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
// Spectral path trace — naive, no NEE (mirrors the CPU MW integrator).
// Returns raw per-sample SampledSpectrum radiance.
// ---------------------------------------------------------------------------
__device__ GSampledSpectrum tracePathMW(
    GRay ray, int maxDepth,
    GSampledWavelengths& lambdas,
    bool useLuminanceOutput,
    const GBVHNode*  bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const GMaterial*  materials,
    const GEnvMap&    envMap,
    const GVec3&      backgroundColor,
    bool              hasBackgroundColor,
    curandState*      rng)
{
    const int rrDepth = 3;
    GSampledSpectrum color(0.f);
    GSampledSpectrum throughput(1.f);
    bool wasSpecular = true;

    for (int bounce = 0; bounce < maxDepth; ++bounce) {
        GHitRecord rec;
        if (!gpu_bvh_hit(bvhNodes, prims, tris, spheres,
                         ray, 0.001f, 1e30f, rec)) {
            // Environment / background contribution.
            GSampledSpectrum envSpec(0.f);
            GVec3 dir = ray.direction.normalized();
            if (hasBackgroundColor) {
                envSpec = gpu_rgbToSampledSpectrum(backgroundColor, lambdas,
                                                   GSPEC_RGB_ILLUMINANT);
            } else if (envMap.loaded) {
                GVec3 rgb = gpu_envmap_lookup(envMap, dir);
                envSpec = gpu_rgbToSampledSpectrum(rgb, lambdas,
                                                   GSPEC_RGB_ILLUMINANT);
            } else if (useLuminanceOutput) {
                // Rayleigh sky fallback for outside-visible bands.
                for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) {
                    float scale = rayleighScale(lambdas.lambda[i]);
                    float horizonFade = 0.5f * (dir.y + 1.f);
                    envSpec.v[i] = 0.08f * scale * (0.5f + horizonFade);
                }
            } else {
                float t = 0.5f * (dir.y + 1.f);
                GVec3 bg = (GVec3(1.f) * (1.f - t) + GVec3(0.5f, 0.7f, 1.f) * t) * 0.2f;
                envSpec = gpu_rgbToSampledSpectrum(bg, lambdas, GSPEC_RGB_ILLUMINANT);
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

        ray = GRay(rec.point, bs.wi);
    }

    return color;
}

// ---------------------------------------------------------------------------
// Multiwavelength megakernel
// ---------------------------------------------------------------------------
__global__ void multiwavelengthKernel(
    float* framebuffer, int width, int height,
    int samplesPerPixel, int maxDepth,
    float lambdaMin, float lambdaMax,
    bool  useLuminanceOutput,
    const GBVHNode*  bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const GMaterial*  materials,
    GEnvMap envMap,
    GCameraParams cam,
    GVec3 backgroundColor, bool hasBackgroundColor,
    curandState* rngStates)
{
    int pixelIdx = blockIdx.x * blockDim.x + threadIdx.x;
    int totalPixels = width * height;
    if (pixelIdx >= totalPixels) return;

    int px = pixelIdx % width;
    int py = pixelIdx / width;

    curandState localRng = rngStates[pixelIdx];

    GVec3 colorRGB(0.f);
    for (int s = 0; s < samplesPerPixel; ++s) {
        float u = (px + curand_uniform(&localRng)) / (width  - 1);
        float v = 1.f - (py + curand_uniform(&localRng)) / (height - 1);

        GVec3 rd     = gpu_randomInUnitDisk(&localRng) * cam.lensRadius;
        GVec3 offset = cam.u * rd.x + cam.v * rd.y;
        GVec3 dir    = cam.lowerLeft + cam.horizontal*u + cam.vertical*v
                       - cam.origin - offset;
        GRay ray(cam.origin + offset, dir);

        GSampledWavelengths lambdas =
            gpu_sampleBandWavelengths(&localRng, lambdaMin, lambdaMax);

        GSampledSpectrum rad = tracePathMW(
            ray, maxDepth, lambdas, useLuminanceOutput,
            bvhNodes, prims, tris, spheres, materials,
            envMap, backgroundColor, hasBackgroundColor, &localRng);

        GVec3 sample;
        if (useLuminanceOutput) {
            float L = 0.f;
            for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) L += rad.v[i];
            L = fmaxf(0.f, L / float(G_SPECTRUM_SAMPLES));
            sample = GVec3(L, L, L);
        } else {
            GVec3 xyz = spectrumToXYZ(rad, lambdas);
            sample = xyzToLinearSRGB_dev(xyz);
        }

        // Per-sample firefly clamp (matches CPU path tracer).
        float lum = luminance(sample);
        if (lum > 20.f) sample *= (20.f / lum);

        colorRGB += sample;
    }

    colorRGB /= float(samplesPerPixel);
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
    float lambdaMin, float lambdaMax, bool useLuminanceOutput,
    const GBVHNode*  d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const GMaterial*  d_materials,
    GEnvMap envMap,
    GCameraParams cam,
    GVec3 backgroundColor, bool hasBackgroundColor,
    curandState* d_rngStates)
{
    int totalPixels    = width * height;
    int threadsPerBlock = 256;
    int blocks         = (totalPixels + threadsPerBlock - 1) / threadsPerBlock;

    multiwavelengthKernel<<<blocks, threadsPerBlock>>>(
        d_framebuffer, width, height, samplesPerPixel, maxDepth,
        lambdaMin, lambdaMax, useLuminanceOutput,
        d_bvhNodes, d_prims, d_tris, d_spheres, d_materials,
        envMap, cam, backgroundColor, hasBackgroundColor,
        d_rngStates);

    cudaError_t err = cudaGetLastError();
    if (err != cudaSuccess) {
        fprintf(stderr, "MW kernel launch error: %s\n", cudaGetErrorString(err));
        throw std::runtime_error(cudaGetErrorString(err));
    }
    cudaDeviceSynchronize();
}
