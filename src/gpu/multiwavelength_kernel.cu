// multiwavelength_kernel.cu — pkg54 GPU port of multiwavelength_path_tracer.
//
// Megakernel that mirrors the CPU integrator
// (plugins/integrators/multiwavelength_path_tracer.cpp): naive spectral path
// tracing with sampled wavelengths in a configurable [lambdaMin, lambdaMax]
// band, no NEE, emissive-on-hit termination. Output is either:
//   * luminance-grey (mean of the 4 sampled radiances) for non-visible bands,
//   * linear sRGB derived from a Wyman/Sloan/Shirley 2013 CIE-XYZ fit, for
//     bands inside the visible range.
//
// Reference: Wyman, Sloan, Shirley, "Simple Analytic Approximations to the
// CIE XYZ Color Matching Functions", JCGT vol. 2 no. 2, 2013. Public-domain
// formulae; we use the multi-lobe Gaussian fit (Eq. 1-3, Table 1).
//
// Spectral profile dispatch is *not* mirrored on the GPU yet — materials
// without a profile fall back to the same gpu_rgbToSampledSpectrum() path
// already used by path_trace_kernel.cu. That is sufficient for visible-band
// parity; full profile support is tracked as a follow-up (see pkg54 doc).

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
// Wyman/Sloan/Shirley 2013 piecewise-Gaussian fit to CIE 1931 2° CMFs.
// Accurate to ~0.01 RMSE over 360-830 nm; cheap, no table required.
// ---------------------------------------------------------------------------
__device__ inline float wymanGauss(float x, float mu, float s1, float s2) {
    float s = (x < mu) ? s1 : s2;
    float t = (x - mu) / s;
    return expf(-0.5f * t * t);
}

__device__ inline void wymanCmf(float lambda, float& X, float& Y, float& Z) {
    X =  1.056f * wymanGauss(lambda, 599.8f, 37.9f, 31.0f)
       + 0.362f * wymanGauss(lambda, 442.0f, 16.0f, 26.7f)
       - 0.065f * wymanGauss(lambda, 501.1f, 20.4f, 26.2f);
    Y =  0.821f * wymanGauss(lambda, 568.8f, 46.9f, 40.5f)
       + 0.286f * wymanGauss(lambda, 530.9f, 16.3f, 31.1f);
    Z =  1.217f * wymanGauss(lambda, 437.0f, 11.8f, 36.0f)
       + 0.681f * wymanGauss(lambda, 459.0f, 26.0f, 13.8f);
}

// Project a sampled spectrum to CIE XYZ via Monte Carlo CMF integration.
__device__ inline GVec3 spectrumToXYZ(
    const GSampledSpectrum& s, const GSampledWavelengths& wl)
{
    float X = 0.f, Y = 0.f, Z = 0.f;
    for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) {
        float p = wl.pdf[i];
        if (p == 0.f) continue;
        float cx, cy, cz;
        wymanCmf(wl.lambda[i], cx, cy, cz);
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
