#pragma once

#include "spectrum.h"
#include "../raytracer.h"

// Volumetric emission base class for Pillar-4 astrophysical emitters.
// Concrete plugins evaluate local, fluid-frame emissivity and may integrate a
// short optically thin segment for render paths that do not yet expose the
// full pkg67 invariant GR transfer state.
class Emission {
public:
    virtual ~Emission() = default;

    virtual bool contains(const Vec3& position_M) const = 0;

    virtual astroray::SampledSpectrum emissivity(
        const Vec3& position_M,
        const Vec3& photon_direction,
        const astroray::SampledWavelengths& lambdas) const = 0;

    virtual astroray::SampledSpectrum integrateSegment(
        const Vec3& position_M,
        const Vec3& photon_direction,
        const astroray::SampledWavelengths& lambdas,
        double path_length_cm) const {
        return emissivity(position_M, photon_direction, lambdas)
             * static_cast<float>(path_length_cm);
    }

    virtual double dopplerFactor(const Vec3& position_M,
                                 const Vec3& photon_direction) const {
        (void)position_M;
        (void)photon_direction;
        return 1.0;
    }
};

