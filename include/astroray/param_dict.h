#pragma once
#include "raytracer.h"
#include <string>
#include <unordered_map>
#include <variant>
#include <vector>

namespace astroray {

class ParamDict {
    using Value = std::variant<float, int, bool, std::string, Vec3, std::vector<float>>;
    std::unordered_map<std::string, Value> data_;

    template <typename T>
    T get_(const std::string& key, T dflt) const {
        auto it = data_.find(key);
        if (it == data_.end()) {
#ifndef NDEBUG
            // Unknown key — silent fallback in release, warn only in debug builds
            // (stderr write omitted to keep the header dependency-free from <cstdio>)
#endif
            return dflt;
        }
        const T* v = std::get_if<T>(&it->second);
        return v ? *v : dflt;
    }

public:
    ParamDict& set(const std::string& key, Value v) {
        data_[key] = std::move(v);
        return *this;
    }

    float              getFloat     (const std::string& key, float              dflt = 0.0f) const { return get_<float>(key, dflt); }
    int                getInt       (const std::string& key, int                dflt = 0)    const { return get_<int>(key, dflt); }

    // Numeric accessor that returns a float whether the value was stored as a
    // float or an int. get_<T> uses std::get_if<T> (exact-type match), so a value
    // set via the int route is invisible to getFloat and vice-versa; getNumber
    // bridges that so an integrator param can be supplied as either from Python
    // (set_integrator_param / set_integrator_param_float). pkg-integrator-float-param.
    float getNumber(const std::string& key, float dflt = 0.0f) const {
        auto it = data_.find(key);
        if (it == data_.end()) return dflt;
        if (const float* f = std::get_if<float>(&it->second)) return *f;
        if (const int*   i = std::get_if<int>(&it->second))   return static_cast<float>(*i);
        return dflt;
    }
    bool               getBool      (const std::string& key, bool               dflt = false) const { return get_<bool>(key, dflt); }
    std::string        getString    (const std::string& key, std::string        dflt = "")   const { return get_<std::string>(key, dflt); }
    Vec3               getVec3      (const std::string& key, Vec3               dflt = {})   const { return get_<Vec3>(key, dflt); }
    std::vector<float> getFloatArray(const std::string& key, std::vector<float> dflt = {})   const { return get_<std::vector<float>>(key, dflt); }
};

} // namespace astroray
