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

const char* closureTypeName(MaterialClosureType type);
bool validateClosureGraph(const MaterialClosureGraph& graph, std::string* reason = nullptr);

} // namespace astroray
