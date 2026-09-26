#pragma once
// photon_emitter.h — pkg286/pkg287 — physically normalised, per-light photon
// emission for the caustic pre-pass, shared by the CPU
// (spectral_path_tracer / light_tracer_caustic) and the GPU (photon_caustic.cu).
//
// A photon leaving light i carries spectral flux
//     Phi_p(lambda) = S(lambda) * W / N_i,   W = Le_geom * cos / (pdfPos * pdfDir)
// (Jensen 2001 §7.1; pbrt-v3 sppm.cpp photon beta = Le |cos| / (pdfPos pdfDir),
// BSD-2), S the light's emission spectrum and W the geometric weight returned
// by peSampleLe. Directions are importance-sampled in one cone toward the
// caster bounding sphere (Jensen 2001 §9.3 projection map with a single cell);
// the cone's solid angle is folded into W, so only light that could reach a
// caster is traced and the estimate stays unbiased. Radiometry mirrors each
// light's sampleLi (src/lights/*.cpp) through DeviceLightParams::staticScale:
//   distant: irradiance E = staticScale * S over a square aperture of half-width
//            `width` normal to the beam, jittered over the sun's cone;
//   point:   intensity  I = staticScale * S (* IES), cone toward the casters;
//   spot:    point intensity * Cycles smoothstep falloff (SpotLight::angleFalloff);
//   area:    radiance   L = staticScale * S * spread attenuation (#852), uniform
//            position on the shape, cone toward the casters from that point.
// Point/spot radius > 0 emit from the centre (far-field intensity is unchanged).
// Notes: .astroray_plan/docs/pkg286-287-photon-power-research.md.

#include "astroray/area_spread.h"   // areaSpreadAttenuation (host+device)
#include "astroray/ies_eval.h"      // ies::evalFrame (host+device)

#include <math.h>

#if defined(__CUDACC__)
#  define AR_PE_HD __host__ __device__
#else
#  define AR_PE_HD
#endif

namespace astroray {
namespace photon {

struct PeV3 { float x, y, z; };

AR_PE_HD inline PeV3 peAdd(PeV3 a, PeV3 b) { return {a.x + b.x, a.y + b.y, a.z + b.z}; }
AR_PE_HD inline PeV3 peSub(PeV3 a, PeV3 b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
AR_PE_HD inline PeV3 peMul(PeV3 a, float s) { return {a.x * s, a.y * s, a.z * s}; }
AR_PE_HD inline float peDot(PeV3 a, PeV3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
AR_PE_HD inline PeV3 peNorm(PeV3 a) {
    const float l = sqrtf(peDot(a, a));
    return l > 0.0f ? peMul(a, 1.0f / l) : a;
}

// Light kinds match astroray::DeviceLightParams::Kind.
enum PhotonEmitterKind { kPePoint = 0, kPeSpot = 1, kPeDistant = 2, kPeArea = 3 };

// One emitting light. POD: filled host-side from DeviceLightParams (both
// backends), copied by value into the GPU kernel.
struct PhotonEmitter {
    int   kind;
    int   shape;          // area: 0 rectangle, 1 disk (width = radius), 2 ellipse
    int   lightIndex;     // dedicated-light index (RNG stream, #909 split)
    int   pad_;
    PeV3  pos;            // point/spot/area centre; distant: aperture centre
    PeV3  axis;           // spot axis; distant propagation dir; area normal
    PeV3  u, v;           // area axes; distant aperture frame (unit, ⟂ axis)
    float width, height;  // area size; distant: aperture half-width in `width`
    float cosInner, cosOuter;  // spot cone; distant: cos(sun half-angle)
    float spread;         // area spread half-angle (radians)
    float staticScale;    // DeviceLightParams::staticScale
    PeV3  target;         // caster bounding-sphere centre
    float targetRadius;
    const float* ies;     // packed IES table (host or device pointer) or null
    float iesFrame[9];    // light-local X, Y, Z columns (ies::evalFrame)
};

// Direction uniformly inside the cone {d : d.w >= cosMax} around unit w.
AR_PE_HD inline PeV3 peSampleCone(PeV3 w, float cosMax, float u0, float u1) {
    const float c = 1.0f - u0 * (1.0f - cosMax);
    const float s = sqrtf(fmaxf(0.0f, 1.0f - c * c));
    const float phi = 6.28318530717958647692f * u1;
    // Duff et al. 2017 orthonormal basis.
    const float sg = copysignf(1.0f, w.z);
    const float a = -1.0f / (sg + w.z);
    const float b = w.x * w.y * a;
    const PeV3 t1 = {1.0f + sg * w.x * w.x * a, sg * b, -sg * w.x};
    const PeV3 t2 = {b, sg + w.y * w.y * a, -w.y};
    return peNorm(peAdd(peAdd(peMul(t1, s * cosf(phi)), peMul(t2, s * sinf(phi))),
                        peMul(w, c)));
}

// Cone from `from` toward the caster sphere; returns its solid angle (4π when
// `from` is inside the sphere) and the axis/cosMax to sample it.
AR_PE_HD inline float peTargetCone(const PhotonEmitter& e, PeV3 from, PeV3& w, float& cosMax) {
    const PeV3 d = peSub(e.target, from);
    const float dist2 = peDot(d, d);
    const float r2 = e.targetRadius * e.targetRadius;
    if (dist2 <= r2 * 1.0001f) {
        w = {0.0f, 0.0f, 1.0f};
        cosMax = -1.0f;
        return 4.0f * 3.14159265358979323846f;
    }
    w = peMul(d, 1.0f / sqrtf(dist2));
    cosMax = sqrtf(fmaxf(0.0f, 1.0f - r2 / dist2));
    return 6.28318530717958647692f * (1.0f - cosMax);
}

// Sample a photon ray from light e. (uA0, uA1) is the stratified 2D sample
// (distant aperture / area position / point-spot direction); (uB0, uB1) the
// secondary one (distant sun cone / area direction). Returns W (flux per unit
// S(λ) before the 1/N_i divide); 0 = no emission along this ray.
AR_PE_HD inline float peSampleLe(const PhotonEmitter& e, float uA0, float uA1,
                                 float uB0, float uB1, PeV3& o, PeV3& d) {
    if (e.kind == kPeDistant) {
        o = peAdd(e.pos, peAdd(peMul(e.u, (2.0f * uA0 - 1.0f) * e.width),
                               peMul(e.v, (2.0f * uA1 - 1.0f) * e.width)));
        d = (e.cosOuter < 1.0f) ? peSampleCone(e.axis, e.cosOuter, uB0, uB1) : e.axis;
        return e.staticScale * 4.0f * e.width * e.width;   // E · A_aperture
    }
    if (e.kind == kPeArea) {
        float lu, lv;
        if (e.shape == 0) {
            lu = (uA0 - 0.5f) * e.width;
            lv = (uA1 - 0.5f) * e.height;
        } else {
            const float r = sqrtf(uA0);
            const float phi = 6.28318530717958647692f * uA1;
            lu = r * e.width * cosf(phi);
            lv = r * (e.shape == 1 ? e.width : e.height) * sinf(phi);
        }
        const float area = (e.shape == 0) ? e.width * e.height
                         : 3.14159265358979323846f * e.width *
                               (e.shape == 1 ? e.width : e.height);
        o = peAdd(e.pos, peAdd(peMul(e.u, lu), peMul(e.v, lv)));
        PeV3 w; float cosMax;
        const float omega = peTargetCone(e, o, w, cosMax);
        d = peSampleCone(w, cosMax, uB0, uB1);
        const float cosL = peDot(d, e.axis);
        if (cosL <= 0.0f) return 0.0f;
        // L cosθ A Ω: radiance × projected area × cone solid angle (pdfDir = 1/Ω).
        return e.staticScale * areaSpreadAttenuation(cosL, e.spread) * cosL * area * omega;
    }
    // Point / spot: radiant intensity toward d, cone of directions toward the casters.
    o = e.pos;
    PeV3 w; float cosMax;
    const float omega = peTargetCone(e, o, w, cosMax);
    d = peSampleCone(w, cosMax, uA0, uA1);
    float falloff = 1.0f;
    if (e.kind == kPeSpot) {
        // SpotLight::angleFalloff (src/lights/spot_light.cpp): Cycles smoothstep.
        const float c = peDot(d, e.axis);
        if (c <= e.cosOuter) return 0.0f;
        if (c < e.cosInner) {
            const float t = (c - e.cosOuter) / (e.cosInner - e.cosOuter);
            falloff = t * t * (3.0f - 2.0f * t);
        }
    }
    if (e.ies)
        falloff *= ies::evalFrame(e.ies, e.iesFrame, e.iesFrame + 3, e.iesFrame + 6,
                                  d.x, d.y, d.z);
    return e.staticScale * falloff * omega;
}

}  // namespace photon
}  // namespace astroray
