#pragma once
#include <functional>
#include <memory>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

namespace astroray {

class ParamDict;

template <typename Product>
class Registry {
public:
    using Factory = std::function<std::shared_ptr<Product>(const ParamDict&)>;

    static Registry& instance() { static Registry r; return r; }

    void add(const std::string& name, Factory f) {
        factories_[name] = std::move(f);
    }

    std::shared_ptr<Product> create(const std::string& name, const ParamDict& p) const {
        auto it = factories_.find(name);
        if (it == factories_.end())
            throw std::runtime_error("astroray: unknown plugin '" + name + "'");
        return it->second(p);
    }

    std::vector<std::string> names() const {
        std::vector<std::string> result;
        result.reserve(factories_.size());
        for (const auto& [k, v] : factories_)
            result.push_back(k);
        return result;
    }

private:
    std::unordered_map<std::string, Factory> factories_;
};

} // namespace astroray
