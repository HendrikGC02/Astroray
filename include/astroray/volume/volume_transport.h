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
#include <atomic>
#include <cmath>
#include <cstdio>
#include <limits>
#include <random>
#include <vector>

#include "astroray/spectrum.h"
#include "astroray/volume/grid_medium.h"
#include "astroray/volume/medium_boundary.h"
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
    // pkg296 (#833): closed triangle boundary (owned by the Renderer). null =>
    // the medium is its AABB (pre-pkg296 path, byte-identical); else the AABB
    // is the boundary's bounds and only a pre-filter (see mediumCoverage).
    const MediumBoundary* boundary = nullptr;
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
    std::array<float, 3> colorRGB = {0.8f, 0.8f, 0.8f};       // pkg269: raw sockets for the GPU upload
    std::array<float, 3> absorptionRGB = {1.0f, 1.0f, 1.0f};
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
    m.colorRGB = pv.color;
    m.absorptionRGB = pv.absorptionColor;
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

// pkg296 (#833) — the first coverage interval [t0,t1] of medium m on
// [cursor,tMax] along (o, unit d), t0 >= cursor (t0 == cursor iff m covers the
// cursor). No boundary => exactly intersectAABB (the pre-pkg296 path). With a
// boundary: the closest crossing strictly after the cursor decides — back-facing
// => inside up to it; front-facing => the medium starts there and ends at the
// following crossing (Cycles volume_stack.h volume_stack_enter_exit, Apache-2.0:
// SR_BACKFACING exits, else enters). Research:
// .astroray_plan/docs/pkg296-mesh-volume-boundary-research.md.
inline bool mediumCoverage(const BoundedMedium& m, const Vec3& o, const Vec3& d, float cursor,
                           float tMax, float& t0, float& t1) {
    if (!m.boundary)
        return intersectAABB(o, d, m.aabbMin, m.aabbMax, cursor, tMax, t0, t1);
    constexpr float kFar = std::numeric_limits<float>::max();
    const MediumBoundary::Crossing c = m.boundary->nextCrossing(o, d, cursor, kFar);
    if (!c.hit) return false;
    if (c.backFacing) {
        t0 = cursor;
        t1 = std::min(c.t, tMax);
        return true;
    }
    if (c.t >= tMax) return false;
    t0 = c.t;
    const MediumBoundary::Crossing e = m.boundary->nextCrossing(o, d, c.t, kFar);
    t1 = e.hit ? std::min(e.t, tMax) : tMax;  // no exit: open mesh, inside to tMax
    return true;
}

// pkg296 — does m contain the point P = o + d*t (t on the same ray)? No boundary
// => the AABB point test (#925's pre-pkg296 check); else the AABB pre-filter and
// the next crossing after t is back-facing.
inline bool mediumContains(const BoundedMedium& m, const Vec3& o, const Vec3& d, float t,
                           const Vec3& P) {
    if (P.x < m.aabbMin[0] || P.x > m.aabbMax[0] || P.y < m.aabbMin[1] ||
        P.y > m.aabbMax[1] || P.z < m.aabbMin[2] || P.z > m.aabbMax[2])
        return false;
    if (!m.boundary) return true;
    const MediumBoundary::Crossing c =
        m.boundary->nextCrossing(o, d, t, std::numeric_limits<float>::max());
    return c.hit && c.backFacing;
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
// pkg271 `noScatter` (volume_bounces exhausted — Cycles PATH_RAY_TERMINATE,
// shade_volume.h `attenuation_only`): a scatter collision is an absorption, so
// the flight only attenuates and collects emission.
inline SpectralFlight spectralTrack(const BoundedMedium& m, const Vec3& o, const Vec3& d,
                                    float tMin, float tMax,
                                    const astroray::SampledWavelengths& wl,
                                    astroray::SampledSpectrum& beta,
                                    astroray::SampledSpectrum& r_u, std::mt19937& gen,
                                    bool noScatter = false) {
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
        float pReal = (sigA[0] + sigS[0]) / sigBar;
        float um = u(gen);
        if (um < pReal) {
            // #925: absorption as a weight (Cycles shade_volume.h). A real
            // collision (pdf σ_t[0]/σ̄) scatters with beta *= σ_s/σ_t[0],
            // r_u *= σ_t/σ_t[0]; noScatter keeps the analog termination.
            if (noScatter || sigS.isZero()) {
                beta = astroray::SampledSpectrum(0.0f);
                ff.event = SpectralEvent::Absorbed; ff.t = t;
                return ff;
            }
            const float inv = 1.0f / (sigS[0] + sigA[0]);
            beta *= sigS * inv; r_u *= (sigS + sigA) * inv;
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

// #842 — free flight where n >= 2 bounded media overlap on [tMin,tMax]. The
// coefficients add (Cycles volume stack: shade_volume.h volume_shader_sample sums
// the closures of every volume the point is inside, Apache-2.0). Null-collision
// tracking over a summed majorant with one collision type per component (Novák
// et al. 2018, "Monte Carlo Methods for Volumetric Light Transport Simulation",
// §3-4): σ̄ = Σ σ̄_k; each medium's scattering is its own type (pScatter_k =
// σ_s,k[0]/σ̄; beta, r_u *= σ_s,k/σ_s,k[0], the pbrt-v4 VolPath update), so
// `which` names the medium whose phase function the scatter uses. One uniform per
// collision, as spectralTrack. Research: issue842-sequential-media-research.md.
inline SpectralFlight spectralTrackOverlap(const BoundedMedium* const* act, int n,
                                           const Vec3& o, const Vec3& d, float tMin,
                                           float tMax, const astroray::SampledWavelengths& wl,
                                           astroray::SampledSpectrum& beta,
                                           astroray::SampledSpectrum& r_u, std::mt19937& gen,
                                           bool noScatter, int& which) {
    std::uniform_real_distribution<float> u(0.0f, 1.0f);
    constexpr int kMax = 8;
    astroray::SampledSpectrum sUnit[kMax], aUnit[kMax];
    float sigBar = 0.0f;
    bool emissive = false;
    for (int k = 0; k < n; ++k) {
        principledSpectralCoeffs(act[k]->colorSpec, act[k]->absorptionSpec, wl, sUnit[k], aUnit[k]);
        sigBar += act[k]->spectralMajorant();
        emissive = emissive || act[k]->emission.active();
    }
    SpectralFlight ff;
    float t = tMin;
    astroray::SampledSpectrum sigSk[kMax];
    for (;;) {
        float xi = u(gen);
        t -= std::log(std::max(1e-20f, 1.0f - xi)) / sigBar;
        if (t >= tMax) { ff.event = SpectralEvent::Escaped; return ff; }
        Vec3 p = o + d * t;
        astroray::SampledSpectrum sigS(0.0f), sigA(0.0f), Le(0.0f);
        for (int k = 0; k < n; ++k) {
            float dens = act[k]->densityAt(p);
            sigSk[k] = sUnit[k] * dens;
            sigS += sigSk[k];
            sigA += aUnit[k] * dens;
            if (emissive) Le += act[k]->emissionAt(p, wl);
        }
        if (!Le.isZero())
            ff.emission += beta * Le * (1.0f / (sigBar * heroAverage(r_u, wl)));
        // #925: absorption as a weight. Real collision with medium k has pdf
        // σ_t,k[0]/σ̄; beta *= σ_s,k/σ_t,k[0], r_u *= σ_t,k/σ_t,k[0].
        float um = u(gen);
        if (noScatter) {
            if (um < (sigS[0] + sigA[0]) / sigBar) {
                beta = astroray::SampledSpectrum(0.0f);
                ff.event = SpectralEvent::Absorbed; ff.t = t;
                return ff;
            }
        } else {
            float cum = 0.0f;
            for (int k = 0; k < n; ++k) {
                float dens = act[k]->densityAt(p);
                astroray::SampledSpectrum sigTk = (sUnit[k] + aUnit[k]) * dens;
                if (sigTk[0] <= 0.0f) continue;
                cum += sigTk[0] / sigBar;
                if (um < cum) {
                    if (sigSk[k].isZero()) {
                        beta = astroray::SampledSpectrum(0.0f);
                        ff.event = SpectralEvent::Absorbed; ff.t = t;
                        return ff;
                    }
                    const float inv = 1.0f / sigTk[0];
                    beta *= sigSk[k] * inv; r_u *= sigTk * inv;
                    ff.event = SpectralEvent::Scattered; ff.t = t;
                    which = k;
                    return ff;
                }
            }
        }
        astroray::SampledSpectrum sigN;
        for (int i = 0; i < astroray::kSpectrumSamples; ++i)
            sigN[i] = std::max(sigBar - sigS[i] - sigA[i], 0.0f);
        if (sigN[0] <= 0.0f) {
            beta = astroray::SampledSpectrum(0.0f);
            ff.event = SpectralEvent::Absorbed; ff.t = t;
            return ff;
        }
        astroray::SampledSpectrum ratio = sigN * (1.0f / sigN[0]);
        beta *= ratio; r_u *= ratio;
    }
}

// #842 — free flight through EVERY bounded medium on the segment [tMin,tMax]
// (was: only the nearest-entered one). The segment is swept in order of the
// media's AABB boundaries; each piece is tracked with the media that cover it
// (one => spectralTrack, byte-identical to the single-medium path; several =>
// spectralTrackOverlap). Restarting the exponential at a boundary is exact
// (memoryless). `entered` = some medium overlaps the segment; `mediumOut` = the
// medium index a Scattered event uses. At most 8 media are tracked on one piece
// (the GPU binding's G_WF_MAX_GRID_MEDIA; extras warn once on stderr). The GPU
// binding itself holds <= 8 media (the addon reports the cap), so a GPU piece
// can never exceed it.
inline SpectralFlight spectralTrackSegment(const std::vector<BoundedMedium>& media,
                                           const Vec3& o, const Vec3& d, float tMin,
                                           float tMax, const astroray::SampledWavelengths& wl,
                                           astroray::SampledSpectrum& beta,
                                           astroray::SampledSpectrum& r_u, std::mt19937& gen,
                                           bool noScatter, bool& entered, int& mediumOut) {
    entered = false;
    mediumOut = -1;
    SpectralFlight total;
    float cursor = tMin;
    while (cursor < tMax) {
        const BoundedMedium* act[8];
        int actIdx[8];
        int n = 0;
        float segEnd = tMax;
        bool later = false;
        for (size_t k = 0; k < media.size(); ++k) {
            float t0, t1;
            if (!mediumCoverage(media[k], o, d, cursor, tMax, t0, t1))  // pkg296
                continue;
            if (t0 > cursor) {           // enters further on: bounds this piece
                segEnd = std::min(segEnd, t0);
                later = true;
            } else if (t1 > cursor) {    // covers the cursor
                segEnd = std::min(segEnd, t1);
                if (n < 8) { act[n] = &media[k]; actIdx[n] = (int)k; ++n; }
                else {
                    static std::atomic<bool> warned{false};
                    if (!warned.exchange(true))
                        std::fprintf(stderr, "[astroray volume] more than 8 bounded media "
                                             "overlap on one ray; extra media are skipped\n");
                }
            }
        }
        if (n == 0) {
            if (!later) break;
            cursor = segEnd;
            continue;
        }
        entered = true;
        SpectralFlight ff;
        int which = 0;
        if (n == 1)
            ff = spectralTrack(*act[0], o, d, cursor, segEnd, wl, beta, r_u, gen, noScatter);
        else
            ff = spectralTrackOverlap(act, n, o, d, cursor, segEnd, wl, beta, r_u, gen,
                                      noScatter, which);
        total.emission += ff.emission;
        if (ff.event != SpectralEvent::Escaped) {
            total.event = ff.event;
            total.t = ff.t;
            mediumOut = actIdx[which];
            return total;
        }
        cursor = segEnd;
    }
    total.event = SpectralEvent::Escaped;
    return total;
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
    if (!m.heterogeneous) {  // #925: exact Beer-Lambert (the ratio-tracking mean)
        astroray::SampledSpectrum Tr;
        const float len = std::max(tMax - tMin, 0.0f);
        for (int i = 0; i < astroray::kSpectrumSamples; ++i)
            Tr[i] = std::exp(-m.densityScale * (sUnit[i] + aUnit[i]) * len);
        return Tr;
    }
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

// ---------------------------------------------------------------------------
// #925 — per-segment volume direct light (decoupled from the scatter decision).
// Source: Kulla & Fajardo, "Importance Sampling Techniques for Path Tracing in
// Participating Media", EGSR 2012, DOI:10.1111/j.1467-8659.2012.03145.x.
// Reference impl: Blender Cycles src/kernel/integrator/shade_volume.h
// (volume_integrate_state_init, volume_equiangular_sample,
// volume_direct_scatter_mis), Apache-2.0. Research:
// .astroray_plan/docs/issue925-volume-segment-direct-light-research.md.
// ---------------------------------------------------------------------------

// pkg296 — Tr through one medium with a boundary over [tMin,tMax]: the product
// over its coverage intervals (a non-convex mesh can be entered several times).
// Each interval ends at a crossing the next query excludes (t > cursor), so the
// cursor strictly increases.
inline astroray::SampledSpectrum boundaryTransmittanceSpectral(
        const BoundedMedium& m, const Vec3& o, const Vec3& d, float tMin, float tMax,
        const astroray::SampledWavelengths& wl, std::mt19937& gen) {
    astroray::SampledSpectrum Tr(1.0f);
    float cur = tMin, s0, s1;
    while (cur < tMax && mediumCoverage(m, o, d, cur, tMax, s0, s1)) {
        Tr *= ratioTrackingTransmittanceSpectral(m, o, d, s0, s1, wl, gen);
        if (!(s1 > cur)) break;
        cur = s1;
    }
    return Tr;
}

// Exact per-λ transmittance over [tMin,tMax] through every bounded medium the
// ray crosses (homogeneous: Beer-Lambert; grid: ratio tracking).
inline astroray::SampledSpectrum segmentTransmittanceSpectral(
        const std::vector<BoundedMedium>& media, const Vec3& o, const Vec3& d,
        float tMin, float tMax, const astroray::SampledWavelengths& wl, std::mt19937& gen) {
    astroray::SampledSpectrum Tr(1.0f);
    for (const auto& m : media) {
        if (m.boundary) {  // pkg296: mesh-bounded
            Tr *= boundaryTransmittanceSpectral(m, o, d, tMin, tMax, wl, gen);
            continue;
        }
        float s0, s1;
        if (intersectAABB(o, d, m.aabbMin, m.aabbMax, tMin, tMax, s0, s1))
            Tr *= ratioTrackingTransmittanceSpectral(m, o, d, s0, s1, wl, gen);
    }
    return Tr;
}

// One-sample MIS distance on [a,b] (b may be +inf) for the segment direct
// light: equiangular about `anchor` (a sampled light point) vs a lane mixture of
// truncated exponentials with per-λ rate `rate`, each picked with probability
// 1/2, weighted 2·power_heuristic / pdf (Cycles volume_direct_scatter_mis).
// Without an anchor (distant light) only the exponential runs. w == 0 => none.
struct SegmentDirectSample {
    float t = 0.0f;
    float w = 0.0f;  // MIS weight / pdf
};
inline SegmentDirectSample sampleSegmentDirect(const Vec3& o, const Vec3& d, float a, float b,
                                               bool hasAnchor, const Vec3& anchor,
                                               const astroray::SampledSpectrum& rate,
                                               std::mt19937& gen) {
    std::uniform_real_distribution<float> u(0.0f, 1.0f);
    constexpr int kN = astroray::kSpectrumSamples;
    SegmentDirectSample out;
    const bool finite = std::isfinite(b) && b < 1e18f;
    const float L = finite ? b - a : std::numeric_limits<float>::infinity();
    if (!(L > 0.0f)) return out;
    // Lanes whose truncated exponential is a proper pdf on [a,b].
    int valid[kN];
    int nValid = 0;
    for (int i = 0; i < kN; ++i)
        if (rate[i] > 1e-12f || finite) valid[nValid++] = i;
    auto pdfDist = [&](float t) {
        if (nValid == 0) return 0.0f;
        float s = 0.0f;
        for (int k = 0; k < nValid; ++k) {
            float r = rate[valid[k]];
            if (r <= 1e-12f) { s += 1.0f / L; continue; }
            float norm = finite ? -std::expm1(-r * L) : 1.0f;
            s += r * std::exp(-r * (t - a)) / norm;
        }
        return s / float(nValid);
    };
    // Equiangular (Kulla & Fajardo 2012 Eq. 6-7): t = tc + D tan θ.
    const float tc = (anchor - o).dot(d);
    const float D = std::max((anchor - (o + d * tc)).length(), 1e-4f);
    const float thA = std::atan2(a - tc, D);
    const float thB = finite ? std::atan2(b - tc, D) : 1.5707962f;
    const bool eqOk = hasAnchor && thB - thA > 1e-7f;
    auto pdfEq = [&](float t) {
        if (!eqOk || t < a || t > b) return 0.0f;
        float dt = t - tc;
        return D / ((thB - thA) * (D * D + dt * dt));
    };
    const bool distOk = nValid > 0;
    if (!eqOk && !distOk) return out;
    const bool both = eqOk && distOk;
    const bool pickEq = both ? (u(gen) >= 0.5f) : eqOk;
    float t;
    if (pickEq) {
        float th = thA + u(gen) * (thB - thA);
        t = tc + D * std::tan(th);
    } else {
        int c = valid[std::min(int(u(gen) * nValid), nValid - 1)];
        float r = rate[c], xi = u(gen);
        if (r <= 1e-12f) t = a + xi * L;
        else t = a - std::log1p(-xi * (finite ? -std::expm1(-r * L) : 1.0f)) / r;
    }
    if (!(t >= a && t <= b) || !std::isfinite(t)) return out;
    float pc = pickEq ? pdfEq(t) : pdfDist(t);
    if (!(pc > 0.0f)) return out;
    out.t = t;
    if (both) {
        float po = pickEq ? pdfDist(t) : pdfEq(t);
        out.w = 2.0f * pc / (pc * pc + po * po);  // 2·pc²/(pc²+po²) / pc
    } else {
        out.w = 1.0f / pc;
    }
    return out;
}

}  // namespace volume
}  // namespace astroray
