#pragma once
// photon_lights.h — pkg286/pkg287 — host-side setup of the per-light photon
// emitters (photon_emitter.h) for the caustic pre-pass, shared by the CPU
// integrators and the GPU aim builder (gpu_wavefront_snapshot.cu).
//
// Every dedicated lamp with a device mirror (DeviceLightParams) becomes one
// emitter; mesh / legacy hittable emitters are not photon sources (pkg287
// non-goal). The photon budget is split over lights in proportion to the
// luminous flux each sends toward the casters (Mitsuba 3 ptracer selects lights
// ∝ power; here the projection-map share, Jensen 2001 §9.3), estimated with a
// deterministic 16x16 pilot. Any split is unbiased: each light divides by its
// own N_i. Photon λ is importance-sampled ∝ the light's SPD over 380..720 nm
// (pkg221), so the S/p factor collapses to the SPD integral I_S.
//
// Requires raytracer.h first (LightList, astroray::Light, AABB).

#include "astroray/photon_emitter.h"
#include "astroray/photon_spd.h"
#include "astroray/spectrum.h"

#include <algorithm>
#include <cmath>
#include <random>
#include <vector>

namespace astroray {
namespace photon {

// S(λ) of a dedicated light exactly as its sampleLi evaluates it (RGB
// illuminant, else the baked 1 nm profile, 360..830 nm).
inline float photonLightSpd(const DeviceLightParams& p, float lambda) {
    if (p.emissionProfileSamples.empty())
        return RGBIlluminantSpectrum({p.emissionRGB.x, p.emissionRGB.y, p.emissionRGB.z})
            .evalAt(lambda);
    const int i = static_cast<int>(lambda - kDeviceEmissionLambdaMin + 0.5f);
    if (i < 0 || i >= static_cast<int>(p.emissionProfileSamples.size())) return 0.0f;
    return p.emissionProfileSamples[i];
}

// Build the emitters for every dedicated lamp. `casterBounds` is the union
// AABB of the caustic casters (one importance cone per light toward its
// bounding sphere).
template <class LightsT>
inline std::vector<PhotonLight> buildPhotonLights(const LightsT& lights, const AABB& casterBounds,
                                                  int totalPhotons) {
    std::vector<PhotonLight> out;
    const Vec3 c = casterBounds.centroid();
    const float diag = (casterBounds.max - casterBounds.min).length();
    const float crad = diag * 0.55f + 1e-3f;          // distant aperture half-width
    const PeV3 target{c.x, c.y, c.z};
    const float targetRadius = 0.5f * diag * 1.01f + 1e-3f;

    std::vector<double> share;
    const auto& ded = lights.getDedicatedLights();
    for (size_t j = 0; j < ded.size(); ++j) {
        DeviceLightParams p;
        if (!ded[j] || !ded[j]->fillDeviceParams(p)) continue;
        if (p.kind < 0 || p.kind > 3) continue;

        PhotonLight L;
        PhotonEmitter& e = L.emitter;
        e = PhotonEmitter{};
        e.kind = p.kind;
        e.shape = p.areaShape;
        e.lightIndex = static_cast<int>(j);
        e.pos = {p.position.x, p.position.y, p.position.z};
        e.axis = peNorm(PeV3{p.axis.x, p.axis.y, p.axis.z});
        e.u = {p.u.x, p.u.y, p.u.z};
        e.v = {p.v.x, p.v.y, p.v.z};
        e.width = p.width;
        e.height = p.height;
        e.cosInner = p.cosInner;
        e.cosOuter = p.cosOuter;
        e.spread = p.spread;
        e.staticScale = p.staticScale;
        e.target = target;
        e.targetRadius = targetRadius;
        if (p.kind == DeviceLightParams::Distant) {
            // Square aperture upstream of the casters, normal to the beam.
            const Vec3 ax(e.axis.x, e.axis.y, e.axis.z);
            const Vec3 a = (std::fabs(ax.x) < 0.9f) ? Vec3(1, 0, 0) : Vec3(0, 1, 0);
            const Vec3 fu = (a - ax * a.dot(ax)).normalized();
            const Vec3 fv = ax.cross(fu);
            const Vec3 o = c - ax * (crad + 2.0f);
            e.pos = {o.x, o.y, o.z};
            e.u = {fu.x, fu.y, fu.z};
            e.v = {fv.x, fv.y, fv.z};
            e.width = crad;
            e.spread = 0.0f;
        }
        if (!p.iesPacked.empty() &&
            (p.kind == DeviceLightParams::Point || p.kind == DeviceLightParams::Spot)) {
            L.iesTable = p.iesPacked;
            for (int k = 0; k < 9; ++k) e.iesFrame[k] = p.iesFrame[k];
        }

        // λ CDF ∝ S and the luminance weight Σ S ȳ (for the photon split).
        float S[PhotonSpdCdf::K];
        double sum = 0.0, lumS = 0.0;
        for (int k = 0; k < PhotonSpdCdf::K; ++k) {
            const float lam = PhotonSpdCdf::kLmin + static_cast<float>(k);
            S[k] = std::max(0.0f, photonLightSpd(p, lam));
            sum += S[k];
            lumS += S[k] * cieCmf1931_2deg(lam).Y;
        }
        if (!(sum > 0.0) || !std::isfinite(sum)) continue;
        L.spd.integral = static_cast<float>(sum);   // Δλ = 1 nm
        double acc = 0.0;
        for (int k = 0; k < PhotonSpdCdf::K; ++k) {
            acc += S[k];
            L.spd.cdf[k] = static_cast<float>(acc / sum);
        }
        L.spd.cdf[PhotonSpdCdf::K - 1] = 1.0f;
        L.spd.valid = true;

        // Pilot: mean geometric weight toward the casters (16x16 stratified).
        e.ies = L.iesTable.empty() ? nullptr : L.iesTable.data();
        std::mt19937 pg(977u + static_cast<unsigned>(j));
        std::uniform_real_distribution<float> u01(0.0f, 1.0f);
        double wsum = 0.0;
        for (int a = 0; a < 16; ++a)
            for (int b = 0; b < 16; ++b) {
                PeV3 o, d;
                wsum += peSampleLe(e, (a + u01(pg)) / 16.0f, (b + u01(pg)) / 16.0f,
                                   u01(pg), u01(pg), o, d);
            }
        const double pw = lumS * wsum / 256.0;
        if (!(pw > 0.0)) continue;
        share.push_back(pw);
        out.push_back(std::move(L));
    }
    double total = 0.0;
    for (double s : share) total += s;
    for (size_t i = 0; i < out.size(); ++i) {
        // >= 1 photon: a dim light rounded to 0 would silently drop its flux.
        out[i].count = std::max(1, static_cast<int>(std::lround(totalPhotons * share[i] / total)));
        out[i].emitter.ies = out[i].iesTable.empty() ? nullptr : out[i].iesTable.data();
    }
    return out;
}

// CPU emission of one photon from light L: ray (o, d), wavelength λ and the
// scalar spectral-flux weight (I_S · W / N_i); the deposit is CMF(λ) × weight × T.
inline float emitPhoton(const PhotonLight& L, std::mt19937& gen, Vec3& o, Vec3& d, float& lambda) {
    std::uniform_real_distribution<float> u01(0.0f, 1.0f);
    lambda = photonSpdInverseCdf(L.spd.cdf, PhotonSpdCdf::K, PhotonSpdCdf::kLmin, u01(gen));
    const float a0 = u01(gen), a1 = u01(gen), b0 = u01(gen), b1 = u01(gen);
    PeV3 po, pd;
    const float w = peSampleLe(L.emitter, a0, a1, b0, b1, po, pd);
    o = Vec3(po.x, po.y, po.z);
    d = Vec3(pd.x, pd.y, pd.z);
    return w * L.spd.integral / static_cast<float>(L.count);
}

}  // namespace photon
}  // namespace astroray
