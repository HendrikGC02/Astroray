#pragma once
// pkg39: Multi-wavelength rendering — SpectralProfile and SpectralProfileDatabase.
//
// SpectralProfile: lightweight, non-owning view into the database memory.
//   reflectance(lambda_nm) → linear interpolation on the 5 nm grid.
// SpectralProfileDatabase: singleton that owns the data loaded from profiles.bin.
//   Loaded once; thread-safe for concurrent reads after load().

#include <string>
#include <vector>
#include <unordered_map>

namespace astroray {

// Non-owning view of one material's reflectance curve from the ASPR database.
// Thread-safe: read-only after construction.
class SpectralProfile {
    const float* data_ = nullptr;
    int   n_    = 0;
    float lmin_ = 300.0f;
    float lstep_= 5.0f;
public:
    SpectralProfile() = default;
    SpectralProfile(const float* data, int n, float lmin, float lstep)
        : data_(data), n_(n), lmin_(lmin), lstep_(lstep) {}

    // Linearly-interpolated reflectance in [0, 1]. Clamps to grid boundaries.
    float reflectance(float lambda_nm) const noexcept {
        if (!data_ || n_ == 0) return 0.0f;
        float t = (lambda_nm - lmin_) / lstep_;
        int   i = static_cast<int>(t);
        float f = t - static_cast<float>(i);
        if (i < 0)       return data_[0];
        if (i >= n_ - 1) return data_[n_ - 1];
        return data_[i] * (1.0f - f) + data_[i + 1] * f;
    }

    bool valid() const noexcept { return data_ != nullptr && n_ > 0; }
};

// Loads and owns the ASPR binary database (profiles.bin from pkg38).
// Call load() once at startup; all subsequent get() calls are read-only.
class SpectralProfileDatabase {
    std::vector<float> storage_;                     // all float32 data
    std::vector<SpectralProfile> profiles_;          // views into storage_
    std::vector<std::string>    names_;              // parallel to profiles_
    std::unordered_map<std::string, int> index_;     // name → profiles_ index
    bool loaded_ = false;

    SpectralProfileDatabase() = default;
public:
    static SpectralProfileDatabase& instance();

    // Load from ASPR binary file. Idempotent if already loaded.
    void load(const std::string& path);

    // Returns nullptr when the name is not in the database.
    const SpectralProfile* get(const std::string& name) const;

    const std::vector<std::string>& names() const { return names_; }
    bool loaded() const { return loaded_; }
};

} // namespace astroray
