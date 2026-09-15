// pkg268 — CPU heterogeneous volume transport: delta-tracking free flight +
// ratio-tracking transmittance + equiangular sampling, over a bounded medium.
//
// Clean-room from pbrt-v4 `media.h` `SampleT_maj` / `cpu/integrators.cpp`
// `VolPathIntegrator` (Woodcock 1965; Apache-2.0), Novák/Selle/Jarosz 2014
// (ratio tracking), Kulla & Fajardo 2012 (equiangular). Citations inline.
// Research: .astroray_plan/docs/pkg268-volume-transport-research.md.
//
// SCALAR σ_t primitives (pkg268; still used by the test-facing estimator
// bindings): transmittance is grey; colour lives in the scattering albedo.
// pkg270 adds the CHROMATIC (per-λ) render path: `spectralTrack` (pbrt-v4
// VolPathIntegrator hero-wavelength spectral MIS, Apache-2.0; Wilkie 2014;
// Kutz 2017 as the published chromatic-tracking reference) and
// `ratioTrackingTransmittanceSpectral`, plus emission accumulated at the
// null-collision vertices (Cycles per-unit-length emission semantics). Research:
// .astroray_plan/docs/pkg270-spectral-tracking-volume-emission-research.md.
// Determinism: the engine std::mt19937 is threaded in — no std::random_device.
//
// Assumes Vec3 (raytracer.h) is already defined; include after raytracer.h.

#pragma once

#include <algorithm>
#include <cmath>
#include <random>

#include "astroray/spectrum.h"
#include "astroray/volume/grid_medium.h"
#include "astroray/volume/phase.h"
#include "astroray/volume/principled_volume.h"
#include "astroray/volume/volume_emission.h"

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

    // ---- pkg270: chromatic coefficients + emission (the render path) ----
    float densityScale = 1.0f;                    // Principled "Density" D
    astroray::RGBAlbedoSpectrum colorSpec;        // JH-upsampled Color
    astroray::RGBAlbedoSpectrum absorptionSpec;   // JH-upsampled Absorption Color
    VolumeEmission emission;
    float temperature = 1000.0f;                  // "Temperature" socket
    float emissionFloor = 0.0f;                   // tracking-rate floor for emissive media

    // D · voxel density (homogeneous => D).
    float densityAt(const Vec3& p) const {
        return densityScale * (heterogeneous ? grid->densityWorld(p.x, p.y, p.z) : 1.0f);
    }
    // Exact λ-independent σ_t bound: s(λ)+a(λ) <= 1 (principledSpectralCoeffs).
    float extinctionMajorant() const { return densityScale * maxDensity + 1e-8f; }
    // Tracking rate for the free flight: the extinction bound, raised to the
    // emission floor so a density-free emitter still generates null-collision
    // vertices to accumulate emission at (research note §2).
    float spectralMajorant() const { return std::max(extinctionMajorant(), emissionFloor + 1e-8f); }
    // Emission per unit length at p (Cycles: independent of density). Constant
    // emission in a GRID medium is gated on density(p) > 0, and blackbody
    // without a temperature grid likewise — the documented approximation of
    // Cycles' bounds mesh around non-background voxels (research note §3).
    astroray::SampledSpectrum emissionAt(const Vec3& p,
                                         const astroray::SampledWavelengths& wl) const {
        astroray::SampledSpectrum e(0.0f);
        if (!emission.active()) return e;
        const bool hasTempGrid = heterogeneous && grid->hasTemperature();
        const bool inActive = !heterogeneous || grid->densityWorld(p.x, p.y, p.z) > 0.0f;
        if (emission.hasConstant() && inActive) e += emission.evalConstant(wl);
        if (emission.hasBlackbody()) {
            float T = hasTempGrid ? temperature * grid->temperatureWorld(p.x, p.y, p.z)
                                  : (inActive ? temperature : 0.0f);
            if (T > 0.0f) e += emission.evalBlackbody(T, wl);
        }
        return e;
    }
};

// pkg270 — fill a BoundedMedium's chromatic/emission fields from the Principled
// Volume sockets (shared by addGridMedium / addHomogeneousMedium). aabb must be
// set first (the emission floor is 8 tentative collisions per AABB diagonal).
inline void setupPrincipled(BoundedMedium& m, const PrincipledVolume& pv) {
    m.densityScale = std::max(0.0f, pv.density);
    m.colorSpec = astroray::RGBAlbedoSpectrum(pv.color);
    m.absorptionSpec = astroray::RGBAlbedoSpectrum(pv.absorptionColor);
    m.emission.setup(pv.emissionStrength, pv.emissionColor, pv.blackbodyIntensity,
                     pv.blackbodyTint);
    m.temperature = std::max(0.0f, pv.temperature);
    float dx = m.aabbMax[0] - m.aabbMin[0], dy = m.aabbMax[1] - m.aabbMin[1],
          dz = m.aabbMax[2] - m.aabbMin[2];
    float diag = std::sqrt(dx * dx + dy * dy + dz * dz);
    m.emissionFloor = (m.emission.active() && diag > 0.0f) ? 8.0f / diag : 0.0f;
}

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

// ---------------------------------------------------------------------------
// pkg270 — chromatic (per-λ) transport. Clean-room from pbrt-v4
// cpu/integrators.cpp VolPathIntegrator::Li / SampleLd (Apache-2.0), specialised
// to Astroray's λ-INDEPENDENT majorant σ̄ (so every pbrt `T_maj/T_maj[0]` factor
// is 1 and the loop reduces to ratios of σ). Lane 0 is the hero (a uniformly
// random member of the CDF-stratified quad, pkg206), so the balance heuristic
// over the four hero choices is avg(r_u) (Wilkie 2014 / pbrt-v4 §14.2.2).
// ---------------------------------------------------------------------------

// Balance-heuristic denominator over the hero choices; lane 0 only once the
// quad has been collapsed by dispersion (the other lanes carry pdf 0).
inline float heroAverage(const astroray::SampledSpectrum& r,
                         const astroray::SampledWavelengths& wl) {
    return wl.secondaryTerminated() ? r[0] : r.average();
}

enum class SpectralEvent { Escaped, Absorbed, Scattered };
struct SpectralFlight {
    SpectralEvent event = SpectralEvent::Escaped;
    float t = 0.0f;
    // Emission collected along the flight, already divided by avg(r_u) at each
    // vertex (i.e. an L contribution: add it to the path radiance as-is).
    astroray::SampledSpectrum emission{0.0f};
};

// Free flight over [tMin,tMax] with hero-wavelength spectral MIS. `beta` is
// the pbrt path throughput and `r_u` the rescaled unidirectional path pdf; the
// caller's effective throughput is beta / heroAverage(r_u). Per tentative
// collision (rate σ̄): emission += beta·Le/(σ̄·avg(r_u)); then absorb with
// pAbsorb = σ_a[0]/σ̄ (terminate), scatter with pScatter = σ_s[0]/σ̄
// (beta, r_u *= σ_s/σ_s[0]), else null (beta, r_u *= σ_n/σ_n[0]). Escaping
// applies no factor (delta-track survival IS the transmittance).
inline SpectralFlight spectralTrack(const BoundedMedium& m, const Vec3& o, const Vec3& d,
                                    float tMin, float tMax,
                                    const astroray::SampledWavelengths& wl,
                                    astroray::SampledSpectrum& beta,
                                    astroray::SampledSpectrum& r_u, std::mt19937& gen) {
    std::uniform_real_distribution<float> u(0.0f, 1.0f);
    astroray::SampledSpectrum sUnit, aUnit;
    principledSpectralCoeffs(m.colorSpec, m.absorptionSpec, wl, sUnit, aUnit);
    const float sigBar = m.spectralMajorant();
    const bool emissive = m.emission.active();
    SpectralFlight ff;
    float t = tMin;
    for (;;) {
        float xi = u(gen);
        t -= std::log(std::max(1e-20f, 1.0f - xi)) / sigBar;
        if (t >= tMax) { ff.event = SpectralEvent::Escaped; return ff; }
        Vec3 p = o + d * t;
        float dens = m.densityAt(p);
        astroray::SampledSpectrum sigS = sUnit * dens;
        astroray::SampledSpectrum sigA = aUnit * dens;
        astroray::SampledSpectrum sigN;
        for (int i = 0; i < astroray::kSpectrumSamples; ++i)
            sigN[i] = std::max(sigBar - sigS[i] - sigA[i], 0.0f);
        if (emissive) {
            astroray::SampledSpectrum Le = m.emissionAt(p, wl);
            if (!Le.isZero())
                ff.emission += beta * Le * (1.0f / (sigBar * heroAverage(r_u, wl)));
        }
        float pAbsorb = sigA[0] / sigBar;
        float pScatter = sigS[0] / sigBar;
        float um = u(gen);
        if (um < pAbsorb) {
            beta = astroray::SampledSpectrum(0.0f);
            ff.event = SpectralEvent::Absorbed; ff.t = t;
            return ff;
        } else if (um < pAbsorb + pScatter) {
            astroray::SampledSpectrum ratio = sigS * (1.0f / sigS[0]);
            beta *= ratio; r_u *= ratio;
            ff.event = SpectralEvent::Scattered; ff.t = t;
            return ff;
        } else {
            if (sigN[0] <= 0.0f) {  // pdf 0 for the null branch: pbrt zeroes beta
                beta = astroray::SampledSpectrum(0.0f);
                ff.event = SpectralEvent::Absorbed; ff.t = t;
                return ff;
            }
            astroray::SampledSpectrum ratio = sigN * (1.0f / sigN[0]);
            beta *= ratio; r_u *= ratio;
        }
    }
}

// Per-λ ratio-tracking transmittance over [tMin,tMax] (Novák 2014; pbrt-v4
// SampleLd). With a λ-independent σ̄ the tentative collisions are shared by all
// lanes, so Tr(λ) = Π σ_n(λ)/σ̄ is unbiased per lane with no wavelength MIS.
// Russian roulette on the max lane (survive with p = maxTr, rescale by 1/p).
inline astroray::SampledSpectrum ratioTrackingTransmittanceSpectral(
        const BoundedMedium& m, const Vec3& o, const Vec3& d, float tMin, float tMax,
        const astroray::SampledWavelengths& wl, std::mt19937& gen) {
    std::uniform_real_distribution<float> u(0.0f, 1.0f);
    astroray::SampledSpectrum sUnit, aUnit;
    principledSpectralCoeffs(m.colorSpec, m.absorptionSpec, wl, sUnit, aUnit);
    const float sigBar = m.extinctionMajorant();
    astroray::SampledSpectrum Tr(1.0f);
    float t = tMin;
    for (;;) {
        float xi = u(gen);
        t -= std::log(std::max(1e-20f, 1.0f - xi)) / sigBar;
        if (t >= tMax) break;
        Vec3 p = o + d * t;
        float dens = m.densityAt(p);
        for (int i = 0; i < astroray::kSpectrumSamples; ++i)
            Tr[i] *= std::max(sigBar - dens * (sUnit[i] + aUnit[i]), 0.0f) / sigBar;
        float mx = Tr.maxValue();
        if (mx < 0.05f) {
            if (u(gen) > mx) return astroray::SampledSpectrum(0.0f);
            Tr *= (1.0f / std::max(mx, 1e-20f));
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
