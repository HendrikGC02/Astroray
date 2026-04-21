#pragma once
#include "raytracer.h"
#include <utility>

// ============================================================================
// TEXTURES
// ============================================================================

class Texture {
public:
    enum class CoordMode {
        UV = 0,
        Generated,
        Object,
        Camera,
        Normal,
        Reflection,
        Window
    };

private:
    CoordMode coordMode = CoordMode::UV;

protected:
    static Vec2 directionToUV(const Vec3& d) {
        Vec3 n = d.normalized();
        float theta = std::acos(std::clamp(n.y, -1.0f, 1.0f));
        float phi = std::atan2(n.z, n.x);
        float u = 0.5f + phi / (2.0f * float(M_PI));
        if (u < 0.0f) u += 1.0f;
        if (u >= 1.0f) u -= 1.0f;
        float v = 1.0f - theta / float(M_PI);
        return Vec2(u, v);
    }

    std::pair<Vec2, Vec3> textureCoordinates(const HitRecord& rec, const Vec3& wo) const {
        switch (coordMode) {
            case CoordMode::Generated: {
                if (rec.hitObject) {
                    AABB box;
                    if (rec.hitObject->boundingBox(box)) {
                        Vec3 size = box.max - box.min;
                        Vec3 p = rec.objectPoint;
                        Vec3 g(
                            size.x > 1e-6f ? (p.x - box.min.x) / size.x : 0.0f,
                            size.y > 1e-6f ? (p.y - box.min.y) / size.y : 0.0f,
                            size.z > 1e-6f ? (p.z - box.min.z) / size.z : 0.0f
                        );
                        g = Vec3(std::clamp(g.x, 0.0f, 1.0f),
                                 std::clamp(g.y, 0.0f, 1.0f),
                                 std::clamp(g.z, 0.0f, 1.0f));
                        return {Vec2(g.x, g.y), g};
                    }
                }
                return {rec.uv, rec.objectPoint};
            }
            case CoordMode::Object:
                return {Vec2(rec.objectPoint.x, rec.objectPoint.y), rec.objectPoint};
            case CoordMode::Camera: {
                if (!rec.hasCameraFrame) return {Vec2(rec.point.x, rec.point.y), rec.point};
                Vec3 rel = rec.point - rec.cameraOrigin;
                Vec3 c(rel.dot(rec.cameraU), rel.dot(rec.cameraV), rel.dot(-rec.cameraW));
                return {Vec2(c.x, c.y), c};
            }
            case CoordMode::Normal: {
                Vec3 n = rec.normal * 0.5f + Vec3(0.5f);
                return {Vec2(n.x, n.y), n};
            }
            case CoordMode::Reflection: {
                Vec3 inDir = rec.incomingDirection.length2() > 1e-8f ? rec.incomingDirection : -wo;
                Vec3 r = (inDir - rec.normal * (2.0f * inDir.dot(rec.normal))).normalized();
                return {directionToUV(r), r};
            }
            case CoordMode::Window:
                return {rec.windowUV, Vec3(rec.windowUV.u, rec.windowUV.v, 0.0f)};
            case CoordMode::UV:
            default:
                return {rec.uv, rec.point};
        }
    }

public:
    virtual ~Texture() = default;
    virtual Vec3 value(const Vec2& uv, const Vec3& p) const = 0;
    Vec3 value(const HitRecord& rec, const Vec3& wo) const {
        auto [uv, p] = textureCoordinates(rec, wo);
        return value(uv, p);
    }
    Vec3 valueOffset(const HitRecord& rec, const Vec3& wo, float du, float dv) const {
        auto [uv, p] = textureCoordinates(rec, wo);
        return value(Vec2(uv.u + du, uv.v + dv), p);
    }
    void setCoordMode(CoordMode mode) { coordMode = mode; }
    CoordMode getCoordMode() const { return coordMode; }
};

class SolidColor : public Texture {
    Vec3 color;
public:
    SolidColor(const Vec3& c) : color(c) {}
    Vec3 value(const Vec2&, const Vec3&) const override { return color; }
};

class CheckerTexture : public Texture {
    std::shared_ptr<Texture> odd, even;
    float scale;
public:
    CheckerTexture(const Vec3& c1, const Vec3& c2, float s = 10)
        : odd(std::make_shared<SolidColor>(c1)), even(std::make_shared<SolidColor>(c2)), scale(s) {}
    Vec3 value(const Vec2& uv, const Vec3& p) const override {
        float sines = std::sin(scale*p.x) * std::sin(scale*p.y) * std::sin(scale*p.z);
        return sines < 0 ? odd->value(uv, p) : even->value(uv, p);
    }
};

class NoiseTexture : public Texture {
    float scale;
public:
    static float noise(const Vec3& p) {
        float n = std::sin(p.dot(Vec3(12.9898f, 78.233f, 37.719f))) * 43758.5453f;
        return n - std::floor(n);
    }
    NoiseTexture(float s = 1) : scale(s) {}
    Vec3 value(const Vec2&, const Vec3& p) const override { return Vec3(noise(p * scale)); }
};

class ImageTexture : public Texture {
    std::vector<Vec3> data;
    int width = 0, height = 0;
public:
    void setData(const std::vector<Vec3>& d, int w, int h) { data = d; width = w; height = h; }
    Vec3 value(const Vec2& uv, const Vec3&) const override {
        if (data.empty()) return Vec3(1, 0, 1);
        float u = std::clamp(uv.u, 0.0f, 1.0f);
        float v = 1 - std::clamp(uv.v, 0.0f, 1.0f);
        int i = std::min((int)(u * width), width - 1);
        int j = std::min((int)(v * height), height - 1);
        return data[j * width + i];
    }
};

class MarbleTexture : public Texture {
    float scale;
    float turbulence(const Vec3& p, int depth = 7) const {
        float accum = 0, weight = 1.0f;
        Vec3 temp = p;
        for (int i = 0; i < depth; i++) { accum += weight * NoiseTexture::noise(temp); weight *= 0.5f; temp *= 2; }
        return std::abs(accum);
    }
public:
    MarbleTexture(float s = 1) : scale(s) {}
    Vec3 value(const Vec2&, const Vec3& p) const override {
        float n = 0.5f * (1 + std::sin(scale * p.z + 10 * turbulence(p)));
        return Vec3(0.8f) * n + Vec3(0.2f) * (1 - n);
    }
};

class WoodTexture : public Texture {
    float scale;
public:
    WoodTexture(float s = 1) : scale(s) {}
    Vec3 value(const Vec2&, const Vec3& p) const override {
        float r = std::sqrt(p.x*p.x + p.z*p.z);
        float n = NoiseTexture::noise(Vec3(r * scale, p.y * scale, 0));
        n = std::pow((n + 1) * 0.5f, 3);
        return Vec3(0.6f, 0.3f, 0.1f) * n + Vec3(0.4f, 0.2f, 0.05f) * (1 - n);
    }
};

// ============================================================================
// PROCEDURAL TEXTURES — issue #19
// ============================================================================

// --- Gradient texture ---
class GradientTexture : public Texture {
    // type: 0=linear, 1=quadratic, 2=easing, 3=diagonal, 4=spherical, 5=quadratic sphere, 6=radial
    int gradType;
    Vec3 color1, color2;
    float scale;
public:
    GradientTexture(int type = 0, const Vec3& c1 = Vec3(0), const Vec3& c2 = Vec3(1), float s = 1.0f)
        : gradType(type), color1(c1), color2(c2), scale(s) {}
    Vec3 value(const Vec2& uv, const Vec3& p) const override {
        Vec3 sp = p * scale;
        float t = 0;
        switch (gradType) {
            case 1: t = std::clamp(sp.x * sp.x, 0.0f, 1.0f); break;          // quadratic
            case 2: { float x = std::clamp(sp.x, 0.0f, 1.0f); t = x*x*(3-2*x); break; } // easing
            case 3: t = std::clamp((sp.x + sp.y) * 0.5f, 0.0f, 1.0f); break; // diagonal
            case 4: t = std::clamp(std::sqrt(sp.x*sp.x + sp.y*sp.y + sp.z*sp.z), 0.0f, 1.0f); break; // spherical
            case 5: { float r = std::sqrt(sp.x*sp.x + sp.y*sp.y + sp.z*sp.z); t = 1.0f - std::clamp(r*r, 0.0f, 1.0f); break; } // quadratic sphere
            case 6: t = std::fmod(std::atan2(sp.y, sp.x) / (2.0f * float(M_PI)) + 1.0f, 1.0f); break; // radial
            default: t = std::clamp(sp.x, 0.0f, 1.0f); break;                // linear
        }
        return color1 * (1.0f - t) + color2 * t;
    }
};

// --- Wave texture ---
// bandDir: 0=bands, 1=rings; profile: 0=sine, 1=saw, 2=triangle
class WaveTexture : public Texture {
    int bandDir;   // 0=bands (X), 1=rings (radial)
    int profile;   // 0=sine, 1=saw, 2=triangle
    float scale, distortion, detail, roughness, lacunarity;
    Vec3 colorLow, colorHigh;
public:
    WaveTexture(int bd = 0, int prof = 0, float sc = 5.0f, float dist = 0.0f,
                float det = 2.0f, float rough = 0.5f, float lac = 2.0f,
                const Vec3& c1 = Vec3(0), const Vec3& c2 = Vec3(1))
        : bandDir(bd), profile(prof), scale(sc), distortion(dist),
          detail(det), roughness(rough), lacunarity(lac), colorLow(c1), colorHigh(c2) {}

    static float turbulence(const Vec3& p, float det, float rough, float lac) {
        float accum = 0, w = 1.0f;
        Vec3 pp = p;
        int steps = std::max(1, (int)det);
        for (int i = 0; i < steps; ++i) {
            accum += w * NoiseTexture::noise(pp);
            w *= rough;
            pp = pp * lac;
        }
        return accum;
    }

    Vec3 value(const Vec2&, const Vec3& p) const override {
        Vec3 sp = p * scale;
        float d = distortion > 0.0f ? distortion * turbulence(sp, detail, roughness, lacunarity) : 0.0f;
        float phase;
        if (bandDir == 1) {
            float r = std::sqrt(sp.x*sp.x + sp.y*sp.y + sp.z*sp.z);
            phase = (r + d) * float(M_PI);
        } else {
            phase = (sp.x + d) * float(M_PI);
        }
        float t;
        if (profile == 1) { // saw
            t = 1.0f - std::fmod(phase / float(M_PI), 1.0f);
        } else if (profile == 2) { // triangle
            float x = std::fmod(phase / float(M_PI), 1.0f);
            t = x < 0.5f ? 2.0f * x : 2.0f - 2.0f * x;
        } else { // sine
            t = 0.5f + 0.5f * std::sin(phase);
        }
        return colorLow * (1.0f - t) + colorHigh * t;
    }
};

// --- Magic texture ---
class MagicTexture : public Texture {
    int turbDepth;
    float scale, distortion;
    Vec3 color1, color2;
public:
    MagicTexture(int depth = 2, float sc = 5.0f, float dist = 1.0f,
                 const Vec3& c1 = Vec3(0), const Vec3& c2 = Vec3(1))
        : turbDepth(depth), scale(sc), distortion(dist), color1(c1), color2(c2) {}
    Vec3 value(const Vec2&, const Vec3& p) const override {
        float x = std::sin((p.x * scale + p.y * scale + p.z * scale) * float(M_PI));
        float y = std::cos((-p.x * scale + p.y * scale - p.z * scale) * float(M_PI));
        float z = -std::cos((-p.x * scale - p.y * scale + p.z * scale) * float(M_PI));
        if (turbDepth > 1) {
            float d = distortion * 0.25f;
            x *= d; y *= d; z *= d;
            y = -std::cos(x - y + z) * d;
            if (turbDepth > 2) {
                x = std::cos(x - y - z) * d;
                if (turbDepth > 3) {
                    z = std::sin(-x - y + z) * d;
                    if (turbDepth > 4) y = -std::cos(x + y - z) * d;
                }
            }
        }
        float t = std::clamp(0.5f + 0.5f * (x + y + z) / 3.0f, 0.0f, 1.0f);
        return color1 * (1.0f - t) + color2 * t;
    }
};

// --- Voronoi texture ---
// distMetric: 0=Euclidean, 1=Manhattan, 2=Chebychev, 3=Minkowski(p=2.5)
// feature: 0=F1, 1=F2, 2=F1+F2, 3=F2-F1, 4=smooth_F1
class VoronoiTexture : public Texture {
    float scale, randomness, smoothness;
    int distMetric, feature;
    Vec3 colorLow, colorHigh;
public:
    VoronoiTexture(float sc = 5.0f, float rand = 1.0f, int dm = 0, int feat = 0,
                   float smooth = 1.0f, const Vec3& c1 = Vec3(0), const Vec3& c2 = Vec3(1))
        : scale(sc), randomness(rand), smoothness(smooth), distMetric(dm), feature(feat),
          colorLow(c1), colorHigh(c2) {}

    static float hash1(float n) {
        float x = std::sin(n) * 43758.5453f;
        return x - std::floor(x);
    }
    static Vec3 hash3(Vec3 p) {
        Vec3 q(p.dot(Vec3(127.1f, 311.7f, 74.7f)),
               p.dot(Vec3(269.5f, 183.3f, 246.1f)),
               p.dot(Vec3(113.5f, 271.9f, 124.6f)));
        return Vec3(hash1(q.x), hash1(q.y), hash1(q.z));
    }
    float dist(const Vec3& a, const Vec3& b) const {
        Vec3 d = a - b;
        switch (distMetric) {
            case 1: return std::abs(d.x) + std::abs(d.y) + std::abs(d.z);
            case 2: return std::max({std::abs(d.x), std::abs(d.y), std::abs(d.z)});
            case 3: { float p = 2.5f; return std::pow(std::pow(std::abs(d.x),p)+std::pow(std::abs(d.y),p)+std::pow(std::abs(d.z),p), 1.0f/p); }
            default: return std::sqrt(d.dot(d));
        }
    }
    Vec3 value(const Vec2&, const Vec3& p) const override {
        Vec3 sp = p * scale;
        Vec3 ip(std::floor(sp.x), std::floor(sp.y), std::floor(sp.z));
        float f1 = 1e9f, f2 = 1e9f;
        float smoothF1 = 0.0f;
        for (int dz = -1; dz <= 1; ++dz)
        for (int dy = -1; dy <= 1; ++dy)
        for (int dx = -1; dx <= 1; ++dx) {
            Vec3 nb(ip.x+dx, ip.y+dy, ip.z+dz);
            Vec3 r = nb + hash3(nb) * randomness;
            float d = dist(sp, r);
            if (d < f1) { f2 = f1; f1 = d; }
            else if (d < f2) { f2 = d; }
            if (smoothness > 0.0f && smoothness < 1e9f) {
                float h = std::max(smoothness - d, 0.0f) / smoothness;
                smoothF1 += h * h * h;
            }
        }
        float val;
        switch (feature) {
            case 1: val = f2; break;
            case 2: val = (f1 + f2) * 0.5f; break;
            case 3: val = f2 - f1; break;
            case 4: val = smoothness > 0.0f ? -std::log(smoothF1) / 3.0f : f1; break;
            default: val = f1; break;
        }
        float t = std::clamp(val, 0.0f, 1.0f);
        return colorLow * (1.0f - t) + colorHigh * t;
    }
};

// --- Brick texture ---
class BrickTexture : public Texture {
    Vec3 colorBrick, colorMortar;
    float brickWidth, brickHeight, mortarSize, offset, scale;
public:
    BrickTexture(const Vec3& brick = Vec3(0.7f, 0.35f, 0.2f),
                 const Vec3& mortar = Vec3(0.9f),
                 float bw = 0.5f, float bh = 0.25f, float mort = 0.02f,
                 float off = 0.5f, float sc = 5.0f)
        : colorBrick(brick), colorMortar(mortar),
          brickWidth(std::max(0.001f, bw)), brickHeight(std::max(0.001f, bh)),
          mortarSize(mort), offset(off), scale(sc) {}
    Vec3 value(const Vec2& uv, const Vec3&) const override {
        float u = uv.u * scale;
        float v = uv.v * scale;
        int row = (int)std::floor(v / brickHeight);
        float rowOffset = (row % 2 == 0) ? 0.0f : offset * brickWidth;
        float uu = std::fmod(u - rowOffset, brickWidth);
        if (uu < 0) uu += brickWidth;
        float vv = std::fmod(v, brickHeight);
        float half = mortarSize * 0.5f;
        if (uu < half || uu > brickWidth - half || vv < half || vv > brickHeight - half)
            return colorMortar;
        return colorBrick;
    }
};

// --- Musgrave (fBm) texture ---
class MusgraveTexture : public Texture {
    // type: 0=fBm, 1=multifractal, 2=ridged, 3=hybrid
    int musType;
    float scale, detail, dimension, lacunarity, gain;
    Vec3 colorLow, colorHigh;
public:
    MusgraveTexture(int type = 0, float sc = 5.0f, float det = 2.0f,
                   float dim = 2.0f, float lac = 2.0f, float g = 1.0f,
                   const Vec3& c1 = Vec3(0), const Vec3& c2 = Vec3(1))
        : musType(type), scale(sc), detail(det), dimension(dim),
          lacunarity(lac), gain(g), colorLow(c1), colorHigh(c2) {}
    Vec3 value(const Vec2&, const Vec3& p) const override {
        Vec3 sp = p * scale;
        float val = 0.0f;
        float amp = 1.0f, freq = 1.0f;
        float H = std::max(0.001f, dimension - 1.0f);
        int steps = std::max(1, (int)detail);
        if (musType == 2) { // ridged
            float signal = NoiseTexture::noise(sp);
            signal = std::abs(signal - 0.5f) * 2.0f; // ridge
            val = signal;
            float weight = 1.0f;
            for (int i = 1; i < steps; ++i) {
                sp = sp * lacunarity;
                amp *= gain;
                weight = std::clamp(signal * gain, 0.0f, 1.0f);
                signal = NoiseTexture::noise(sp);
                signal = (1.0f - std::abs(signal - 0.5f) * 2.0f);
                val += weight * std::pow(freq, -H) * signal;
                freq *= lacunarity;
                signal = val;
            }
        } else { // fBm / multifractal / hybrid
            for (int i = 0; i < steps; ++i) {
                val += amp * (NoiseTexture::noise(sp * freq) - 0.5f);
                freq *= lacunarity;
                amp *= std::pow(lacunarity, -H);
            }
        }
        float t = std::clamp(0.5f + 0.5f * val, 0.0f, 1.0f);
        return colorLow * (1.0f - t) + colorHigh * t;
    }
};

// ============================================================================
// TEXTURED MATERIAL
// ============================================================================

class TexturedLambertian : public Material {
    std::shared_ptr<Texture> albedo;
public:
    TexturedLambertian(std::shared_ptr<Texture> a) : albedo(a) {}
    Vec3 eval(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        if (wi.dot(rec.normal) <= 0) return Vec3(0);
        return albedo->value(rec, wo) / M_PI * wi.dot(rec.normal);
    }
    BSDFSample sample(const HitRecord& rec, const Vec3& wo, std::mt19937& gen) const override {
        BSDFSample s;
        Vec3 localWi = Vec3::randomCosineDirection(gen);
        s.wi = rec.tangent * localWi.x + rec.bitangent * localWi.y + rec.normal * localWi.z;
        s.f = albedo->value(rec, wo) / M_PI * s.wi.dot(rec.normal);
        s.pdf = s.wi.dot(rec.normal) / M_PI;
        s.isDelta = false;
        return s;
    }
    float pdf(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        float c = wi.dot(rec.normal);
        return c > 0 ? c / M_PI : 0;
    }
};
namespace astroray {
// Defined in plugins/materials/normal_mapped.cpp
std::shared_ptr<Material> makeNormalMapped(
    std::shared_ptr<Material> base,
    std::shared_ptr<Texture> normalTex,
    std::shared_ptr<Texture> bumpTex,
    float normalStr, float bumpStr, float bumpDist);
} // namespace astroray


// ConstantMedium class body moved to include/astroray/shapes.h (pkg04).
class ConstantMedium;

// ============================================================================
// TRANSFORMS
// ============================================================================

class Translate : public Hittable {
    std::shared_ptr<Hittable> object;
    Vec3 offset;
public:
    Translate(std::shared_ptr<Hittable> obj, const Vec3& d) : object(obj), offset(d) {}
    bool hit(const Ray& r, float tMin, float tMax, HitRecord& rec) const override {
        Ray moved(r.origin - offset, r.direction, r.time, r.screenU, r.screenV);
        moved.hasCameraFrame = r.hasCameraFrame;
        moved.cameraOrigin = r.cameraOrigin;
        moved.cameraU = r.cameraU;
        moved.cameraV = r.cameraV;
        moved.cameraW = r.cameraW;
        if (!object->hit(moved, tMin, tMax, rec)) return false;
        rec.point += offset;
        rec.setFaceNormal(moved, rec.normal);
        return true;
    }
    bool boundingBox(AABB& box) const override {
        if (!object->boundingBox(box)) return false;
        box = AABB(box.min + offset, box.max + offset);
        return true;
    }
};

class Scale : public Hittable {
    std::shared_ptr<Hittable> object;
    Vec3 scale;
public:
    Scale(std::shared_ptr<Hittable> obj, const Vec3& s) : object(obj), scale(s) {}
    bool hit(const Ray& r, float tMin, float tMax, HitRecord& rec) const override {
        Vec3 o(r.origin.x/scale.x, r.origin.y/scale.y, r.origin.z/scale.z);
        Vec3 d(r.direction.x/scale.x, r.direction.y/scale.y, r.direction.z/scale.z);
        Ray scaled(o, d, r.time, r.screenU, r.screenV);
        scaled.hasCameraFrame = r.hasCameraFrame;
        scaled.cameraOrigin = r.cameraOrigin;
        scaled.cameraU = r.cameraU;
        scaled.cameraV = r.cameraV;
        scaled.cameraW = r.cameraW;
        if (!object->hit(scaled, tMin, tMax, rec)) return false;
        rec.point = Vec3(rec.point.x*scale.x, rec.point.y*scale.y, rec.point.z*scale.z);
        Vec3 n(rec.normal.x/scale.x, rec.normal.y/scale.y, rec.normal.z/scale.z);
        rec.setFaceNormal(r, n.normalized());
        return true;
    }
    bool boundingBox(AABB& box) const override {
        if (!object->boundingBox(box)) return false;
        box = AABB(Vec3(box.min.x*scale.x, box.min.y*scale.y, box.min.z*scale.z),
                   Vec3(box.max.x*scale.x, box.max.y*scale.y, box.max.z*scale.z));
        return true;
    }
};

class RotateY : public Hittable {
    std::shared_ptr<Hittable> object;
    float sinT, cosT;
public:
    RotateY(std::shared_ptr<Hittable> obj, float angle) : object(obj) {
        float rad = angle * M_PI / 180.0f;
        sinT = std::sin(rad); cosT = std::cos(rad);
    }
    bool hit(const Ray& r, float tMin, float tMax, HitRecord& rec) const override {
        Vec3 o(cosT*r.origin.x + sinT*r.origin.z, r.origin.y, -sinT*r.origin.x + cosT*r.origin.z);
        Vec3 d(cosT*r.direction.x + sinT*r.direction.z, r.direction.y, -sinT*r.direction.x + cosT*r.direction.z);
        Ray rot(o, d, r.time, r.screenU, r.screenV);
        rot.hasCameraFrame = r.hasCameraFrame;
        rot.cameraOrigin = r.cameraOrigin;
        rot.cameraU = r.cameraU;
        rot.cameraV = r.cameraV;
        rot.cameraW = r.cameraW;
        if (!object->hit(rot, tMin, tMax, rec)) return false;
        Vec3 p = rec.point;
        rec.point = Vec3(cosT*p.x - sinT*p.z, p.y, sinT*p.x + cosT*p.z);
        Vec3 n = rec.normal;
        rec.setFaceNormal(r, Vec3(cosT*n.x - sinT*n.z, n.y, sinT*n.x + cosT*n.z));
        return true;
    }
    bool boundingBox(AABB& box) const override { return object->boundingBox(box); }
};

// Mesh class body moved to include/astroray/shapes.h (pkg04).
class Mesh;
