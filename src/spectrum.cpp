#include "astroray/spectrum.h"

#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <stdexcept>
#include <string>
#include <vector>

namespace astroray {

// Baked, auto-generated 1 nm tables covering 360-830 nm. The relative
// include path mirrors the repository layout; CMake adds the repo root as
// an include directory for the compilation unit.
namespace baked {
#include "../data/spectra/cie_cmf.inc"
#include "../data/spectra/illuminant_d65.inc"

static_assert(kCieCmfCount == kD65Count,
              "CMF and D65 tables must share the same wavelength grid");
}  // namespace baked

// ---------------------------------------------------------------------------
// 1 nm table lookup with linear interpolation.
// ---------------------------------------------------------------------------
namespace {

inline float sampleTable(const float* table, float lambda) {
    if (lambda < baked::kCieCmfLambdaMin || lambda > baked::kCieCmfLambdaMax) {
        return 0.0f;
    }
    float idx = (lambda - baked::kCieCmfLambdaMin) / baked::kCieCmfLambdaStep;
    int   i   = static_cast<int>(idx);
    if (i >= baked::kCieCmfCount - 1) {
        return table[baked::kCieCmfCount - 1];
    }
    float t = idx - static_cast<float>(i);
    return table[i] * (1.0f - t) + table[i + 1] * t;
}

// Integrated Y of D65 against the 1964 10° observer over the table grid.
// Used to normalize `sampleD65` so the resulting D65 XYZ has Y = 1.0.
float computeD65Normalization() {
    double yInt = 0.0;
    for (int i = 0; i + 1 < baked::kD65Count; ++i) {
        double dLam = static_cast<double>(baked::kCieCmfLambdaStep);
        double a = baked::kD65Spd[i]     * baked::kCieCmfY[i];
        double b = baked::kD65Spd[i + 1] * baked::kCieCmfY[i + 1];
        yInt += 0.5 * dLam * (a + b);
    }
    return static_cast<float>(yInt);
}

float d65NormFactor() {
    static const float k = 1.0f / computeD65Normalization();
    return k;
}

// pkg142 hardware-verifier regression (2026-07-2x): ∫ bare kCieCmfY dλ over
// the table grid, i.e. computeD65Normalization() WITHOUT the D65 weighting.
// RGBIlluminantSpectrum's `* sampleD65(lambda)` factor folded TWO things into
// one multiply -- the D65 chromaticity tilt (the ~7-16% pkg142 set out to
// remove) AND a photometric anchor (sampleD65 is normalized so
// ∫sampleD65·ȳdλ = 1, i.e. unit luminance for unit-white input). Switching
// emission to RGBUnboundedSpectrum removed BOTH, not just the tilt: bare
// RGBUnboundedSpectrum::sample() has no illuminant and no luminance
// normalization at all, so its integrated Y came out ~116x too bright (this
// build's 1964 10° CMF-Y table integral -- NOT the 2° observer's ~106.857;
// always derive from the table, never hardcode). cieYIntegral() restores
// just the anchor while keeping RGBUnbounded's flat (no-D65) chromaticity.
// See cieYIntegral()'s callers: emission_spectrum.cpp::evalRGB and
// gpu_materials.h's GSPEC_RGB_UNBOUNDED branch must both apply this factor,
// byte-equivalent.
float computeCieYIntegral() {
    double yInt = 0.0;
    for (int i = 0; i + 1 < baked::kCieCmfCount; ++i) {
        double dLam = static_cast<double>(baked::kCieCmfLambdaStep);
        double a = baked::kCieCmfY[i];
        double b = baked::kCieCmfY[i + 1];
        yInt += 0.5 * dLam * (a + b);
    }
    return static_cast<float>(yInt);
}

}  // namespace

XYZ cieCmf1964_10deg(float lambda) {
    return XYZ{ sampleTable(baked::kCieCmfX, lambda),
                sampleTable(baked::kCieCmfY, lambda),
                sampleTable(baked::kCieCmfZ, lambda) };
}

float sampleD65(float lambda) {
    return sampleTable(baked::kD65Spd, lambda) * d65NormFactor();
}

float cieYIntegral() {
    static const float k = computeCieYIntegral();
    return k;
}

// Every production EMISSION call site (light Le, mesh emitter, env
// background/HDRI) must upsample RGB emission through this helper, not
// RGBUnboundedSpectrum(rgb).sample(wl) directly -- see cieYIntegral() above
// for why the anchor is required. Non-emission RGBUnbounded uses (env
// color-tint spectral multiply in raytracer.h, Phong specular_spec_ in
// plugins/materials/phong.cpp) are dimensionless reflectance-style lifts and
// must NOT receive this anchor; they are unchanged by this function.
SampledSpectrum sampleUnboundedEmission(const std::array<float, 3>& rgb,
                                         const SampledWavelengths& wl) {
    return RGBUnboundedSpectrum(rgb).sample(wl) * (1.0f / cieYIntegral());
}

// ---------------------------------------------------------------------------
// SampledWavelengths
// ---------------------------------------------------------------------------
SampledWavelengths SampledWavelengths::sampleUniform(float u,
                                                    float lambdaMin,
                                                    float lambdaMax) {
    SampledWavelengths swl;
    float span = lambdaMax - lambdaMin;
    float step = span / static_cast<float>(kSpectrumSamples);
    // Hero sample over the full wavelength range; remaining samples are
    // stratified at equal spacing and wrapped into range. This keeps
    // wavelength-dependent paths such as dispersion unbiased when they
    // collapse to the hero wavelength.
    float hero = lambdaMin + u * span;
    for (int i = 0; i < kSpectrumSamples; ++i) {
        float lam = hero + static_cast<float>(i) * step;
        if (lam > lambdaMax) lam -= span;
        swl.lambdas_[i] = lam;
        swl.pdfs_[i]    = 1.0f / span;
    }
    return swl;
}

void SampledWavelengths::terminateSecondary() {
    for (int i = 1; i < kSpectrumSamples; ++i) {
        pdfs_[i] = 0.0f;
    }
}

bool SampledWavelengths::secondaryTerminated() const {
    for (int i = 1; i < kSpectrumSamples; ++i) {
        if (pdfs_[i] != 0.0f) return false;
    }
    return true;
}

// pkg67: apply g = ν_obs / ν_emit to the carried wavelengths.
// λ_obs = λ_emit / g; the PDF, which has units of 1/wavelength, scales by g
// (probability mass is conserved over the shifted band).
void SampledWavelengths::redshift(float g) {
    if (!(g > 0.0f)) return;  // guards NaN and non-positive g (degenerate)
    for (int i = 0; i < kSpectrumSamples; ++i) {
        lambdas_[i] /= g;
        pdfs_[i]    *= g;
    }
}

// ---------------------------------------------------------------------------
// SampledSpectrum arithmetic
// ---------------------------------------------------------------------------
SampledSpectrum SampledSpectrum::operator+(const SampledSpectrum& o) const {
    SampledSpectrum r;
    for (int i = 0; i < kSpectrumSamples; ++i) r.v_[i] = v_[i] + o.v_[i];
    return r;
}

SampledSpectrum SampledSpectrum::operator-(const SampledSpectrum& o) const {
    SampledSpectrum r;
    for (int i = 0; i < kSpectrumSamples; ++i) r.v_[i] = v_[i] - o.v_[i];
    return r;
}

SampledSpectrum SampledSpectrum::operator*(const SampledSpectrum& o) const {
    SampledSpectrum r;
    for (int i = 0; i < kSpectrumSamples; ++i) r.v_[i] = v_[i] * o.v_[i];
    return r;
}

SampledSpectrum SampledSpectrum::operator/(const SampledSpectrum& o) const {
    SampledSpectrum r;
    for (int i = 0; i < kSpectrumSamples; ++i) {
        r.v_[i] = (o.v_[i] != 0.0f) ? v_[i] / o.v_[i] : 0.0f;
    }
    return r;
}

SampledSpectrum SampledSpectrum::operator*(float s) const {
    SampledSpectrum r;
    for (int i = 0; i < kSpectrumSamples; ++i) r.v_[i] = v_[i] * s;
    return r;
}

SampledSpectrum SampledSpectrum::operator/(float s) const {
    SampledSpectrum r;
    float inv = (s != 0.0f) ? 1.0f / s : 0.0f;
    for (int i = 0; i < kSpectrumSamples; ++i) r.v_[i] = v_[i] * inv;
    return r;
}

SampledSpectrum SampledSpectrum::operator-() const {
    SampledSpectrum r;
    for (int i = 0; i < kSpectrumSamples; ++i) r.v_[i] = -v_[i];
    return r;
}

SampledSpectrum& SampledSpectrum::operator+=(const SampledSpectrum& o) {
    for (int i = 0; i < kSpectrumSamples; ++i) v_[i] += o.v_[i];
    return *this;
}
SampledSpectrum& SampledSpectrum::operator-=(const SampledSpectrum& o) {
    for (int i = 0; i < kSpectrumSamples; ++i) v_[i] -= o.v_[i];
    return *this;
}
SampledSpectrum& SampledSpectrum::operator*=(const SampledSpectrum& o) {
    for (int i = 0; i < kSpectrumSamples; ++i) v_[i] *= o.v_[i];
    return *this;
}
SampledSpectrum& SampledSpectrum::operator*=(float s) {
    for (int i = 0; i < kSpectrumSamples; ++i) v_[i] *= s;
    return *this;
}

float SampledSpectrum::sum() const {
    float s = 0.0f;
    for (int i = 0; i < kSpectrumSamples; ++i) s += v_[i];
    return s;
}
float SampledSpectrum::average() const {
    return sum() / static_cast<float>(kSpectrumSamples);
}
float SampledSpectrum::maxValue() const {
    float m = v_[0];
    for (int i = 1; i < kSpectrumSamples; ++i) m = std::max(m, v_[i]);
    return m;
}
float SampledSpectrum::minValue() const {
    float m = v_[0];
    for (int i = 1; i < kSpectrumSamples; ++i) m = std::min(m, v_[i]);
    return m;
}
bool SampledSpectrum::hasNaN() const {
    for (int i = 0; i < kSpectrumSamples; ++i) {
        if (std::isnan(v_[i])) return true;
    }
    return false;
}
bool SampledSpectrum::isZero() const {
    for (int i = 0; i < kSpectrumSamples; ++i) {
        if (v_[i] != 0.0f) return false;
    }
    return true;
}

XYZ SampledSpectrum::toXYZ(const SampledWavelengths& wl) const {
    // Monte Carlo estimator: for each sample, accumulate value*CMF/pdf,
    // then average over the sample count (PBRT v4 convention).
    float X = 0.0f, Y = 0.0f, Z = 0.0f;
    for (int i = 0; i < kSpectrumSamples; ++i) {
        float pdf = wl.pdf(i);
        if (pdf == 0.0f) continue;
        XYZ cmf = cieCmf1964_10deg(wl.lambda(i));
        float w = v_[i] / pdf;
        X += w * cmf.X;
        Y += w * cmf.Y;
        Z += w * cmf.Z;
    }
    float norm = 1.0f / static_cast<float>(kSpectrumSamples);
    return XYZ{ X * norm, Y * norm, Z * norm };
}

// ---------------------------------------------------------------------------
// Jakob-Hanika sigmoid evaluator. The math now lives in include/astroray/
// spectrum.h::jhEvalSpectrumF as a single source of truth shared with the
// CUDA path (gpu_jhEvalSpectrum); this thin wrapper preserves the existing
// std::array call sites unchanged.
// ---------------------------------------------------------------------------
namespace {

inline float evalSigmoidCoeffs(const std::array<float, 3>& c, float lambda) {
    return jhEvalSpectrumF(c[0], c[1], c[2], lambda);
}

}  // namespace

// ---------------------------------------------------------------------------
// Jakob-Hanika LUT file (binary, little-endian):
//     char     magic[4];            // "SPEC"
//     uint32_t res;
//     float    scale[res];
//     float    coeffs[3][res][res][res][3];  // [channel][z][y][x][coeff]
// ---------------------------------------------------------------------------
class JakobHanikaLut {
public:
    static const JakobHanikaLut& get();

    // res_ is the edge length of each 3D table (typically 64 for sRGB).
    int res() const { return res_; }

    // Raw table pointers — used by the GPU uploader to cudaMemcpy the
    // tables verbatim into device global memory.
    const float* scaleData()  const { return scale_.data(); }
    const float* coeffsData() const { return coeffs_.data(); }

    std::array<float, 3> lookup(const std::array<float, 3>& rgb) const;

private:
    JakobHanikaLut() = default;
    void load(const std::string& path);

    int                 res_ = 0;
    std::vector<float>  scale_{};
    std::vector<float>  coeffs_{};

    // Indexing: channel c, z, y, x -> flat offset in coeffs_
    inline const float* entry(int c, int z, int y, int x) const {
        const std::size_t r   = static_cast<std::size_t>(res_);
        const std::size_t idx = ((static_cast<std::size_t>(c) * r + z) * r + y) * r + x;
        return coeffs_.data() + idx * 3;
    }
};

namespace {

std::string resolveLutPath() {
    if (const char* env = std::getenv("ASTRORAY_DATA_DIR")) {
        std::filesystem::path p = std::filesystem::path(env) / "spectra" / "rgb_to_spectrum_srgb.coeff";
        if (std::filesystem::exists(p)) return p.string();
    }
#ifdef ASTRORAY_DATA_DIR
    {
        std::filesystem::path p = std::filesystem::path(ASTRORAY_DATA_DIR) / "spectra" / "rgb_to_spectrum_srgb.coeff";
        if (std::filesystem::exists(p)) return p.string();
    }
#endif
    // Fallback: relative to current working directory (test runs from repo root).
    std::filesystem::path rel = std::filesystem::path("data") / "spectra" / "rgb_to_spectrum_srgb.coeff";
    if (std::filesystem::exists(rel)) return rel.string();

    throw std::runtime_error(
        "Jakob-Hanika LUT not found. Set ASTRORAY_DATA_DIR or run from the "
        "repository root so that data/spectra/rgb_to_spectrum_srgb.coeff is "
        "reachable.");
}

}  // namespace

std::string spectrumLutPath() {
    return resolveLutPath();
}

void JakobHanikaLut::load(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::runtime_error("Cannot open Jakob-Hanika LUT: " + path);

    char magic[4];
    in.read(magic, 4);
    if (!in || std::memcmp(magic, "SPEC", 4) != 0) {
        throw std::runtime_error("Jakob-Hanika LUT: bad magic (expected 'SPEC'): " + path);
    }
    uint32_t res = 0;
    in.read(reinterpret_cast<char*>(&res), sizeof(res));
    if (!in || res == 0 || res > 1024) {
        throw std::runtime_error("Jakob-Hanika LUT: invalid resolution: " + path);
    }
    res_ = static_cast<int>(res);

    scale_.resize(res_);
    in.read(reinterpret_cast<char*>(scale_.data()),
            static_cast<std::streamsize>(scale_.size() * sizeof(float)));
    if (!in) throw std::runtime_error("Jakob-Hanika LUT: truncated scale table: " + path);

    const std::size_t n = static_cast<std::size_t>(3) * res_ * res_ * res_ * 3;
    coeffs_.resize(n);
    in.read(reinterpret_cast<char*>(coeffs_.data()),
            static_cast<std::streamsize>(coeffs_.size() * sizeof(float)));
    if (!in) throw std::runtime_error("Jakob-Hanika LUT: truncated coefficient grid: " + path);
}

const JakobHanikaLut& JakobHanikaLut::get() {
    static JakobHanikaLut instance;
    static std::once_flag flag;
    std::call_once(flag, []() {
        instance.load(resolveLutPath());
    });
    return instance;
}

// Read-only accessors for the GPU uploader; trigger lazy load on first use.
int jakobHanikaLutRes() {
    return JakobHanikaLut::get().res();
}
const float* jakobHanikaLutScale() {
    return JakobHanikaLut::get().scaleData();
}
const float* jakobHanikaLutCoeffs() {
    return JakobHanikaLut::get().coeffsData();
}

std::array<float, 3> JakobHanikaLut::lookup(const std::array<float, 3>& rgb) const {
    // Largest channel picks the sub-table; the remaining two channels,
    // divided by the largest, parametrise (x, y) in [0, 1]. The largest
    // channel itself parametrises z via the (non-uniform) scale table.
    int i = 0;
    if (rgb[1] > rgb[0]) i = 1;
    if (rgb[2] > rgb[i]) i = 2;

    float vMax = rgb[i];
    if (vMax <= 1e-8f) {
        // Effectively black: a huge negative c2 flushes the sigmoid to 0.
        return { 0.0f, 0.0f, -1e20f };
    }
    const int other0 = (i + 1) % 3;
    const int other1 = (i + 2) % 3;

    float x = rgb[other0] / vMax;
    float y = rgb[other1] / vMax;
    float z = vMax;

    const int resM1 = res_ - 1;

    // Locate k such that scale_[k] <= z <= scale_[k+1]. Monotonic, so
    // a simple linear scan is fine (res is small and constant).
    int k = 0;
    while (k + 1 < resM1 && scale_[k + 1] < z) ++k;
    float denomZ = scale_[k + 1] - scale_[k];
    float tz = (denomZ > 0.0f) ? (z - scale_[k]) / denomZ : 0.0f;
    tz = std::clamp(tz, 0.0f, 1.0f);

    float fx = x * static_cast<float>(resM1);
    float fy = y * static_cast<float>(resM1);
    int   x0 = std::clamp(static_cast<int>(fx), 0, resM1 - 1);
    int   y0 = std::clamp(static_cast<int>(fy), 0, resM1 - 1);
    float tx = std::clamp(fx - static_cast<float>(x0), 0.0f, 1.0f);
    float ty = std::clamp(fy - static_cast<float>(y0), 0.0f, 1.0f);

    std::array<float, 3> out{};
    for (int comp = 0; comp < 3; ++comp) {
        auto at = [&](int zi, int yi, int xi) -> float {
            return entry(i, zi, yi, xi)[comp];
        };
        float c000 = at(k,     y0,     x0    );
        float c100 = at(k,     y0,     x0 + 1);
        float c010 = at(k,     y0 + 1, x0    );
        float c110 = at(k,     y0 + 1, x0 + 1);
        float c001 = at(k + 1, y0,     x0    );
        float c101 = at(k + 1, y0,     x0 + 1);
        float c011 = at(k + 1, y0 + 1, x0    );
        float c111 = at(k + 1, y0 + 1, x0 + 1);

        float cLow  = (c000 * (1.0f - tx) + c100 * tx) * (1.0f - ty)
                    + (c010 * (1.0f - tx) + c110 * tx) * ty;
        float cHigh = (c001 * (1.0f - tx) + c101 * tx) * (1.0f - ty)
                    + (c011 * (1.0f - tx) + c111 * tx) * ty;
        out[comp] = cLow * (1.0f - tz) + cHigh * tz;
    }
    return out;
}

// ---------------------------------------------------------------------------
// RGB*Spectrum
// ---------------------------------------------------------------------------
RGBAlbedoSpectrum::RGBAlbedoSpectrum(const std::array<float, 3>& rgb) {
    std::array<float, 3> clamped = {
        std::clamp(rgb[0], 0.0f, 1.0f),
        std::clamp(rgb[1], 0.0f, 1.0f),
        std::clamp(rgb[2], 0.0f, 1.0f),
    };
    c_ = JakobHanikaLut::get().lookup(clamped);
}

SampledSpectrum RGBAlbedoSpectrum::sample(const SampledWavelengths& wl) const {
    SampledSpectrum s;
    for (int i = 0; i < kSpectrumSamples; ++i) {
        s[i] = evalSigmoidCoeffs(c_, wl.lambda(i));
    }
    return s;
}

float RGBAlbedoSpectrum::evalAt(float lambda) const {
    return evalSigmoidCoeffs(c_, lambda);
}

RGBUnboundedSpectrum::RGBUnboundedSpectrum(const std::array<float, 3>& rgb) {
    float m = std::max({ rgb[0], rgb[1], rgb[2] });
    if (m <= 0.0f) {
        scale_ = 0.0f;
        rsp_ = RGBAlbedoSpectrum(std::array<float, 3>{ 0.0f, 0.0f, 0.0f });
        return;
    }
    scale_ = 2.0f * m;
    std::array<float, 3> normalized = {
        rgb[0] / scale_,
        rgb[1] / scale_,
        rgb[2] / scale_,
    };
    rsp_ = RGBAlbedoSpectrum(normalized);
}

SampledSpectrum RGBUnboundedSpectrum::sample(const SampledWavelengths& wl) const {
    return rsp_.sample(wl) * scale_;
}

float RGBUnboundedSpectrum::evalAt(float lambda) const {
    return rsp_.evalAt(lambda) * scale_;
}

RGBIlluminantSpectrum::RGBIlluminantSpectrum(const std::array<float, 3>& rgb) {
    float m = std::max({ rgb[0], rgb[1], rgb[2] });
    if (m <= 0.0f) {
        scale_ = 0.0f;
        rsp_ = RGBAlbedoSpectrum(std::array<float, 3>{ 0.0f, 0.0f, 0.0f });
        return;
    }
    scale_ = 2.0f * m;
    std::array<float, 3> normalized = {
        rgb[0] / scale_,
        rgb[1] / scale_,
        rgb[2] / scale_,
    };
    rsp_ = RGBAlbedoSpectrum(normalized);
}

SampledSpectrum RGBIlluminantSpectrum::sample(const SampledWavelengths& wl) const {
    SampledSpectrum s;
    for (int i = 0; i < kSpectrumSamples; ++i) {
        s[i] = scale_ * evalSigmoidCoeffs(rsp_.coeffs(), wl.lambda(i))
             * sampleD65(wl.lambda(i));
    }
    return s;
}

float RGBIlluminantSpectrum::evalAt(float lambda) const {
    return scale_ * rsp_.evalAt(lambda) * sampleD65(lambda);
}

}  // namespace astroray
