#include "raytracer.h"
#include "astroray/light_sampler.h"
#include "astroray/light_tree.h"
#include "astroray/light.h"
#include <algorithm>

namespace astroray {

// ============================================================================
// PowerLightSampler — power-weighted CDF (current LightList behavior)
// ============================================================================

LightSample PowerLightSampler::sample(const Vec3& point, const Vec3& normal,
                                      const SampledWavelengths& lambdas,
                                      std::mt19937& gen) const {
    // Delegate to LightList's original implementation.
    // This is a bit circular, but we need to extract the logic here.
    // For now, we'll inline the original LightList::sample logic.

    const auto& lights = lightList_->getLights();
    const auto& dedicatedLights = lightList_->getDedicatedLights();
    const auto& powerDist = lightList_->getPowerDist();
    float totalPower = lightList_->getTotalPower();

    size_t numHittableLights = lights.size();
    size_t numDedicatedLights = dedicatedLights.size();
    size_t totalLights = numHittableLights + numDedicatedLights;

    if (totalLights == 0) {
        return LightSample{Vec3(0), Vec3(0), Vec3(0), SampledSpectrum(0.0f), 0, 0};
    }

    // Sample light index from unified power CDF.
    std::uniform_real_distribution<float> dist(0, 1);
    float u = dist(gen) * totalPower;
    size_t idx = 0;
    for (size_t i = 0; i < powerDist.size(); ++i) {
        if (u < powerDist[i]) {
            idx = i;
            break;
        }
    }

    LightSample s;
    float selPdf = (idx > 0 ? powerDist[idx] - powerDist[idx - 1] : powerDist[0]) / totalPower;

    // Dispatch: first numHittableLights indices are legacy Hittables, rest are dedicated.
    if (idx < numHittableLights) {
        // Legacy Hittable path (emissive geometry).
        Vec3 dir = lights[idx]->random(point, gen);
        HitRecord rec;
        if (lights[idx]->hit(Ray(point, dir), 0.001f, std::numeric_limits<float>::max(), rec)) {
            s.position = rec.point;
            s.normal = rec.normal;
            Vec3 toPoint = (point - rec.point).normalized();
            Vec3 lightNormal = rec.frontFace ? rec.normal : -rec.normal;
            s.emission = lights[idx]->emittedRadiance(lightNormal, toPoint) *
                         lights[idx]->directionFalloff(toPoint);
            s.distance = rec.t;
            s.pdf = lights[idx]->pdfValue(point, dir) * selPdf;

            // Spectral emission: upsample RGB via RGBIlluminantSpectrum (temporary).
            s.emission_spec = RGBIlluminantSpectrum({s.emission.x, s.emission.y, s.emission.z}).sample(lambdas);
        }
    } else {
        // Dedicated Light path (pkg89 Phase A).
        size_t dedicatedIdx = idx - numHittableLights;
        const Light* light = dedicatedLights[dedicatedIdx].get();
        Light::LiSample liSample;
        light->sampleLi(liSample, point, normal, lambdas, gen);

        s.position = liSample.position;
        s.normal = liSample.normal;
        s.emission = liSample.emission_rgb;
        s.emission_spec = liSample.emission_spec;
        s.distance = liSample.distance;
        s.pdf = liSample.pdf * selPdf;
    }

    return s;
}

float PowerLightSampler::pdfValue(const Vec3& point, const Vec3& dir) const {
    const auto& lights = lightList_->getLights();
    const auto& dedicatedLights = lightList_->getDedicatedLights();
    const auto& powerDist = lightList_->getPowerDist();
    float totalPower = lightList_->getTotalPower();

    if (lights.empty() && dedicatedLights.empty()) return 0;

    float pdf = 0;
    size_t idx = 0;

    // Legacy Hittables.
    for (size_t i = 0; i < lights.size(); ++i, ++idx) {
        float selPdf = (idx > 0 ? powerDist[idx] - powerDist[idx - 1] : powerDist[0]) / totalPower;
        pdf += selPdf * lights[i]->pdfValue(point, dir);
    }

    // Dedicated Lights.
    for (size_t i = 0; i < dedicatedLights.size(); ++i, ++idx) {
        float selPdf = (idx > 0 ? powerDist[idx] - powerDist[idx - 1] : powerDist[0]) / totalPower;
        pdf += selPdf * dedicatedLights[i]->pdfLi(point, dir);
    }

    return pdf;
}

bool PowerLightSampler::empty() const {
    return lightList_->empty();
}

// ============================================================================
// TreeLightSampler — light tree (Conty 2018 + Cycles)
// ============================================================================

TreeLightSampler::TreeLightSampler(const LightList* lightList)
    : lightList_(lightList), tree_(std::make_unique<LightTree>()) {
    tree_->build(*lightList);
}

TreeLightSampler::~TreeLightSampler() = default;

LightSample TreeLightSampler::sample(const Vec3& point, const Vec3& normal,
                                     const SampledWavelengths& lambdas,
                                     std::mt19937& gen) const {
    if (tree_->empty()) {
        return LightSample{Vec3(0), Vec3(0), Vec3(0), SampledSpectrum(0.0f), 0, 0};
    }

    // Pick a light from the tree.
    std::uniform_real_distribution<float> dist(0, 1);
    float u = dist(gen);
    LightTree::PickResult pick = tree_->pick(point, normal, u, gen);

    if (pick.lightIndex < 0) {
        return LightSample{Vec3(0), Vec3(0), Vec3(0), SampledSpectrum(0.0f), 0, 0};
    }

    // Sample the chosen light.
    LightSample s;
    float treePdf = pick.pdf;

    if (!pick.isDedicated) {
        // Legacy Hittable path.
        const auto& lights = lightList_->getLights();
        Vec3 dir = lights[pick.lightIndex]->random(point, gen);
        HitRecord rec;
        if (lights[pick.lightIndex]->hit(Ray(point, dir), 0.001f, std::numeric_limits<float>::max(), rec)) {
            s.position = rec.point;
            s.normal = rec.normal;
            Vec3 toPoint = (point - rec.point).normalized();
            Vec3 lightNormal = rec.frontFace ? rec.normal : -rec.normal;
            s.emission = lights[pick.lightIndex]->emittedRadiance(lightNormal, toPoint) *
                         lights[pick.lightIndex]->directionFalloff(toPoint);
            s.distance = rec.t;
            s.pdf = lights[pick.lightIndex]->pdfValue(point, dir) * treePdf;

            // Spectral emission: upsample RGB via RGBIlluminantSpectrum.
            s.emission_spec = RGBIlluminantSpectrum({s.emission.x, s.emission.y, s.emission.z}).sample(lambdas);
        }
    } else {
        // Dedicated Light path.
        const auto& dedicatedLights = lightList_->getDedicatedLights();
        const Light* light = dedicatedLights[pick.lightIndex].get();
        Light::LiSample liSample;
        light->sampleLi(liSample, point, normal, lambdas, gen);

        s.position = liSample.position;
        s.normal = liSample.normal;
        s.emission = liSample.emission_rgb;
        s.emission_spec = liSample.emission_spec;
        s.distance = liSample.distance;
        s.pdf = liSample.pdf * treePdf;
    }

    return s;
}

float TreeLightSampler::pdfValue(const Vec3& point, const Vec3& dir) const {
    // For MIS, we compute the pdf of sampling direction `dir` from `point`.
    // This requires summing over all lights that could be sampled in that direction:
    //   pdf = sum_i [ tree_pdf(i) * light_i.pdfValue(point, dir) ]
    // This mirrors PowerLightSampler::pdfValue but uses tree selection probabilities.

    if (tree_->empty()) return 0.0f;

    const auto& lights = lightList_->getLights();
    const auto& dedicatedLights = lightList_->getDedicatedLights();

    // We need a normal for tree traversal. Since we don't have the actual surface normal here,
    // use the direction as a proxy (assume normal ≈ -dir for backfacing logic).
    // This is a heuristic; proper MIS would cache the shading normal from the hit point.
    Vec3 normal = -dir.normalized();

    float pdf = 0.0f;

    // Legacy Hittables.
    for (size_t i = 0; i < lights.size(); ++i) {
        float treePdf = tree_->pdf(point, normal, static_cast<int>(i), false);
        if (treePdf > 0.0f) {
            pdf += treePdf * lights[i]->pdfValue(point, dir);
        }
    }

    // Dedicated Lights.
    for (size_t i = 0; i < dedicatedLights.size(); ++i) {
        float treePdf = tree_->pdf(point, normal, static_cast<int>(i), true);
        if (treePdf > 0.0f) {
            pdf += treePdf * dedicatedLights[i]->pdfLi(point, dir);
        }
    }

    return pdf;
}

bool TreeLightSampler::empty() const {
    return tree_->empty();
}

} // namespace astroray
