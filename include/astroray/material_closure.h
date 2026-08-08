#pragma once

#include <array>
#include <cstdint>
#include <string>

namespace astroray {

struct ClosureColor {
    float x = 1.0f;
    float y = 1.0f;
    float z = 1.0f;
};

enum class MaterialClosureType : uint8_t {
    None = 0,
    Diffuse = 1,
    GGXConductor = 2,
    DielectricTransmission = 3,
    Clearcoat = 4,
    Sheen = 5,
    Emission = 6,
    ThinGlass = 7,
    // pkg178 Stage 2: monolithic native-Principled core-lobe closure. Unlike the
    // other types (each a single static lobe), this carries ALL of the Stage-1
    // core-lobe params so the device twin (gpu_principled_*) can run the SAME
    // view-dependent lobe assembly the CPU PrincipledPlugin::assembleLobes does
    // (Fresnel-weighted selection + ggxDirectionalAlbedo layering are functions
    // of wo, so they cannot be baked into static per-lobe closure weights). A
    // Principled material therefore emits exactly ONE closure of this type.
    Principled = 8,
};

struct MaterialClosure {
    MaterialClosureType type = MaterialClosureType::None;
    ClosureColor color{};
    float weight = 1.0f;
    float roughness = 0.0f;
    float metallic = 0.0f;
    float ior = 1.5f;
    float transmission = 0.0f;
    float clearcoatGloss = 1.0f;
    bool twoSidedEmission = false;
    // pkg178 Stage 2 (Principled core lobes only): extra params the monolithic
    // Principled closure needs beyond the shared fields above. Unused (defaults)
    // by every other closure type. color/roughness/metallic/ior/transmission
    // carry base_color / roughness / metallic / ior / transmission_weight.
    ClosureColor specularTint{};        // Cycles specular_tint (RGB)
    float specularIorLevel = 0.5f;      // Cycles specular_ior_level
    float diffuseRoughness = 0.0f;      // Cycles diffuse_roughness (EON)
};

class MaterialClosureGraph {
public:
    static constexpr int kMaxClosures = 8;

    bool add(const MaterialClosure& closure);
    bool empty() const { return count_ == 0; }
    int count() const { return count_; }
    const MaterialClosure& closure(int index) const { return closures_[index]; }
    const std::array<MaterialClosure, kMaxClosures>& closures() const { return closures_; }

private:
    std::array<MaterialClosure, kMaxClosures> closures_{};
    int count_ = 0;
};

MaterialClosure makeDiffuseClosure(ClosureColor color, float weight = 1.0f);
MaterialClosure makeGGXConductorClosure(ClosureColor color, float roughness, float weight = 1.0f);
MaterialClosure makeDielectricTransmissionClosure(
    ClosureColor color,
    float ior,
    float roughness = 0.0f,
    float transmission = 1.0f,
    float weight = 1.0f);
MaterialClosure makeEmissionClosure(
    ClosureColor color,
    float intensity,
    bool twoSided = false,
    float weight = 1.0f);
MaterialClosure makeThinGlassClosure(
    ClosureColor color,
    float ior,
    float roughness = 0.0f,
    float transmission = 1.0f,
    float weight = 1.0f);
// pkg178 Stage 2: build the monolithic native-Principled core-lobe closure.
// `color` = base_color; `transmission` = transmission_weight. Mirrors the
// Stage-1 PrincipledPlugin ctor param set (plugins/materials/principled.cpp).
MaterialClosure makePrincipledClosure(
    ClosureColor baseColor,
    float metallic,
    float roughness,
    float ior,
    float specularIorLevel,
    ClosureColor specularTint,
    float transmission,
    float diffuseRoughness,
    float weight = 1.0f);

const char* closureTypeName(MaterialClosureType type);
bool validateClosureGraph(const MaterialClosureGraph& graph, std::string* reason = nullptr);

} // namespace astroray
