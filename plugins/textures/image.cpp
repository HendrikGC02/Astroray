#include "astroray/register.h"
#include "advanced_features.h"
#include "stb_image.h"

class ImagePlugin : public ImageTexture {
public:
    explicit ImagePlugin(const astroray::ParamDict& p) {
        std::string path = p.getString("path", "");
        if (path.empty()) return;
        int w = 0, h = 0, ch = 0;
        unsigned char* raw = stbi_load(path.c_str(), &w, &h, &ch, 3);
        if (!raw) return;
        std::vector<Vec3> data(w * h);
        for (int i = 0; i < w * h; ++i)
            data[i] = Vec3(raw[i*3] / 255.0f, raw[i*3+1] / 255.0f, raw[i*3+2] / 255.0f);
        stbi_image_free(raw);
        setData(data, w, h);
    }
};

ASTRORAY_REGISTER_TEXTURE("image", ImagePlugin)
