#include "astroray/register.h"
#include "astroray/shapes.h"

class MeshPlugin : public Mesh {
public:
    explicit MeshPlugin(const astroray::ParamDict& p)
        : Mesh(astroray::MaterialRegistry::instance().create(
               p.getString("material_type", "lambertian"), p)) {
        std::string path = p.getString("path", "");
        if (!path.empty()) loadOBJ(path);
    }
};

ASTRORAY_REGISTER_SHAPE("mesh", MeshPlugin)
