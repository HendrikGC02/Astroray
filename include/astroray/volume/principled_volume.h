// pkg268 — Principled Volume basics: map Blender's ShaderNodeVolumePrincipled /
// Volume Scatter / Volume Absorption sockets onto the scalar-σ_t + spectral-
// albedo medium model. Socket semantics follow Cycles
// `svm_node_principled_volume` (`kernel/svm/closure.h`, Apache-2.0):
//
//   σ_s(λ) = color(λ) · density
//   σ_a(λ) = max(1 − color(λ), 0) · max(1 − sqrt(absorption_color(λ)), 0) · density
//   σ_t(λ) = σ_s(λ) + σ_a(λ)
//
// With the DEFAULT white absorption_color, σ_a = 0 (lossless, per-channel albedo
// 1) — a scattering-only medium, NOT the over-absorbing σ_a=(1−color)·density the
// first cut used. See .astroray_plan/docs/pkg268-volume-transport-research.md
// §"Scope decision".
//
// SCALAR-σ_t SCOPE (pkg268): the tracker is grey, so we collapse the per-channel
// σ_t to a single conservative majorant σ_t_scalar = density · max_c(σ_s_c+σ_a_c)
// and carry the colour as the spectral single-scattering albedo
// albedo_c = σ_s_c / max_c(σ_s+σ_a) ∈ [0,1] (no per-channel energy gain). This is
// the documented grey-extinction approximation of Cycles' chromatic σ_t; true
// per-λ extinction is pkg270. Emission / blackbody / temperature are pkg270.

#pragma once

#include <algorithm>
#include <array>
#include <cmath>

#include "astroray/spectrum.h"

namespace astroray {
namespace volume {

struct PrincipledVolume {
    // "Density": the density scale D. σ_s/σ_a/σ_t are proportional to it; for a
    // grid medium the per-voxel density multiplies it further.
    float density = 1.0f;

    // "Color": scattering colour. σ_s = color · density.
    std::array<float, 3> color = {0.8f, 0.8f, 0.8f};

    // "Absorption Color": σ_a gets a max(1 − sqrt(absorption_color), 0) factor.
    // Default white ⇒ σ_a = 0. A non-grey absorption colour is a chromatic-
    // extinction effect approximated grey here (pkg270); the exporter reports it.
    std::array<float, 3> absorptionColor = {1.0f, 1.0f, 1.0f};

    // "Anisotropy": HG asymmetry g in [-1, 1].
    float anisotropy = 0.0f;

    static float clamp01(float v) { return std::clamp(v, 0.0f, 1.0f); }

    // Cycles per-channel scattering coefficient σ_s_c / density (= color_c).
    std::array<float, 3> sigmaSCoeff() const {
        return {std::max(0.0f, color[0]), std::max(0.0f, color[1]), std::max(0.0f, color[2])};
    }
    // Cycles per-channel absorption coefficient σ_a_c / density.
    std::array<float, 3> sigmaACoeff() const {
        std::array<float, 3> a{};
        for (int c = 0; c < 3; ++c) {
            float sc = std::max(1.0f - color[c], 0.0f);
            float ac = std::max(1.0f - std::sqrt(std::max(absorptionColor[c], 0.0f)), 0.0f);
            a[c] = sc * ac;
        }
        return a;
    }
    // max_c(σ_s_c + σ_a_c) / density — the per-density grey extinction bound.
    float maxExtinctionCoeff() const {
        auto s = sigmaSCoeff();
        auto a = sigmaACoeff();
        float m = 0.0f;
        for (int c = 0; c < 3; ++c) m = std::max(m, s[c] + a[c]);
        return m;
    }

    // Grey scalar extinction σ_t at grid-density 1: D · max_c(σ_s+σ_a).
    float extinctionScale() const { return density * maxExtinctionCoeff(); }

    // Spectral single-scattering albedo σ_s_c / max_c(σ_s+σ_a), clamped to [0,1]
    // (energy-safe: albedo ≤ 1 per channel). Density cancels.
    astroray::RGBAlbedoSpectrum scatteringAlbedo() const {
        auto s = sigmaSCoeff();
        float m = maxExtinctionCoeff();
        if (m <= 0.0f) return astroray::RGBAlbedoSpectrum({0.0f, 0.0f, 0.0f});
        return astroray::RGBAlbedoSpectrum(
            {clamp01(s[0] / m), clamp01(s[1] / m), clamp01(s[2] / m)});
    }

    // True iff the absorption color departs from grey (=> a pkg270 chromatic-
    // extinction effect this package approximates as grey).
    bool hasChromaticAbsorption(float eps = 1e-3f) const {
        float a = absorptionColor[0], b = absorptionColor[1], c = absorptionColor[2];
        return std::abs(a - b) > eps || std::abs(a - c) > eps;
    }
    // True iff the scattering colour is chromatic (grey-extinction approximation
    // then loses per-channel extinction detail vs Cycles).
    bool hasChromaticColor(float eps = 1e-3f) const {
        return std::abs(color[0] - color[1]) > eps || std::abs(color[0] - color[2]) > eps;
    }
};

}  // namespace volume
}  // namespace astroray
