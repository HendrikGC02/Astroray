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
class Hittable;

namespace astroray {

struct SampledWavelengths;
class Light;
class LightTree;  // Forward-declare to avoid incomplete type in unique_ptr

// ============================================================================
// LightSampler — abstract base
// ============================================================================
class LightSampler {
public:
    virtual ~LightSampler() = default;

    // Sample a light. Populates `out` with position, emission, pdf, etc.
    // Passing by reference avoids MinGW large-struct-by-value corruption (memory/mingw_large_struct_byval.md).
    virtual void sample(LightSample& out, const Vec3& point, const Vec3& normal,
                        const SampledWavelengths& lambdas,
                        std::mt19937& gen) const = 0;

    // PDF for a given direction from the shading point (for MIS). `normal` is
    // the shading normal passed to sample() at that point (zero for a volume
    // vertex); the tree's selection pdf depends on it (#851).
    // #912: on a BSDF/phase hit of an emitter, pass that emitter (hitEmitter
    // for a Hittable, hitLamp for a dedicated lamp): only its pdf is the
    // reverse NEE pdf (Cycles light_sample_mis_weight_forward_surface/_lamp).
    // Both null = sum over every light the direction reaches.
    virtual float pdfValue(const Vec3& point, const Vec3& dir, const Vec3& normal,
                           const Hittable* hitEmitter = nullptr,
                           const Light* hitLamp = nullptr) const = 0;

    // #925: re-sample the light a previous sample picked (LightSample::pickIndex)
    // from `point`, keeping its selection pdf. Default: unsupported.
    virtual bool resample(LightSample& /*out*/, const LightSample& /*picked*/,
                          const Vec3& /*point*/, const Vec3& /*normal*/,
                          const SampledWavelengths& /*lambdas*/,
                          std::mt19937& /*gen*/) const { return false; }

    // #961: pick a light for a medium segment (origin o, unit d, length t;
    // t >= 1e18 = open), Cycles light_sample_from_volume_segment
    // (kernel/light/sample.h, Apache-2.0). Fills picked.pickIndex (unified:
    // hittables first, then dedicated) and picked.pickPdf only; resample()
    // then draws the SAME light at a point. False = no light.
    virtual bool pickSegment(LightSample& picked, const Vec3& o, const Vec3& d, float t,
                             std::mt19937& gen) const = 0;

    // #961: pdfValue with the selection pdf of the segment pick instead of the
    // point pick (Cycles light_tree_pdf from mis_origin_n / previous_dt after a
    // volume scatter); the direction pdf is still taken at `point`.
    virtual float pdfValueSegment(const Vec3& o, const Vec3& d, float t, const Vec3& point,
                                  const Vec3& dir, const Hittable* hitEmitter,
                                  const Light* hitLamp) const = 0;

    // Check if the sampler is empty (no lights).
    virtual bool empty() const = 0;

    // pkg86-B: the underlying light tree, when this sampler has one.
    // Non-tree samplers return nullptr; used by the GPU scene upload.
    virtual const LightTree* tree() const { return nullptr; }
};

// ============================================================================
// PowerLightSampler — power-weighted CDF (legacy behavior)
// ============================================================================
class PowerLightSampler : public LightSampler {
public:
    explicit PowerLightSampler(const LightList* lightList) : lightList_(lightList) {}

    void sample(LightSample& out, const Vec3& point, const Vec3& normal,
                const SampledWavelengths& lambdas,
                std::mt19937& gen) const override;

    float pdfValue(const Vec3& point, const Vec3& dir, const Vec3& normal,
                   const Hittable* hitEmitter, const Light* hitLamp) const override;

    bool resample(LightSample& out, const LightSample& picked, const Vec3& point,
                  const Vec3& normal, const SampledWavelengths& lambdas,
                  std::mt19937& gen) const override;

    bool pickSegment(LightSample& picked, const Vec3& o, const Vec3& d, float t,
                     std::mt19937& gen) const override;

    float pdfValueSegment(const Vec3& o, const Vec3& d, float t, const Vec3& point,
                          const Vec3& dir, const Hittable* hitEmitter,
                          const Light* hitLamp) const override;

    bool empty() const override;

private:
    // Power-CDF pick: unified index and its selection pdf; false = no lights.
    bool pickIndex(std::mt19937& gen, size_t& idx, float& selPdf) const;
    // Sample light `idx` (unified index) chosen with probability selPdf.
    void sampleIndexed(LightSample& out, size_t idx, float selPdf, const Vec3& point,
                       const Vec3& normal, const SampledWavelengths& lambdas,
                       std::mt19937& gen) const;
    const LightList* lightList_;
};

// ============================================================================
// TreeLightSampler — light tree (Conty 2018 + Cycles)
// ============================================================================
class TreeLightSampler : public LightSampler {
public:
    explicit TreeLightSampler(const LightList* lightList);
    ~TreeLightSampler() override;  // Defined in .cpp where LightTree is complete

    void sample(LightSample& out, const Vec3& point, const Vec3& normal,
                const SampledWavelengths& lambdas,
                std::mt19937& gen) const override;

    float pdfValue(const Vec3& point, const Vec3& dir, const Vec3& normal,
                   const Hittable* hitEmitter, const Light* hitLamp) const override;

    bool resample(LightSample& out, const LightSample& picked, const Vec3& point,
                  const Vec3& normal, const SampledWavelengths& lambdas,
                  std::mt19937& gen) const override;

    bool pickSegment(LightSample& picked, const Vec3& o, const Vec3& d, float t,
                     std::mt19937& gen) const override;

    float pdfValueSegment(const Vec3& o, const Vec3& d, float t, const Vec3& point,
                          const Vec3& dir, const Hittable* hitEmitter,
                          const Light* hitLamp) const override;

    bool empty() const override;

    const LightTree* tree() const override { return tree_.get(); }

private:
    const LightList* lightList_;
    std::unique_ptr<LightTree> tree_;
};

} // namespace astroray
