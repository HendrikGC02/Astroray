#pragma once

#include "spectrum.h"
#include "../raytracer.h"
#include <algorithm>
#include <cmath>


// pkg283: Lorentz-invariant volumetric transfer (CPU).
// Rybicki & Lightman 1979 section 4.9: I/nu^3, j/nu^2 and nu*alpha are invariant, so
// d(I/nu^3)/dlambda = j/nu^2 - (nu*alpha)(I/nu^3) along k = dx/dlambda
// (Lindquist 1966; Younsi et al. 2012 eqs. 29-31). Pattern: ipole
// @7f7a482c (BSD-3) radiation.c::get_fluid_nu, model_radiation.c::jar_calc_dist,
// ipolarray.c::approximate_solve. No code copied. Notes:
// .astroray_plan/docs/volumetric-invariant-transport-research.md
namespace astroray::invariant_transfer {

// nu_em = -k.u in the static observer's flat frame (signature -+++):
// k = nu_obs (1, n), u = gamma (1, beta*betaDir). n = propagation direction.
inline double fluidFrameFrequency(double nu_obs, const Vec3& n,
                                  const Vec3& betaDir, double beta) {
    beta = std::clamp(beta, 0.0, 1.0 - 1.0e-12);
    const double gamma = 1.0 / std::sqrt((1.0 - beta) * (1.0 + beta));
    // Double-precision cosine: 1 - beta*mu cancels badly in float at high gamma.
    const double bl = std::sqrt(double(betaDir.x) * betaDir.x + double(betaDir.y) * betaDir.y
                                + double(betaDir.z) * betaDir.z);
    const double nl = std::sqrt(double(n.x) * n.x + double(n.y) * n.y + double(n.z) * n.z);
    const double mu = (bl > 0.0 && nl > 0.0)
        ? (double(betaDir.x) * n.x + double(betaDir.y) * n.y + double(betaDir.z) * n.z) / (bl * nl)
        : 0.0;
    return nu_obs * gamma * (1.0 - beta * mu);
}

struct Segment {
    double dI_obs = 0.0;   // observed intensity added by the segment
    double dtau = 0.0;     // invariant optical depth of the segment
};

// One uniform segment of lab path ds_lab. J = j_em/nu_em^2, A = nu_em*alpha_em,
// dlambda = ds_lab/nu_obs, dtau = A*dlambda, I_obs = nu_obs^3 * dI_inv.
// Thin limit: nu_obs^2 j/nu_em^2 ds_lab = g^2 j ds_lab (= g^3 j L_fluid).
inline Segment invariantSegment(double nu_obs, double nu_em, double j_em,
                                double alpha_em, double ds_lab) {
    Segment s;
    if (!(nu_obs > 0.0) || !(nu_em > 0.0) || !(ds_lab > 0.0)) return s;
    const double J = std::max(0.0, j_em) / (nu_em * nu_em);
    const double A = std::max(0.0, alpha_em) * nu_em;
    const double dlam = ds_lab / nu_obs;
    s.dtau = A * dlam;
    // ipole approximate_solve: Taylor branch for small dtau.
    const double dI = s.dtau < 1.0e-3
        ? J * dlam * (1.0 - 0.5 * s.dtau * (1.0 - s.dtau / 3.0))
        : (J / A) * -std::expm1(-s.dtau);
    s.dI_obs = nu_obs * nu_obs * nu_obs * dI;
    if (!std::isfinite(s.dI_obs)) s.dI_obs = 0.0;
    return s;
}

// Front-to-back chord march (camera outward): I += T*dI, T *= exp(-dtau).
// Exact for a piecewise-uniform medium.
inline void accumulateSegment(astroray::SampledSpectrum& I,
                              astroray::SampledSpectrum& T,
                              const astroray::SampledSpectrum& dI,
                              const astroray::SampledSpectrum& dtau) {
    for (int i = 0; i < astroray::kSpectrumSamples; ++i) {
        I[i] += T[i] * dI[i];
        T[i] *= std::exp(-std::max(0.0f, dtau[i]));
    }
}

} // namespace astroray::invariant_transfer

// Volumetric emission base class for Pillar-4 astrophysical emitters.
// Concrete plugins return the OBSERVED per-lab-path emissivity D^2 j(nu_em)
// (Doppler boost already applied, pkg283) -- do not multiply by
// dopplerFactor() again. integrateSegmentTransfer does the invariant transport.
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

    // pkg283: segment emission plus its optical depth, so chord marches can
    // attenuate what lies behind. Default: optically thin.
    virtual astroray::SampledSpectrum integrateSegmentTransfer(
        const Vec3& position_M,
        const Vec3& photon_direction,
        const astroray::SampledWavelengths& lambdas,
        double path_length_cm,
        astroray::SampledSpectrum& tau) const {
        tau = astroray::SampledSpectrum(0.0f);
        return integrateSegment(position_M, photon_direction, lambdas, path_length_cm);
    }

    virtual double dopplerFactor(const Vec3& position_M,
                                 const Vec3& photon_direction) const {
        (void)position_M;
        (void)photon_direction;
        return 1.0;
    }
};

