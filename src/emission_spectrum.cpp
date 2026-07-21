#include "astroray/emission_spectrum.h"
#include "astroray/spectral.h"  // for planck()
#include "astroray/spectrum.h"  // for RGBAlbedoSpectrum, RGBUnboundedSpectrum, cieCmf1964_10deg
#include "astroray/spectral_profile.h"
#include "raytracer.h"  // for Vec3
#include <stdexcept>
#include <algorithm>
#include <variant>
#include <cmath>
#include <unordered_map>

namespace astroray {

namespace {

// pkg122 (Defect 3) — photopic-luminance normalization for a Planck SPD.
//
// The pkg89 Q11 resolution (owner-confirmed) requires a `normalize = true`
// blackbody to divide by its integrated photopic luminance so the artist's
// intensity slider is perceptually stable across temperature and comparable to
// an equal-intensity RGB illuminant. Cycles does the same in
// scene/light.cpp::light_normalize_factor (divide emission by its luminance)
// and precomputes the normalized XYZ in kernel/svm/svm_blackbody.h (Apache-2.0).
//
// Returned factor = 1 / ∫ planck(λ,T)·1e9·ȳ(λ) dλ, integrated over the CIE-1964
// 10° ȳ support (360–830 nm, 1 nm) using the SAME cieCmf1964_10deg() that
// SampledSpectrum::toXYZ() uses. This is self-consistent: the evaluated,
// normalized SPD has E[toXYZ().Y] = 1 for any T, independent of planck()'s
// absolute scale and of the render's wavelength-sampling pdf (the Monte-Carlo
// toXYZ estimator is unbiased for ∫Sȳdλ). Chromaticity is preserved (scalar
// divide), so 6500 K stays near-neutral.
//
// thread_local memo keyed on rounded temperature — a light has one temperature,
// so this is O(1) after warmup and avoids a mutex on the render hot path.
float blackbodyLuminanceNorm(double temperature_K) {
    if (!(temperature_K > 0.0)) return 0.0f;
    static thread_local std::unordered_map<int, float> cache;
    int key = static_cast<int>(std::lround(temperature_K));
    auto it = cache.find(key);
    if (it != cache.end()) return it->second;

    double lumIntegral = 0.0;  // ∫ planck·1e9·ȳ dλ  (dλ = 1 nm)
    for (int lambda = 360; lambda <= 830; ++lambda) {
        double bb = planck(static_cast<double>(lambda), temperature_K) * 1e9;
        float ybar = cieCmf1964_10deg(static_cast<float>(lambda)).Y;
        lumIntegral += bb * static_cast<double>(ybar);  // ·1 nm
    }
    float norm = (lumIntegral > 0.0) ? static_cast<float>(1.0 / lumIntegral) : 0.0f;
    cache.emplace(key, norm);
    return norm;
}

}  // namespace

// Copy constructor (handles unique_ptr in Composite).
EmissionSpectrum::EmissionSpectrum(const EmissionSpectrum& other)
    : data_(std::visit([](const auto& mode) -> Variant {
        using T = std::decay_t<decltype(mode)>;
        if constexpr (std::is_same_v<T, Composite>) {
            // Deep copy the unique_ptr via direct Composite construction, then move into Variant.
            Composite newComp{
                std::make_unique<EmissionSpectrum>(*mode.base),
                mode.filter_rgb
            };
            return Variant{std::move(newComp)};
        } else {
            // Blackbody, RGB, MeasuredSPD are trivially copyable.
            return Variant{mode};
        }
    }, other.data_))
{}

// Copy assignment (handles unique_ptr in Composite).
EmissionSpectrum& EmissionSpectrum::operator=(const EmissionSpectrum& other) {
    if (this == &other) return *this;
    std::visit([this](const auto& mode) {
        using T = std::decay_t<decltype(mode)>;
        if constexpr (std::is_same_v<T, Composite>) {
            // Deep copy the unique_ptr.
            data_.emplace<Composite>(Composite{
                std::make_unique<EmissionSpectrum>(*mode.base),
                mode.filter_rgb
            });
        } else {
            // Blackbody, RGB, MeasuredSPD are trivially copyable.
            data_.emplace<T>(mode);
        }
    }, other.data_);
    return *this;
}

// Evaluate the emission spectrum at the given wavelengths.
SampledSpectrum EmissionSpectrum::eval(const SampledWavelengths& lambdas) const {
    return std::visit([&](const auto& mode) -> SampledSpectrum {
        using T = std::decay_t<decltype(mode)>;
        if constexpr (std::is_same_v<T, Blackbody>) {
            return evalBlackbody(mode, lambdas);
        } else if constexpr (std::is_same_v<T, RGB>) {
            return evalRGB(mode, lambdas);
        } else if constexpr (std::is_same_v<T, MeasuredSPD>) {
            return evalMeasuredSPD(mode, lambdas);
        } else if constexpr (std::is_same_v<T, Composite>) {
            return evalComposite(mode, lambdas);
        }
    }, data_);
}

// Helper: create a Composite by multiplying this spectrum by a filter.
EmissionSpectrum EmissionSpectrum::composeWith(const Vec3& filterRGB) const {
    // Aggregate initialization to avoid default-constructing the unique_ptr.
    Composite comp{
        std::make_unique<EmissionSpectrum>(*this),
        filterRGB
    };
    return EmissionSpectrum(std::move(comp));
}

// pkg89-GPU / GAP 1 — reference RGB for the device RGB upsample.
// pkg142: the caller (scene_upload.cu) selects the device spectral mode for
// this RGB; as of pkg142 that is GSPEC_RGB_UNBOUNDED for emission, so device
// gpu_rgbSpectrumAt(color, λ, UNBOUNDED) (scale*JH*gpu_cieYNormFactor())
// reproduces CPU sampleUnboundedEmission(color, ...) exactly (same pkg54c
// mirror pattern; both apply the pkg142 hardware-verifier photometric
// anchor).
void EmissionSpectrum::deviceReference(Vec3& outRGB, bool& exactRGB) const {
    if (const RGB* rgb = std::get_if<RGB>(&data_)) {
        outRGB   = rgb->color;
        exactRGB = true;
        return;
    }
    // Blackbody / MeasuredSPD / Composite: convert the evaluated SPD to a
    // reference linear-sRGB triple (chroma + magnitude approximate). Sampled at
    // the same uniform stratified wavelengths the CPU power() estimator uses.
    SampledWavelengths wl = SampledWavelengths::sampleUniform(0.5f);
    SampledSpectrum spec = eval(wl);
    XYZ xyz = spec.toXYZ(wl);
    outRGB = Vec3(
        3.2404542f * xyz.X - 1.5371385f * xyz.Y - 0.4985314f * xyz.Z,
        -0.9692660f * xyz.X + 1.8760108f * xyz.Y + 0.0415560f * xyz.Z,
        0.0556434f * xyz.X - 0.2040259f * xyz.Y + 1.0572252f * xyz.Z);
    outRGB.x = std::max(0.0f, outRGB.x);
    outRGB.y = std::max(0.0f, outRGB.y);
    outRGB.z = std::max(0.0f, outRGB.z);
    exactRGB = false;
}

// Internal: evaluate Blackbody mode.
SampledSpectrum EmissionSpectrum::evalBlackbody(const Blackbody& bb,
                                                 const SampledWavelengths& wl) const {
    SampledSpectrum result;

    // Check if tint is white (1,1,1) - if so, skip the tint multiplication entirely.
    bool isWhiteTint = (std::abs(bb.tint_rgb.x - 1.0f) < 1e-6f &&
                        std::abs(bb.tint_rgb.y - 1.0f) < 1e-6f &&
                        std::abs(bb.tint_rgb.z - 1.0f) < 1e-6f);

    // pkg122 (Defect 3): photopic-luminance normalization (pkg89 Q11). Applied
    // on BOTH the white-tint and tinted branches — the previous white-tint
    // short-circuit skipped normalization entirely, which is why the bare-Planck
    // case was ~14× over-bright. Chromaticity is preserved (scalar factor).
    float bbNorm = blackbodyLuminanceNorm(static_cast<double>(bb.temperature_K));

    for (int i = 0; i < kSpectrumSamples; ++i) {
        float lambda = wl.lambda(i);
        // Planck blackbody (W/(m²·sr·nm)) — note: spectral.h planck() returns
        // W/(m²·sr·m), so multiply by 1e9 to get per-nm.
        double bbValue = planck(static_cast<double>(lambda), static_cast<double>(bb.temperature_K));
        float bbFloat = static_cast<float>(bbValue * 1e9) * bbNorm;  // normalized to unit luminance

        if (isWhiteTint) {
            // No tint: pure (normalized) blackbody emission.
            result[i] = bbFloat;
        } else {
            // Apply RGB tint as a multiplicative filter via Jakob-Hanika upsample.
            RGBAlbedoSpectrum tintSpectrum({bb.tint_rgb.x, bb.tint_rgb.y, bb.tint_rgb.z});
            float tintAt = tintSpectrum.evalAt(lambda);
            result[i] = bbFloat * tintAt;
        }
    }
    return result;
}

// Internal: evaluate RGB mode.
// pkg142 (Defect 4): RGB emission uses the RGBUnbounded (no-D65) lift to match
// Cycles' RGB-native light scaling -- Astroray's parity target -- rather than
// the pbrt-v4/Mitsuba RGBIlluminant D65 convention. See
// .astroray_plan/packages/pkg142-rgb-emission-convention.md and
// .astroray_plan/docs/defect4-rgb-emission-research.md.
//
// pbrt-v4 (`SpectrumType::Illuminant` -> RGBIlluminantSpectrum,
// src/pbrt/lights.cpp) and Mitsuba 3 (srgb_d65) both imprint a D65 illuminant
// chromaticity on RGB lights. Cycles is RGB-native: light `strength` is stored
// as a linear-RGB float3 and radiance = strength * eval_fac, with no spectral
// upsampling and no D65 (src/scene/light.cpp, src/kernel/light/area.h).
//
// The chromaticity tilt vs. photometric units are TWO SEPARATE things, not
// one (2026-07-2x hardware-verifier correction to the framing below):
// RGBIlluminantSpectrum's `* sampleD65(lambda)` factor carried BOTH the D65
// chromaticity tilt AND an implicit photometric anchor (sampleD65 is
// normalized so unit-white integrates to Y=1). Dropping the whole factor to
// switch to RGBUnboundedSpectrum removed BOTH -- RGBUnboundedSpectrum::sample()
// has no illuminant and no luminance normalization at all, so bare emission
// came out ~116x too bright (this build's 1964 10° CMF-Y table integral),
// not merely mis-tilted. sampleUnboundedEmission() (src/spectrum.cpp)
// restores just the photometric anchor (1/cieYIntegral()) while keeping
// RGBUnbounded's flat (no-D65) chromaticity -- see cieYIntegral()'s doc
// comment there. With the anchor restored, the expected oracle effect is the
// chromaticity tilt alone (previously modeled as 1.07-1.16x; the "+7-16%"
// framing conflated the tilt with the units bug -- see PR history).
//
// RGBUnboundedSpectrum is pbrt-v4's class (src/pbrt/util/spectrum.h,
// Apache-2.0), already in-tree (src/spectrum.cpp) -- this re-points the
// emission call site at it (plus the anchor), no new algorithm (CLAUDE.md SS6).
SampledSpectrum EmissionSpectrum::evalRGB(const RGB& rgb,
                                           const SampledWavelengths& wl) const {
    return sampleUnboundedEmission({rgb.color.x, rgb.color.y, rgb.color.z}, wl);
}

// Internal: evaluate MeasuredSPD mode.
SampledSpectrum EmissionSpectrum::evalMeasuredSPD(const MeasuredSPD& spd,
                                                    const SampledWavelengths& wl) const {
    const SpectralProfileDatabase& db = SpectralProfileDatabase::instance();
    const SpectralProfile* profile = db.get(spd.profile_name);
    if (!profile || !profile->valid()) {
        throw std::runtime_error("EmissionSpectrum: MeasuredSPD profile '" +
                                 spd.profile_name + "' not found in database");
    }

    SampledSpectrum result;
    for (int i = 0; i < kSpectrumSamples; ++i) {
        float lambda = wl.lambda(i);
        // SpectralProfile::emission() returns relative SPD (normalized to [0, 1]).
        // For emission, interpret as relative spectral radiance.
        result[i] = profile->emission(lambda);
    }
    return result;
}

// Internal: evaluate Composite mode.
SampledSpectrum EmissionSpectrum::evalComposite(const Composite& comp,
                                                 const SampledWavelengths& wl) const {
    // Evaluate base emission.
    SampledSpectrum baseEmission = comp.base->eval(wl);

    // Apply RGB filter via Jakob-Hanika upsample.
    RGBAlbedoSpectrum filterSpectrum({comp.filter_rgb.x, comp.filter_rgb.y, comp.filter_rgb.z});
    SampledSpectrum filterSampled = filterSpectrum.sample(wl);

    // Multiply: spectrum(λ) = base(λ) · filter(λ).
    return baseEmission * filterSampled;
}

} // namespace astroray
