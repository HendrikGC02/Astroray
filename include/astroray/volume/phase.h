// pkg268 — Volume phase functions (Henyey–Greenstein + isotropic), the single
// home for medium scattering directions. Generalizes the orphaned `isotropic`
// plugin (which scattered via Lambertian, research note §1c) and the world-volume
// HG helpers in raytracer.h.
//
// HG: Henyey & Greenstein 1941; sampling from PBRT-v3 `HenyeyGreenstein::Sample_p`
// (src/core/medium.cpp, BSD). Phase functions here are achromatic (scalar) — the
// colour of a medium lives in its single-scattering albedo (pkg268) and its
// per-λ extinction (pkg270), not the phase function.
//
// This header assumes `Vec3` (raytracer.h) is already defined; include it after
// raytracer.h (as volume_transport.h and the integrator do).

#pragma once

#include <algorithm>
#include <cmath>

namespace astroray {
namespace volume {

inline constexpr float kInv4Pi = 0.07957747154594767f;  // 1/(4π)

// Orthonormal basis around a unit vector (PBRT-v3 CoordinateSystem, BSD).
inline void coordinateSystem(const Vec3& v1, Vec3& v2, Vec3& v3) {
    if (std::abs(v1.x) > std::abs(v1.y))
        v2 = Vec3(-v1.z, 0.0f, v1.x) / std::sqrt(v1.x * v1.x + v1.z * v1.z);
    else
        v2 = Vec3(0.0f, v1.z, -v1.y) / std::sqrt(v1.y * v1.y + v1.z * v1.z);
    v3 = v1.cross(v2);
}

// HG phase value. cosTheta = dot(wo, wi) with wo pointing back along the incoming
// ray. Normalised over the sphere (integrates to 1). g>0 forward-scatters.
inline float phaseHG(float cosTheta, float g) {
    float denom = 1.0f + g * g + 2.0f * g * cosTheta;
    denom = std::max(denom, 1e-6f);
    return kInv4Pi * (1.0f - g * g) / (denom * std::sqrt(denom));
}

// Importance-sample HG. `wo` points back along the incoming ray (= -ray.dir).
// Returns the sampled continuation direction; outPdf is the phase value (HG is
// perfectly importance-sampled, so value/pdf == 1).
inline Vec3 sampleHG(const Vec3& wo, float g, float u1, float u2, float& outPdf) {
    float cosTheta;
    if (std::abs(g) < 1e-3f) {
        cosTheta = 1.0f - 2.0f * u1;
    } else {
        float sqrTerm = (1.0f - g * g) / (1.0f + g - 2.0f * g * u1);
        cosTheta = -(1.0f + g * g - sqrTerm * sqrTerm) / (2.0f * g);
    }
    cosTheta = std::clamp(cosTheta, -1.0f, 1.0f);
    float sinTheta = std::sqrt(std::max(0.0f, 1.0f - cosTheta * cosTheta));
    float phi = 2.0f * float(M_PI) * u2;
    Vec3 v2, v3;
    coordinateSystem(wo, v2, v3);
    Vec3 wi = v2 * (sinTheta * std::cos(phi)) + v3 * (sinTheta * std::sin(phi)) +
              wo * cosTheta;
    outPdf = phaseHG(cosTheta, g);
    return wi.normalized();
}

// Isotropic phase value (p = 1/4π) and uniform-sphere sample.
inline float phaseIsotropic() { return kInv4Pi; }

inline Vec3 sampleIsotropic(float u1, float u2, float& outPdf) {
    float cosTheta = 1.0f - 2.0f * u1;
    float sinTheta = std::sqrt(std::max(0.0f, 1.0f - cosTheta * cosTheta));
    float phi = 2.0f * float(M_PI) * u2;
    outPdf = kInv4Pi;
    return Vec3(sinTheta * std::cos(phi), sinTheta * std::sin(phi), cosTheta);
}

}  // namespace volume
}  // namespace astroray
