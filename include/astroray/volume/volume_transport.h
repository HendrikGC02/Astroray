// pkg268 — CPU heterogeneous volume transport: delta-tracking free flight +
// ratio-tracking transmittance + equiangular sampling, over a bounded medium.
//
// Clean-room from pbrt-v4 `media.h` `SampleT_maj` / `cpu/integrators.cpp`
// `VolPathIntegrator` (Woodcock 1965; Apache-2.0), Novák/Selle/Jarosz 2014
// (ratio tracking), Kulla & Fajardo 2012 (equiangular). Citations inline.
// Research: .astroray_plan/docs/pkg268-volume-transport-research.md.
//
// SCALAR σ_t (pkg268 scope): transmittance is grey; colour lives in the
// scattering albedo. Per-λ chromatic extinction is pkg270. Determinism: the
// engine std::mt19937 is threaded in — no std::random_device.
//
// Assumes Vec3 (raytracer.h) is already defined; include after raytracer.h.

#pragma once

#include <algorithm>
#include <cmath>
#include <random>

#include "astroray/spectrum.h"
#include "astroray/volume/grid_medium.h"
#include "astroray/volume/phase.h"

namespace astroray {
namespace volume {

// A bounded participating medium registered in the spectral path.
struct BoundedMedium {
    bool heterogeneous = false;
    const GridMedium* grid = nullptr;  // non-null iff heterogeneous
    float aabbMin[3] = {0, 0, 0};
    float aabbMax[3] = {0, 0, 0};
    float extinction = 1.0f;  // σ_t scale, 1/world-length
    float maxDensity = 1.0f;  // density majorant (homogeneous => 1)
    float g = 0.0f;           // HG anisotropy
    astroray::RGBAlbedoSpectrum albedo;  // single-scattering albedo (colour)

    // σ_t at a WORLD point (scalar). For a grid, nearest-voxel density * scale;
    // 0 outside the active voxels. Homogeneous => extinction inside the AABB.
    float sigmaT(const Vec3& p) const {
        float d = heterogeneous ? grid->densityWorld(p.x, p.y, p.z) : 1.0f;
        return extinction * d;
    }
    // Global majorant σ̄ >= sup σ_t (pkg268 uses one global bound; the pkg267
    // DDA majorant grid is available for a tighter per-segment bound — a
    // variance/perf refinement for pkg269).
    float majorant() const { return extinction * maxDensity + 1e-8f; }
};

// Ray (o, unit d) vs world AABB. Returns the clipped overlap [t0,t1] within
// [tMin,tMax]; false if no overlap.
inline bool intersectAABB(const Vec3& o, const Vec3& d, const float mn[3],
                          const float mx[3], float tMin, float tMax,
                          float& t0, float& t1) {
    t0 = tMin;
    t1 = tMax;
    for (int a = 0; a < 3; ++a) {
        float oa = (&o.x)[a], da = (&d.x)[a];
        if (std::abs(da) < 1e-12f) {
            if (oa < mn[a] || oa > mx[a]) return false;
        } else {
            float inv = 1.0f / da;
            float tn = (mn[a] - oa) * inv;
            float tf = (mx[a] - oa) * inv;
            if (tn > tf) std::swap(tn, tf);
            t0 = std::max(t0, tn);
            t1 = std::min(t1, tf);
            if (t0 > t1) return false;
        }
    }
    return true;
}

// Delta/Woodcock tracking free flight over [tMin,tMax] (world distances, unit d).
// Returns whether a real collision occurred and its distance. Null collisions
// are consumed internally; reaching the far end with no real collision happens
// with exactly the transmittance probability (unbiased — no explicit Tr multiply
// on pass-through).
struct FreeFlight {
    bool scattered = false;
    float t = 0.0f;
};
inline FreeFlight deltaTrack(const BoundedMedium& m, const Vec3& o, const Vec3& d,
                             float tMin, float tMax, std::mt19937& gen) {
    std::uniform_real_distribution<float> u(0.0f, 1.0f);
    float sigBar = m.majorant();
    float t = tMin;
    FreeFlight ff;
    for (;;) {
        float xi = u(gen);
        t -= std::log(std::max(1e-20f, 1.0f - xi)) / sigBar;
        if (t >= tMax) {
            ff.scattered = false;
            return ff;
        }
        Vec3 p = o + d * t;
        float sig = m.sigmaT(p);
        if (u(gen) < sig / sigBar) {  // real collision
            ff.scattered = true;
            ff.t = t;
            return ff;
        }
        // else: null collision, continue
    }
}

// Ratio-tracking transmittance over [tMin,tMax] (Novák 2014). Scalar (grey σ_t).
// Unbiased estimator of exp(-∫σ_t ds); required because σ_t varies spatially.
inline float ratioTrackingTransmittance(const BoundedMedium& m, const Vec3& o,
                                        const Vec3& d, float tMin, float tMax,
                                        std::mt19937& gen) {
    std::uniform_real_distribution<float> u(0.0f, 1.0f);
    float sigBar = m.majorant();
    float Tr = 1.0f;
    float t = tMin;
    for (;;) {
        float xi = u(gen);
        t -= std::log(std::max(1e-20f, 1.0f - xi)) / sigBar;
        if (t >= tMax) break;
        Vec3 p = o + d * t;
        Tr *= (1.0f - m.sigmaT(p) / sigBar);
        // Russian-roulette the tail so thin media terminate quickly.
        if (Tr < 0.05f) {
            if (u(gen) > Tr) { Tr = 0.0f; break; }
            Tr = 1.0f;  // survived: reset weight (RR keeps it unbiased)
        }
    }
    return Tr;
}

// Equiangular distance sample toward a light at worldLightPos along ray (o,d)
// over [tMin,tMax] (Kulla & Fajardo 2012). Returns the sampled distance and its
// pdf; used MIS-combined with delta-track distance sampling for single-scatter
// NEE (spot-in-fog / god-rays).
struct EquiangularSample {
    float t = 0.0f;
    float pdf = 0.0f;
};
inline EquiangularSample equiangularSample(const Vec3& o, const Vec3& d,
                                           const Vec3& lightPos, float tMin,
                                           float tMax, float u) {
    EquiangularSample s;
    float tClosest = (lightPos - o).dot(d);
    Vec3 closest = o + d * tClosest;
    float D = (lightPos - closest).length();
    D = std::max(D, 1e-4f);
    float thetaA = std::atan2(tMin - tClosest, D);
    float thetaB = std::atan2(tMax - tClosest, D);
    float theta = (1.0f - u) * thetaA + u * thetaB;
    s.t = tClosest + D * std::tan(theta);
    float dt = s.t - tClosest;
    float denom = (thetaB - thetaA) * (D * D + dt * dt);
    s.pdf = (std::abs(denom) > 1e-20f) ? D / denom : 0.0f;
    return s;
}

// Equiangular pdf at an arbitrary distance t (for MIS weighting of the
// delta-track strategy against the equiangular strategy).
inline float equiangularPdf(const Vec3& o, const Vec3& d, const Vec3& lightPos,
                            float tMin, float tMax, float t) {
    float tClosest = (lightPos - o).dot(d);
    Vec3 closest = o + d * tClosest;
    float D = std::max((lightPos - closest).length(), 1e-4f);
    float thetaA = std::atan2(tMin - tClosest, D);
    float thetaB = std::atan2(tMax - tClosest, D);
    float dt = t - tClosest;
    float denom = (thetaB - thetaA) * (D * D + dt * dt);
    return (std::abs(denom) > 1e-20f) ? D / denom : 0.0f;
}

}  // namespace volume
}  // namespace astroray
