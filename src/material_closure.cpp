#include "astroray/material_closure.h"

#include <algorithm>
#include <cmath>

namespace astroray {

namespace {

static ClosureColor sanitizeColor(ClosureColor color) {
    color.x = std::clamp(color.x, 0.0f, 1.0e6f);
    color.y = std::clamp(color.y, 0.0f, 1.0e6f);
    color.z = std::clamp(color.z, 0.0f, 1.0e6f);
    return color;
}

static float sanitizeWeight(float weight) {
    return std::isfinite(weight) ? std::clamp(weight, 0.0f, 1.0e6f) : 0.0f;
}

} // namespace

bool MaterialClosureGraph::add(const MaterialClosure& closure) {
    if (count_ >= kMaxClosures || closure.type == MaterialClosureType::None)
        return false;
    closures_[count_++] = closure;
    return true;
}

MaterialClosure makeDiffuseClosure(ClosureColor color, float weight) {
    MaterialClosure c;
    c.type = MaterialClosureType::Diffuse;
    c.color = sanitizeColor(color);
    c.weight = sanitizeWeight(weight);
    c.roughness = 1.0f;
    return c;
}

MaterialClosure makeGGXConductorClosure(ClosureColor color, float roughness, float weight) {
    MaterialClosure c;
    c.type = MaterialClosureType::GGXConductor;
    c.color = sanitizeColor(color);
    c.weight = sanitizeWeight(weight);
    c.roughness = std::clamp(std::isfinite(roughness) ? roughness : 0.0f, 0.001f, 1.0f);
    c.metallic = 1.0f;
    return c;
}

MaterialClosure makeDielectricTransmissionClosure(
        ClosureColor color,
        float ior,
        float roughness,
        float transmission,
        float weight) {
    MaterialClosure c;
    c.type = MaterialClosureType::DielectricTransmission;
    c.color = sanitizeColor(color);
    c.weight = sanitizeWeight(weight);
    c.roughness = std::clamp(std::isfinite(roughness) ? roughness : 0.0f, 0.0f, 1.0f);
    c.ior = std::max(std::isfinite(ior) ? ior : 1.5f, 1.0f);
    c.transmission = std::clamp(std::isfinite(transmission) ? transmission : 1.0f, 0.0f, 1.0f);
    return c;
}

MaterialClosure makeEmissionClosure(
        ClosureColor color,
        float intensity,
        bool twoSided,
        float weight) {
    MaterialClosure c;
    c.type = MaterialClosureType::Emission;
    c.color = sanitizeColor(color);
    c.weight = sanitizeWeight(weight);
    c.transmission = std::max(std::isfinite(intensity) ? intensity : 0.0f, 0.0f);
    c.twoSidedEmission = twoSided;
    return c;
}

MaterialClosure makeThinGlassClosure(
        ClosureColor color,
        float ior,
        float roughness,
        float transmission,
        float weight) {
    MaterialClosure c = makeDielectricTransmissionClosure(
        color, ior, roughness, transmission, weight);
    c.type = MaterialClosureType::ThinGlass;
    return c;
}

const char* closureTypeName(MaterialClosureType type) {
    switch (type) {
        case MaterialClosureType::Diffuse: return "diffuse";
        case MaterialClosureType::GGXConductor: return "ggx_conductor";
        case MaterialClosureType::DielectricTransmission: return "dielectric_transmission";
        case MaterialClosureType::Clearcoat: return "clearcoat";
        case MaterialClosureType::Sheen: return "sheen";
        case MaterialClosureType::Emission: return "emission";
        case MaterialClosureType::ThinGlass: return "thin_glass";
        case MaterialClosureType::None:
        default:
            return "none";
    }
}

bool validateClosureGraph(const MaterialClosureGraph& graph, std::string* reason) {
    if (graph.empty()) {
        if (reason) *reason = "closure graph is empty";
        return false;
    }

    for (int i = 0; i < graph.count(); ++i) {
        const MaterialClosure& c = graph.closure(i);
        if (c.type == MaterialClosureType::None) {
            if (reason) *reason = "closure graph contains a none closure";
            return false;
        }
        if (!std::isfinite(c.weight) || c.weight < 0.0f) {
            if (reason) *reason = "closure graph contains an invalid weight";
            return false;
        }
        if (!std::isfinite(c.roughness) || c.roughness < 0.0f || c.roughness > 1.0f) {
            if (reason) *reason = "closure graph contains an invalid roughness";
            return false;
        }
        if ((c.type == MaterialClosureType::DielectricTransmission ||
             c.type == MaterialClosureType::ThinGlass) &&
            (!std::isfinite(c.ior) || c.ior < 1.0f)) {
            if (reason) *reason = "closure graph contains an invalid IOR";
            return false;
        }
    }
    return true;
}

} // namespace astroray
