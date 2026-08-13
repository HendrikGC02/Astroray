#pragma once
// pkg39: Multi-wavelength rendering — SpectralProfile and SpectralProfileDatabase.
//
// SpectralProfile: lightweight, non-owning view into the database memory.
//   reflectance(lambda_nm) → linear interpolation on the 5 nm grid.
// SpectralProfileDatabase: singleton that owns the data loaded from profiles.bin.
//   Loaded once; thread-safe for concurrent reads after load().

#include <string>
#include <vector>
#include <deque>
#include <unordered_map>

namespace astroray {

// pkg195 Stage C: how a material consults an attached SpectralProfile.
//   ExtendOnly (default) — profile drives only λ outside the visible band
//     [380, 780] nm; the visible band keeps the Jakob-Hanika RGB path. This is
//     the pkg39 behaviour; old scenes and the pkg58 material-panel fallback
//     keep it (no behaviour change).
//   Replace — the profile drives ALL λ (visible included), bypassing the JH
//     upsample entirely (design doc §3.1 principle 2: an authored SPD must never
//     round-trip through RGB). The Spectral Profile / Spectrum Preset / Drawn
//     Spectrum source nodes wired to a Surface set this.
enum class ProfileMode { ExtendOnly, Replace };

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

    // Alias for emission SPD evaluation (pkg89 Q5 resolution).
    // The same spectral curve represents reflectance (BSDF) or relative SPD
    // (emission) depending on caller context. This inline alias makes emission
    // call sites self-documenting.
    float emission(float lambda_nm) const noexcept {
        return reflectance(lambda_nm);
    }

    bool valid() const noexcept { return data_ != nullptr && n_ > 0; }

    // pkg195 Stage B: grid metadata for the light-panel λ-range label. The DB
    // ships 300-2500 nm @ 5 nm today, but register_spectral_profile (Stage C)
    // accepts arbitrary ranges, so read them per-profile rather than assuming.
    float lambdaMin()  const noexcept { return lmin_; }
    float lambdaStep() const noexcept { return lstep_; }
    int   count()      const noexcept { return n_; }
};

// Loads and owns the ASPR binary database (profiles.bin from pkg38).
// Call load() once at startup; all subsequent get() calls are read-only.
class SpectralProfileDatabase {
    std::vector<float> storage_;                     // all float32 data (from file)
    std::vector<SpectralProfile> profiles_;          // views into storage_
    std::vector<std::string>    names_;              // parallel to profiles_
    std::unordered_map<std::string, int> index_;     // name → profiles_ index
    bool loaded_ = false;

    // pkg195 Stage C: runtime-registered profiles (register_spectral_profile).
    // Kept in pointer-stable containers (std::deque never invalidates element
    // addresses on push_back, unlike std::vector) because materials cache a
    // SpectralProfile* across a render — appending a new runtime profile must
    // not dangle those pointers. Re-registering an existing runtime name
    // overwrites its slot IN PLACE (the SpectralProfile view is rebuilt over the
    // refreshed buffer) so the cached pointer stays valid.
    std::deque<std::vector<float>> runtimeStorage_;
    std::deque<SpectralProfile>    runtimeProfiles_;
    std::unordered_map<std::string, int> runtimeIndex_;  // name → runtimeProfiles_ index

    SpectralProfileDatabase() = default;
public:
    static SpectralProfileDatabase& instance();

    // Load from ASPR binary file. Idempotent if already loaded.
    void load(const std::string& path);

    // Returns nullptr when the name is not in the database.
    const SpectralProfile* get(const std::string& name) const;

    // pkg195 Stage C: insert (or overwrite) a runtime profile from raw samples on
    // a regular λ grid. Returns a stable pointer to the stored profile. `values`
    // is the sample array; the grid is lambda_min_nm + i*lambda_step_nm.
    const SpectralProfile* registerProfile(const std::string& name,
                                           float lambda_min_nm,
                                           float lambda_step_nm,
                                           const std::vector<float>& values);

    // All profile names (file + runtime), file order first. Returned by value
    // because runtime names are held in a separate container.
    std::vector<std::string> names() const;
    bool loaded() const { return loaded_; }
};

} // namespace astroray
