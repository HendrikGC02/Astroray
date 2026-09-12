// pkg268 — Principled Volume basics: map Blender's ShaderNodeVolumePrincipled /
// Volume Scatter / Volume Absorption sockets onto the scalar-σ_t + spectral-
// albedo medium model (see .astroray_plan/docs/pkg268-volume-transport-research.md
// §"Scope decision"). Socket semantics follow Cycles `svm_node_closure_volume`
// (`kernel/svm/closure.h`, Apache-2.0).
//
// BASICS ONLY (pkg268): density (extinction scale), color (single-scattering
// albedo), absorption color, anisotropy. Emission / blackbody / temperature and
// per-λ chromatic extinction are pkg270.

#pragma once

#include <algorithm>
#include <array>

#include "astroray/spectrum.h"

namespace astroray {
namespace volume {

struct PrincipledVolume {
    // "Density": the extinction coefficient scale (1/world-length). For a grid
    // medium it multiplies the per-voxel density; for a homogeneous medium it IS
    // σ_t. Cycles treats the density grid/socket as the extinction directly.
    float density = 1.0f;

    // "Color": single-scattering albedo (fraction of σ_t that scatters vs.
    // absorbs), spectral via RGB upsampling.
    std::array<float, 3> color = {0.8f, 0.8f, 0.8f};

    // "Absorption Color": tints absorption. BASICS approximation: grey absorption
    // (1 - albedo). A non-grey absorption color is a chromatic-extinction effect
    // deferred to pkg270; the exporter emits a degradation note when it is set
    // (pkg200: never claim honour silently).
    std::array<float, 3> absorptionColor = {1.0f, 1.0f, 1.0f};

    // "Anisotropy": HG asymmetry g in [-1, 1].
    float anisotropy = 0.0f;

    static float clamp01(float v) { return std::clamp(v, 0.0f, 1.0f); }

    // Single-scattering albedo spectrum (clamped to [0,1] for energy safety).
    astroray::RGBAlbedoSpectrum scatteringAlbedo() const {
        return astroray::RGBAlbedoSpectrum(
            {clamp01(color[0]), clamp01(color[1]), clamp01(color[2])});
    }

    // True iff the absorption color departs from grey (=> a pkg270 chromatic-
    // extinction effect this package approximates as grey).
    bool hasChromaticAbsorption(float eps = 1e-3f) const {
        float a = absorptionColor[0], b = absorptionColor[1], c = absorptionColor[2];
        return std::abs(a - b) > eps || std::abs(a - c) > eps;
    }
};

}  // namespace volume
}  // namespace astroray
