// NOTE: raytracer.h must come BEFORE light headers (Vec3/AABB/EmissionSpectrum dependency).
#include "raytracer.h"
#include "astroray/lights/distant_light.h"
#include "astroray/spectrum.h"
#include "raytracer.h"  // for Vec3, buildOrthonormalBasis
#include <algorithm>
#include <cmath>
#include <random>
#include <limits>

// Reference: Cycles kernel/light/distant.h::distant_light_sample (Apache-2.0).

namespace astroray {

namespace {

// pkg140 fix A: solidAngle = 2*pi*(1 - cos(halfAngle)) via the textbook
// identity 1 - cos(x) = 2*sin^2(x/2) (CLAUDE.md SS6: trivial, no citation
// needed for the identity itself). The naive `1.0f - std::cos(halfAngle)`
// suffers catastrophic cancellation in float32: cos(h) rounds to exactly
// 1.0f for h ~< 3.4e-4 rad, making solidAngle == 0.0f even though the true
// value is tiny-but-nonzero (matches the pkg122 hardware-verifier sweep:
// angular_diameter 0.00017 rad measured pure black, 0.00175 rad measured
// correct). sin(x) has no such cancellation at small x, so this form stays
// accurate all the way down to the point where angularDiameter_ is exactly
// 0.0 (a true delta light), which the callers branch on separately.
inline float distantSolidAngle(float angularDiameter) {
    float quarterAngle = angularDiameter * 0.25f;  // halfAngle / 2
    float s = std::sin(quarterAngle);
    return 4.0f * static_cast<float>(M_PI) * s * s;
}

// pkg140 fix B (power-CDF starvation): a true-delta sun (angularDiameter_ ==
// 0, solidAngle == 0 exactly) must still have nonzero power() or
// LightList::addLight / PowerLightSampler's power-weighted CDF gives it zero
// selection probability (totalPower == 0 degenerates the CDF search to a
// 0/0 selPdf -- see light_sampler.cpp PowerLightSampler::sample). pbrt-v4
// DistantLight::Phi() returns `Pi * sceneRadius^2 * Lemit` (src/pbrt/
// lights.cpp, Apache-2.0), i.e. a disk the size of the scene's bounding
// sphere -- but that needs scene-bounds plumbing this Light interface does
// not have, and threading it through is out of this package's scope (see
// pkg140 spec non-goals). Instead we floor solidAngle at the value for a
// 1.75e-3 rad disk: the smallest angular_diameter the pkg122 hardware
// verifier measured as rendering correctly (~0.99x analytic; pkg140 spec
// sweep). Flooring (rather than branching to a separate constant) keeps
// power() continuous as angle -> 0+: every angle in [0, 1.75e-3] shares this
// same floor, and angles above it fall through to the real identity-computed
// value, so there is no jump anywhere (pkg140 spec gate).
constexpr float kDeltaPowerFloorAngularDiameter = 1.75e-3f;
inline float deltaPowerSolidAngleFloor() {
    return distantSolidAngle(kDeltaPowerFloorAngularDiameter);
}

}  // namespace

DistantLight::DistantLight(const Vec3& axis,
                            float angularDiameter,
                            const EmissionSpectrum& emission,
                            float intensity)
    : axis_(axis.normalized())
    , angularDiameter_(angularDiameter)
    , emission_(emission)
    , intensity_(intensity)
{
    // Distant lights don't use geometric normalization (no area concept).
    // Just use 1.0 (Cycles distant light has no invarea factor).
    normalizeFactor_ = 1.0f;
}

void DistantLight::sampleLi(LiSample& sample,
                            const Vec3& shadingPoint,
                            const Vec3& shadingNormal,
                            const SampledWavelengths& lambdas,
                            std::mt19937& gen) const {
    // Distant light: rays arrive from a fixed direction (axis points FROM light).
    // Sample a direction within the angular disk.
    Vec3 dir = -axis_;  // direction TO light
    if (angularDiameter_ > 0.0f) {
        // Uniform disk sampling within half-angle cone.
        std::uniform_real_distribution<float> dist(0.0f, 1.0f);
        float u1 = dist(gen);
        float u2 = dist(gen);
        float halfAngle = angularDiameter_ / 2.0f;
        float r = std::sqrt(u1) * std::sin(halfAngle);
        float phi = 2.0f * static_cast<float>(M_PI) * u2;

        // Build orthonormal basis around -axis.
        Vec3 w = -axis_;
        Vec3 u = (std::abs(w.x) > 0.1f ? Vec3(0, 1, 0) : Vec3(1, 0, 0)).cross(w).normalized();
        Vec3 v = w.cross(u);

        // Perturb direction within cone.
        dir = (w + u * (r * std::cos(phi)) + v * (r * std::sin(phi))).normalized();
    }

    sample.position = shadingPoint + dir * 1e6f;  // far away (simulates infinity)
    sample.normal = -dir;
    sample.distance = std::numeric_limits<float>::max();

    // pkg122 (Distant): Blender sun "Strength" is IRRADIANCE S (W/m²) delivered
    // to a normal surface; the reflected radiance is f_r·cosθ·S, independent of
    // angular size. The prior code returned emission = eval·intensity with a
    // solid-angle pdf 1/Ω, so the L/pdf divide multiplied by Ω (≈6.6e-5 for the
    // sun) → effectively black. Carry the sun RADIANCE L = S/Ω in emission so
    // the L/pdf divide reconstructs the delivered irradiance S.
    // Reference: Cycles scene/light.cpp sun path (sun.eval_fac = 1/area,
    //   area = π·sin²(θ_half) = disk solid angle) (Apache-2.0).
    // pkg140 fix A: distantSolidAngle() (2*sin^2(h/2) identity) instead of
    // the raw 1-cos(halfAngle) that cancels to exactly 0.0f for tiny angles.
    float solidAngle = distantSolidAngle(angularDiameter_);

    SampledSpectrum emissionSpec = emission_.eval(lambdas);
    if (solidAngle > 0.0f) {
        emissionSpec *= (intensity_ * normalizeFactor_ / solidAngle);  // radiance = S/Ω
        sample.pdf = 1.0f / solidAngle;                                 // solid-angle pdf
        sample.isDelta = false;
    } else {
        // True delta sun (angular diameter exactly 0): a single direction;
        // deliver irradiance directly with a delta pdf (pdf = 1), no area
        // sampling. pkg140 fix B: isDelta flags this for the integrator so
        // the NEE/BSDF MIS combine uses weight 1 instead of a power
        // heuristic against bsdfPdf (a BSDF-sampled ray has probability 0 of
        // ever reproducing this exact direction; mirrors pbrt-v4 delta-light
        // MIS handling, src/pbrt/lights.h, Apache-2.0).
        emissionSpec *= (intensity_ * normalizeFactor_);
        sample.pdf = 1.0f;
        sample.isDelta = true;
    }

    sample.emission_spec = emissionSpec;

    // Convert to RGB.
    XYZ xyz = emissionSpec.toXYZ(lambdas);
    sample.emission_rgb = Vec3(
        3.2404542f * xyz.X - 1.5371385f * xyz.Y - 0.4985314f * xyz.Z,
        -0.9692660f * xyz.X + 1.8760108f * xyz.Y + 0.0415560f * xyz.Z,
        0.0556434f * xyz.X - 0.2040259f * xyz.Y + 1.0572252f * xyz.Z
    );
}

float DistantLight::pdfLi(const Vec3& shadingPoint, const Vec3& direction) const {
    // pkg140 fix A: distantSolidAngle() identity (see sampleLi).
    float solidAngle = distantSolidAngle(angularDiameter_);
    // pkg122: delta sun (Ω=0) → 0 ("not useful for MIS"), matching sampleLi.
    return (solidAngle > 0.0f) ? (1.0f / solidAngle) : 0.0f;
}

bool DistantLight::intersect(const Vec3& /*rayOrigin*/, const Vec3& rayDir,
                             float tMin, float tMax,
                             const SampledWavelengths& lambdas,
                             Intersection& out) const {
    // pkg181: a BSDF-sampled ray "hits" the sun disk when its direction lies
    // within the angular-disk half-angle of the direction TO the light (-axis_).
    // Cycles distant_light: hittable only for a finite angular diameter (a true
    // delta sun, angularDiameter_ == 0, stays NEE-only — a BSDF ray has zero
    // probability of reproducing a single direction). Reference: Cycles
    // kernel/light/light.h distant handling + kernel/light/distant.h (Apache-2.0).
    if (angularDiameter_ <= 0.0f) return false;
    Vec3 D = rayDir.normalized();
    Vec3 toLight = -axis_;                              // axis_ points FROM light
    float cosAngle = D.dot(toLight);
    float cosHalf = std::cos(angularDiameter_ * 0.5f);
    if (cosAngle < cosHalf) return false;              // outside the sun disk

    // The sun is at infinity: place the hit far away but finite so the caller's
    // "closer than the surface" test resolves against real geometry (a floor
    // the ray already hit is nearer, so this loses to it, as it should).
    const float kFar = 1e30f;
    if (kFar <= tMin || kFar > tMax) return false;

    out.t = kFar;
    out.position = D * kFar;                            // direction-only sentinel
    out.normal = -D;
    // Sun radiance L = S/Ω (irradiance divided by the disk solid angle),
    // identical to sampleLi's emission_spec for the finite-angle branch.
    float solidAngle = distantSolidAngle(angularDiameter_);
    SampledSpectrum e = emission_.eval(lambdas);
    e *= (solidAngle > 0.0f ? (intensity_ * normalizeFactor_ / solidAngle) : 0.0f);
    out.emission = e;
    return true;
}

float DistantLight::power() const {
    // Distant light: power is proportional to solid angle × intensity.
    SampledWavelengths lambdas = SampledWavelengths::sampleUniform(0.5f);
    SampledSpectrum emissionSpec = emission_.eval(lambdas);
    XYZ xyz = emissionSpec.toXYZ(lambdas);
    float luminance = xyz.Y;
    // pkg140 fix A: distantSolidAngle() identity (see sampleLi).
    float solidAngle = distantSolidAngle(angularDiameter_);
    // pkg140 fix B: floor so a true-delta sun (solidAngle == 0) still gets a
    // nonzero power-CDF selection weight; see deltaPowerSolidAngleFloor().
    float effectiveSolidAngle = std::max(solidAngle, deltaPowerSolidAngleFloor());
    return luminance * intensity_ * normalizeFactor_ * effectiveSolidAngle;
}

AABB DistantLight::bounds() const {
    // Infinite light: unbounded AABB.
    return AABB(Vec3(-std::numeric_limits<float>::max()),
                Vec3(std::numeric_limits<float>::max()));
}

OrientationCone DistantLight::orientationCone() const {
    float halfAngle = angularDiameter_ / 2.0f;
    return OrientationCone::fromAxisAngle(-axis_, halfAngle);
}

// pkg89-GPU / GAP 1 — device upload description mirroring sampleLi() radiometry.
bool DistantLight::fillDeviceParams(DeviceLightParams& out) const {
    out.kind     = DeviceLightParams::Distant;
    out.axis     = axis_;   // points FROM the light; device uses -axis as dir to light
    out.cosOuter = std::cos(angularDiameter_ * 0.5f);  // cos(halfAngle) for disk-direction sampling
    // pkg140: precomputed solid angle (2*sin^2(h/2) identity), reusing the
    // otherwise-unused-for-Distant `spread` field. The device previously
    // recomputed 2*pi*(1-cosOuter) itself, which cannot recover small-angle
    // precision cosOuter already lost when it was rounded to float32 (same
    // cancellation the CPU fix addresses) -- see gpu_nee.cuh gpu_dedicated_sample.
    out.spread   = distantSolidAngle(angularDiameter_);
    emission_.deviceReference(out.emissionRGB, out.exactIlluminant);
    // pkg218: baked device SPD for non-RGB emission modes (see point_light.cpp).
    if (!out.exactIlluminant) out.emissionProfileSamples = emission_.bakeDeviceProfile();
    // Distant light omits the 1/π factor (matches distant_light.cpp sampleLi).
    out.staticScale = intensity_ * normalizeFactor_;
    return true;
}

} // namespace astroray
