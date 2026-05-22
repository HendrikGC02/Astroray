#pragma once

// LightSampler — abstract interface for light selection strategies.
//
// Two implementations:
//   - PowerLightSampler: power-weighted CDF (current LightList behavior, regression baseline).
//   - TreeLightSampler: light tree (Conty 2018 + Cycles, pkg86).
//
// Integrators call LightList::sample, which delegates to a LightSampler. This
// abstraction allows swapping samplers without touching integrator code.

#include <memory>
#include <random>

// Forward-declare types from raytracer.h.
struct Vec3;
struct LightSample;
class LightList;

namespace astroray {

struct SampledWavelengths;
class LightTree;  // Forward-declare to avoid incomplete type in unique_ptr

// ============================================================================
// LightSampler — abstract base
// ============================================================================
class LightSampler {
public:
    virtual ~LightSampler() = default;

    // Sample a light. Returns a LightSample with position, emission, pdf, etc.
    virtual LightSample sample(const Vec3& point, const Vec3& normal,
                               const SampledWavelengths& lambdas,
                               std::mt19937& gen) const = 0;

    // PDF for a given direction from the shading point (for MIS).
    virtual float pdfValue(const Vec3& point, const Vec3& dir) const = 0;

    // Check if the sampler is empty (no lights).
    virtual bool empty() const = 0;
};

// ============================================================================
// PowerLightSampler — power-weighted CDF (legacy behavior)
// ============================================================================
class PowerLightSampler : public LightSampler {
public:
    explicit PowerLightSampler(const LightList* lightList) : lightList_(lightList) {}

    LightSample sample(const Vec3& point, const Vec3& normal,
                       const SampledWavelengths& lambdas,
                       std::mt19937& gen) const override;

    float pdfValue(const Vec3& point, const Vec3& dir) const override;

    bool empty() const override;

private:
    const LightList* lightList_;
};

// ============================================================================
// TreeLightSampler — light tree (Conty 2018 + Cycles)
// ============================================================================
class TreeLightSampler : public LightSampler {
public:
    explicit TreeLightSampler(const LightList* lightList);
    ~TreeLightSampler() override;  // Defined in .cpp where LightTree is complete

    LightSample sample(const Vec3& point, const Vec3& normal,
                       const SampledWavelengths& lambdas,
                       std::mt19937& gen) const override;

    float pdfValue(const Vec3& point, const Vec3& dir) const override;

    bool empty() const override;

private:
    const LightList* lightList_;
    std::unique_ptr<LightTree> tree_;
};

} // namespace astroray
