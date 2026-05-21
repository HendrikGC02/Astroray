// NOTE: raytracer.h must be included BEFORE astroray/light.h (for Vec3/AABB/EmissionSpectrum).
#include "raytracer.h"
#include "astroray/light.h"
#include "astroray/spectral.h"  // for planck()
#include "astroray/spectrum.h"  // for cieCmf1964_10deg
#include <cmath>

namespace astroray {

// Helper: compute geometric normalize factor (inverse area).
// Returns 1/area if shouldNormalize is true, else 1.0.
// The M_1_PI_F (1/π) factor is applied separately at sampling time.
// Reference: Cycles intern/cycles/scene/light.cpp:127-131
// (PointLight::copy_to_kernel, eval_fac = invarea * M_1_PI_F) (Apache-2.0).
float Light::computeNormalizeFactor(float area, bool shouldNormalize) {
    if (!shouldNormalize) return 1.0f;

    // Geometric normalization: 1/area (NOT including π).
    // For point/spot lights, area=1.0 gives invarea=1.0.
    if (area > 0.0f) {
        return 1.0f / area;
    }
    return 1.0f;
}

} // namespace astroray
