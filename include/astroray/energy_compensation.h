#pragma once

#include <array>
#include <string>

namespace astroray {

class DisneyEnergyCompensationTables {
public:
    static constexpr int kGgxSize = 32;
    static constexpr int kSheenSize = 32;
    static constexpr int kClearcoatSize = 32;

    static const DisneyEnergyCompensationTables& instance();

    bool loaded() const { return loaded_; }
    const std::string& dataDirectory() const { return dataDirectory_; }

    float ggxE(float roughness, float mu) const;
    float ggxEavg(float roughness) const;
    float sheenAlbedo(float roughness, float mu) const;
    float clearcoatE(float mu) const;

private:
    DisneyEnergyCompensationTables();

    bool load();
    float sample2D(const std::array<float, kGgxSize * kGgxSize>& table,
                   int size, float roughness, float mu) const;
    float sample1D(const std::array<float, kGgxSize>& table, int size, float x) const;

    std::array<float, kGgxSize * kGgxSize> ggxE_{};
    std::array<float, kGgxSize> ggxEavg_{};
    std::array<float, kSheenSize * kSheenSize> sheenE_{};
    std::array<float, kClearcoatSize> clearcoatE_{};
    std::string dataDirectory_;
    bool loaded_ = false;
};

} // namespace astroray
