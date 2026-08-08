#pragma once

// Light — first-class light interface (sibling to Hittable, not derived from it).
//
// Motivation (pkg89 research §1.3):
//   - No first-class isotropic point light (Blender POINT faked as 0.1 m sphere).
//   - Spectral emission per-Material forces one Material per light fixture.
//   - No explicit orientation cone for pkg86 Light Tree's Conty 2018 metric.
//   - No place to put per-light controls (cast_shadow, use_mis, normalize).
//
// Design (pkg89 Q1 confirmed: polymorphic vector<unique_ptr<Light>>):
//   - CPU-side virtual interface (PBRT-v4 pattern, Apache-2.0 ref).
//   - Five concrete types: Point, Spot, Distant, Area, Background.
//   - GPU mirror (pkg89-GPU follow-up) will use tagged-union POD (Cycles pattern).
//
// Reference:
//   - PBRT-v4 src/pbrt/lights.h (Apache-2.0): interface shape.
//   - Cycles intern/cycles/scene/light.{h,cpp} (Apache-2.0): per-light flags,
//     normalize factor, emission profiles.
//   - Conty 2018 "Importance Sampling of Many Lights": orientation cone metric.
//
// NOTE: This header requires raytracer.h to be included FIRST (for Vec3/AABB definitions).
// When included from raytracer.h itself (line ~473), this is guaranteed. When included
// standalone (e.g., from src/lights/*.cpp), raytracer.h must be included manually.

#include "spectrum.h"
#include <memory>
#include <random>
#include <cmath>

// Vec3 and AABB are assumed to be already defined (from raytracer.h).
// Forward-declare them here to make the dependency explicit.
struct Vec3;
struct AABB;

namespace astroray {

class EmissionSpectrum;

// --------------------------------------------------------------------------
// DeviceLightParams — neutral (no CUDA types) upload description for a
// dedicated light (pkg89-GPU / GAP 1). Each Light subclass fills this
// mirroring its own sampleLi() radiometry, so scene_upload.cu can convert it
// to a GDedicatedLight and the device NEE samples with pdfs + emission scale
// IDENTICAL to the CPU PowerLightSampler dedicated path. Keeping GPU types out
// of this CPU header avoids dragging <cuda_runtime.h> into the addon TU.
// Reference: mirrors src/lights/{point,spot,distant,area}_light.cpp (which in
// turn cite Cycles kernel/light/{point,spot,distant,area}.h, Apache-2.0).
// --------------------------------------------------------------------------
struct DeviceLightParams {
    enum Kind { Point = 0, Spot = 1, Distant = 2, Area = 3 };
    int   kind      = Point;
    Vec3  position;               // point/spot/area center (world space)
    Vec3  axis;                   // spot axis; distant axis_ (points FROM light); area normal_
    Vec3  u, v;                   // area plane axes (normalized); u × v = normal
    float width     = 0.0f;       // area width (or disk radius in width)
    float height    = 0.0f;       // area height
    int   areaShape = 0;          // 0 rectangle, 1 disk, 2 ellipse
    float radius    = 0.0f;       // point/spot soft-shadow radius (0 = hard/delta)
    float spread    = 0.0f;       // area emission cone half-angle (radians) /
                                   // distant: precomputed solid angle in sr
                                   // (pkg140 distantSolidAngle(), 2*sin^2(h/2)
                                   // identity -- avoids the device recomputing
                                   // 2*pi*(1-cosOuter), which loses the same
                                   // small-angle precision cosOuter already did)
    float cosInner  = 1.0f;       // spot inner-cone cosine (full intensity)
    float cosOuter  = -1.0f;      // spot outer-cone cosine / distant cos(halfAngle)
    Vec3  emissionRGB = Vec3(1.0f); // reference color for the device RGBIlluminant upsample
    bool  exactIlluminant = true; // true when RGB mode (device parity is exact);
                                  // false for blackbody/measured (chroma-approx, energy follow-up)
    float staticScale = 1.0f;     // intensity·normalizeFactor·(1/π) baked per type
                                  // (distant omits the 1/π, matching distant_light.cpp)
};

// --------------------------------------------------------------------------
// OrientationCone — bounding cone for light's emission direction distribution.
// Used by pkg86 Light Tree's Conty 2018 importance metric.
// --------------------------------------------------------------------------
struct OrientationCone {
    Vec3  axis      = Vec3(0, 0, 1);  // normalized axis
    float theta_o   = 0.0f;           // outer half-angle (radians)
    float theta_e   = 0.0f;           // emission half-angle (radians)
                                      // (theta_e ≤ theta_o; tighter bound)

    // Full-sphere cone (isotropic emitter).
    static OrientationCone fullSphere() {
        return OrientationCone{ Vec3(0,0,1), static_cast<float>(M_PI), static_cast<float>(M_PI) };
    }

    // Cone from axis + half-angle (outer == emission).
    static OrientationCone fromAxisAngle(const Vec3& ax, float halfAngle) {
        return OrientationCone{ ax.normalized(), halfAngle, halfAngle };
    }
};

// --------------------------------------------------------------------------
// Light — abstract base for all dedicated light types.
// --------------------------------------------------------------------------
class Light {
public:
    virtual ~Light() = default;

    // Sample a point on the light surface/volume and return emission direction
    // toward the shading point. Returns the sampled position, emission spectrum
    // at the sampled wavelengths, PDF, and distance.
    //
    // Signature (pkg89 Q9): no `time` parameter in Phase A. pkg88 (motion blur)
    // will widen this signature when it lands (or if it lands first, this is
    // born with `time`).
    //
    // NOTE: LiSample is returned via out-parameter (not by-value) to avoid MinGW
    // large-struct corruption (>32 bytes across TU boundaries). See memory note
    // mingw_large_struct_byval.md.
    //
    // Reference: PBRT-v4 `Light::SampleLi` (Apache-2.0, src/pbrt/lights.h:163).
    struct LiSample {
        Vec3              position;       // sampled point on light surface
        Vec3              normal;         // surface normal at sampled point
        SampledSpectrum   emission_spec;  // spectral emission (W/(m²·sr·nm))
        Vec3              emission_rgb;   // RGB emission (for ReSTIR compat)
        float             pdf;            // probability density (1/sr or 1/m²)
        float             distance;       // distance to shading point
        // pkg140: true when this sample came from a delta (zero-measure)
        // direction/position distribution (e.g. DistantLight with
        // angular_diameter == 0). A BSDF-sampled ray has probability 0 of
        // ever reproducing a delta sample, so the NEE/BSDF MIS combine must
        // use weight 1 (not a power-heuristic against bsdfPdf) for these
        // samples. Reference: pbrt-v4 delta-light handling (Light::Type() ==
        // LightType::DeltaDirection skips MIS; src/pbrt/lights.h, Apache-2.0).
        bool              isDelta = false;
    };

    virtual void sampleLi(LiSample& result,
                          const Vec3& shadingPoint,
                          const Vec3& shadingNormal,
                          const SampledWavelengths& lambdas,
                          std::mt19937& gen) const = 0;

    // pkg181: result of a BSDF-sampled ray intersecting this dedicated light.
    // Returned via out-parameter (Intersection carries a SampledSpectrum >32
    // bytes; MinGW large-struct-by-value corruption, see mingw_large_struct_byval.md).
    // `emission` is the PLAIN emitted radiance toward the ray origin — the same
    // radiance sampleLi() returns — and is zero for a back-face / out-of-cone /
    // out-of-bounds hit so the caller can rely solely on the bool.
    struct Intersection {
        float           t = 0.0f;       // ray parameter of the hit
        Vec3            position;       // world-space hit point
        Vec3            normal;         // light surface normal at the hit (outward)
        SampledSpectrum emission;       // radiance emitted back along -rayDir
    };

    // pkg181: intersect a BSDF-sampled ray against this light (Cycles
    // lights_intersect / light_eval_from_intersection parity,
    // intern/cycles/kernel/light/{light,area,distant}.h, Apache-2.0). Returns
    // true and fills `out` when the ray hits the emitting surface within
    // (tMin, tMax]. Default: not hittable (true-delta lights — Point/Spot
    // radius==0, Distant angle==0 — and Background). See pkg181 research note
    // for why Point/Spot with radius>0 also stay NEE-only in Astroray.
    virtual bool intersect(const Vec3& /*rayOrigin*/, const Vec3& /*rayDir*/,
                           float /*tMin*/, float /*tMax*/,
                           const SampledWavelengths& /*lambdas*/,
                           Intersection& /*out*/) const { return false; }

    // PDF for the given direction from the shading point (for MIS).
    virtual float pdfLi(const Vec3& shadingPoint, const Vec3& direction) const = 0;

    // Total emitted power (integrated over all directions and surface).
    // Used for light-selection CDF (importance sampling over lights).
    // Reference: Cycles `Light::emission_estimate` (Apache-2.0).
    virtual float power() const = 0;

    // Bounding box (world space). Infinite lights return unbounded AABB.
    virtual AABB bounds() const = 0;

    // Orientation cone (for pkg86 Light Tree). Isotropic lights return full-sphere.
    // Reference: Conty 2018 §4.1 "Orientation Cone".
    virtual OrientationCone orientationCone() const = 0;

    // pkg89-GPU / GAP 1 — fill the neutral device-upload description. Returns
    // false if this light type has no device mirror yet (scene_upload.cu then
    // skips it, leaving the conservative power-CDF fallback). Default: unsupported.
    virtual bool fillDeviceParams(DeviceLightParams& /*out*/) const { return false; }

    // Per-light flags (Cycles parity, pkg89 research §1.2).
    bool castShadow  = true;   // light casts shadows (occlusion test in NEE)
    bool useMIS      = true;   // include in MIS weight computation
    bool useCaustics = false;  // light participates in caustic paths (SMS, photon map)
    int  maxBounces  = 0;      // light-ray depth limit (0 = unlimited)

    // Normalize flag (Cycles parity, pkg89 Q11 confirmed): if true, divide
    // raw emission by integrated photopic luminance so the artist's "intensity"
    // slider behaves uniformly across blackbody temperatures.
    // Reference: Cycles `light_normalize_factor()` (Apache-2.0, scene/light.cpp).
    bool normalize   = true;

protected:
    Light() = default;

    // Helper: compute geometric normalize factor (inverse area).
    // Returns 1/area if shouldNormalize is true, else 1.0.
    // The M_1_PI_F (1/π) factor is applied separately at sampling time.
    // Reference: Cycles intern/cycles/scene/light.cpp:127-131 (Apache-2.0).
    static float computeNormalizeFactor(float area, bool shouldNormalize);
};

} // namespace astroray
