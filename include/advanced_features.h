#pragma once
#include "raytracer.h"
#include "astroray/shader_vm.h"   // pkg219b — bounded per-texel op-VM
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
    Vec3 genMin_{0, 0, 0};
    Vec3 genSize_{0, 0, 0};
    bool hasGenBBox_ = false;
    // pkg59 follow-up: per-texture UV transform baked in from a Blender
    // Mapping node (Location + Rotation.z + Scale). Applied AFTER coord-mode
    // resolution so it composes with Generated/Object/UV. Order matches
    // Blender's "Point" Mapping node: scale → rotate → translate.
    Vec2 uvScale_{1.0f, 1.0f};
    Vec2 uvOffset_{0.0f, 0.0f};
    float uvRotation_ = 0.0f;  // radians, Z-axis only (2D)
    std::string uvLayerName_;
    // pkg219a — full 3-D Mapping node matrix (Location + XYZ-euler Rotation +
    // Scale) composed host-side by the Blender addon (mathutils.Matrix.
    // LocRotScale) and shipped as the top 3x4 rows, row-major. Reference:
    // Cycles svm/mapping_util.h svm_mapping POINT (Apache-2.0):
    //   out = location + Rotate(euler) * (scale * vector)
    // == M * vector, M = Translate(loc) * RotXYZ(rot) * Scale(scale).
    // Supersedes the 2-D uvScale/uvOffset/uvRotation path when set; those stay
    // for backward compat (legacy set_texture_uv_transform callers/tests).
    float mapping_[12] = {1.f,0.f,0.f,0.f, 0.f,1.f,0.f,0.f, 0.f,0.f,1.f,0.f};
    bool hasMapping_ = false;

protected:
    // Apply the 3x4 affine mapping matrix to a 3-D coordinate (point, w=1).
    Vec3 applyMappingPoint(const Vec3& p) const {
        return Vec3(
            mapping_[0]*p.x + mapping_[1]*p.y + mapping_[2]*p.z  + mapping_[3],
            mapping_[4]*p.x + mapping_[5]*p.y + mapping_[6]*p.z  + mapping_[7],
            mapping_[8]*p.x + mapping_[9]*p.y + mapping_[10]*p.z + mapping_[11]);
    }

    Vec2 applyUVTransform(const Vec2& uv) const {
        // Blender "Point" Mapping: out = location + rotation @ (scale * in).
        // 2D simplification: only Z rotation has effect on UV.
        float s = uv.u * uvScale_.u;
        float t = uv.v * uvScale_.v;
        if (uvRotation_ != 0.0f) {
            float c = std::cos(uvRotation_);
            float si = std::sin(uvRotation_);
            float u2 = c * s - si * t;
            float v2 = si * s + c * t;
            s = u2;
            t = v2;
        }
        return Vec2(s + uvOffset_.u, t + uvOffset_.v);
    }

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

    Vec2 selectedUV(const HitRecord& rec) const {
        if (!uvLayerName_.empty()) {
            for (size_t i = 0; i < rec.uvLayerNames.size() && i < rec.uvLayers.size(); ++i) {
                if (rec.uvLayerNames[i] == uvLayerName_) {
                    return rec.uvLayers[i];
                }
            }
        }
        return rec.uv;
    }

    std::pair<Vec2, Vec3> textureCoordinates(const HitRecord& rec, const Vec3& wo) const {
        Vec2 uv = selectedUV(rec);
        switch (coordMode) {
            case CoordMode::Generated: {
                // pkg115 generated-coords mesh fix: triangle meshes carry no
                // object-level hitObject (and a triangle's own bbox would be
                // wrong anyway), so the exporter bakes the OBJECT bounding box
                // onto the texture (set_texture_generated_bbox). Blender
                // semantics: object-local position normalized to the bbox
                // (Texture Coordinate > Generated; Cycles orco). The addon
                // bakes world transforms into vertices, so world == object
                // space for exported meshes. Shared-material multi-object
                // scenes get the last writer's bbox (per-object texture
                // instancing is the follow-up).
                if (hasGenBBox_) {
                    Vec3 size = genSize_;
                    Vec3 p = rec.objectPoint;
                    Vec3 g(
                        size.x > 1e-6f ? (p.x - genMin_.x) / size.x : 0.0f,
                        size.y > 1e-6f ? (p.y - genMin_.y) / size.y : 0.0f,
                        size.z > 1e-6f ? (p.z - genMin_.z) / size.z : 0.0f
                    );
                    g = Vec3(std::clamp(g.x, 0.0f, 1.0f),
                             std::clamp(g.y, 0.0f, 1.0f),
                             std::clamp(g.z, 0.0f, 1.0f));
                    return {Vec2(g.x, g.y), g};
                }
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
                return {uv, rec.objectPoint};
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
                // pkg115 parity fix: Blender's Normal coordinate output is the
                // SIGNED normal, no 0.5n+0.5 remap. Cycles svm/tex_coord.h:113-121
                // (object_inverse_normal_transform(sd->N), Apache-2.0) uses the
                // object-space normal; the addon bakes vertices to world space,
                // so the geometric world-space normal is exact for untransformed
                // objects and a documented approximation for rotated ones
                // (object-frame recovery would need per-object inverse
                // transforms the baked pipeline no longer has).
                Vec3 n = rec.frontFace ? rec.normal : rec.normal * -1.0f;  // geometric outward, signed
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
                // pkg115 parity fix: UV mode hands 3D evaluators (u,v,0), not the
                // world hit position. Blender's UV/UVMap coordinate is 2D; a 3D texture
                // node using it samples at (u,v,0) in its internal space. Audit §4.
                return {uv, Vec3(uv.u, uv.v, 0.0f)};
        }
    }

public:
    virtual ~Texture() = default;
    virtual Vec3 value(const Vec2& uv, const Vec3& p) const = 0;
    Vec3 value(const HitRecord& rec, const Vec3& wo) const {
        auto [uv, p] = textureCoordinates(rec, wo);
        // pkg219a: full 3-D Mapping applies to the texture coordinate. The
        // image sample uses (M*p).xy; p (untransformed) still feeds procedural
        // value(uv,p) so pkg190 voxel bakes stay byte-identical.
        if (hasMapping_) {
            Vec3 mp = applyMappingPoint(p);
            return value(Vec2(mp.x, mp.y), p);
        }
        return value(applyUVTransform(uv), p);
    }
    Vec3 valueOffset(const HitRecord& rec, const Vec3& wo, float du, float dv) const {
        auto [uv, p] = textureCoordinates(rec, wo);
        if (hasMapping_) {
            Vec3 mp = applyMappingPoint(p);
            return value(Vec2(mp.x + du, mp.y + dv), p);
        }
        Vec2 t = applyUVTransform(uv);
        return value(Vec2(t.u + du, t.v + dv), p);
    }
    void setCoordMode(CoordMode mode) { coordMode = mode; }
    // pkg115 generated-coords: object bbox baked by the exporter (see the
    // CoordMode::Generated comment above).
    void setGeneratedBBox(const Vec3& bmin, const Vec3& bsize) {
        genMin_ = bmin;
        genSize_ = bsize;
        hasGenBBox_ = true;
    }
    CoordMode getCoordMode() const { return coordMode; }
    // pkg190 — read-only bbox accessors so the GPU scene-upload (scene_upload.cu)
    // can bake a Generated/Object-coord procedural into a 3D voxel buffer and
    // hand the GPU sampler the same (genMin, genSize) frame this class uses to
    // build the normalized Generated coordinate (see the CoordMode::Generated
    // branch above: g = clamp((objectPoint - genMin_) / genSize_, 0, 1)).
    bool hasGeneratedBBox() const { return hasGenBBox_; }
    Vec3 getGeneratedMin()  const { return genMin_; }
    Vec3 getGeneratedSize() const { return genSize_; }
    // pkg59 follow-up: apply Mapping(Location, Rotation.z, Scale) at sample
    // time. 4-arg overload kept for backward compat (rotation defaults to 0).
    void setUVTransform(float sx, float sy, float ox, float oy) {
        uvScale_ = Vec2(sx, sy);
        uvOffset_ = Vec2(ox, oy);
        uvRotation_ = 0.0f;
    }
    void setUVTransform(float sx, float sy, float ox, float oy, float rotZRad) {
        uvScale_ = Vec2(sx, sy);
        uvOffset_ = Vec2(ox, oy);
        uvRotation_ = rotZRad;
    }
    Vec2 getUVScale()  const { return uvScale_;  }
    Vec2 getUVOffset() const { return uvOffset_; }
    float getUVRotation() const { return uvRotation_; }
    // pkg219a — full 3-D Mapping matrix (top 3x4 rows, row-major). Setting it
    // supersedes the 2-D UV transform above.
    void setMappingMatrix(const float m12[12]) {
        for (int i = 0; i < 12; ++i) mapping_[i] = m12[i];
        hasMapping_ = true;
    }
    bool hasMapping() const { return hasMapping_; }
    const float* getMappingMatrix() const { return mapping_; }
    void setUVLayerName(const std::string& name) { uvLayerName_ = name; }
    const std::string& getUVLayerName() const { return uvLayerName_; }

    // Spectral hook (pkg13). Default upsamples the RGB value per-call.
    virtual astroray::SampledSpectrum sampleSpectral(
            const Vec2& uv, const Vec3& p,
            const astroray::SampledWavelengths& lambdas) const {
        Vec3 rgb = value(uv, p);
        return astroray::RGBAlbedoSpectrum({rgb.x, rgb.y, rgb.z}).sample(lambdas);
    }
    astroray::SampledSpectrum sampleSpectral(
            const HitRecord& rec, const Vec3& wo,
            const astroray::SampledWavelengths& lambdas) const {
        auto [uv, p] = textureCoordinates(rec, wo);
        // pkg219a: full 3-D Mapping applies to the sample coord (see value()).
        if (hasMapping_) {
            Vec3 mp = applyMappingPoint(p);
            return sampleSpectral(Vec2(mp.x, mp.y), p, lambdas);
        }
        return sampleSpectral(applyUVTransform(uv), p, lambdas);
    }
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
        // pkg115 parity fix: replace sine-product with Blender's floor-parity formula.
        // Cycles intern/cycles/kernel/svm/checker.h::svm_checker (Apache-2.0):
        // p = (p + 0.000001) * 0.999999 (precision guard);
        // xi = abs((int)floor(p.x)); yi/zi same;
        // return ((xi % 2 == yi % 2) == (zi % 2)) ? 1 : 0;
        // Guard applied AFTER scaling, exactly like Cycles (epsilon must not
        // scale with the cell size): floor(((co*scale) + 1e-6) * 0.999999).
        Vec3 sp = (p * scale + Vec3(1e-6f)) * 0.999999f;
        int xi = std::abs((int)std::floor(sp.x));
        int yi = std::abs((int)std::floor(sp.y));
        int zi = std::abs((int)std::floor(sp.z));
        bool checker = ((xi % 2 == yi % 2) == (zi % 2));
        // Cycles maps parity-true -> fac=1 -> Color1 (svm_checker + the node's
        // color select); ctor order is (c1=odd, c2=even), so parity-true must
        // return the c1/'odd' member for Blender-identical cell colors.
        return checker ? odd->value(uv, p) : even->value(uv, p);
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
    // Spectral cache: one RGBAlbedoSpectrum per texel, built eagerly in setData().
    std::vector<astroray::RGBAlbedoSpectrum> spectral_cache_;
public:
    void setData(const std::vector<Vec3>& d, int w, int h) {
        data = d; width = w; height = h;
        spectral_cache_.resize(data.size());
        for (size_t i = 0; i < data.size(); ++i) {
            const Vec3& c = data[i];
            spectral_cache_[i] = astroray::RGBAlbedoSpectrum({c.x, c.y, c.z});
        }
    }
    // pkg186 — read-only accessors so the GPU scene-upload (scene_upload.cu) can
    // bake this image into a device buffer. The device sampler mirrors value()'s
    // nearest-neighbour clamp+v-flip exactly (see gpu_sampleImageTexture).
    int getWidth()  const { return width; }
    int getHeight() const { return height; }
    const std::vector<Vec3>& getData() const { return data; }
    Vec3 value(const Vec2& uv, const Vec3&) const override {
        if (data.empty()) return Vec3(1, 0, 1);
        float u = std::clamp(uv.u, 0.0f, 1.0f);
        float v = 1 - std::clamp(uv.v, 0.0f, 1.0f);
        int i = std::min((int)(u * width), width - 1);
        int j = std::min((int)(v * height), height - 1);
        return data[j * width + i];
    }
    astroray::SampledSpectrum sampleSpectral(
            const Vec2& uv, const Vec3&,
            const astroray::SampledWavelengths& lambdas) const override {
        if (spectral_cache_.empty()) {
            Vec3 rgb = value(uv, Vec3(0));
            return astroray::RGBAlbedoSpectrum({rgb.x, rgb.y, rgb.z}).sample(lambdas);
        }
        float u = std::clamp(uv.u, 0.0f, 1.0f);
        float v = 1 - std::clamp(uv.v, 0.0f, 1.0f);
        int i = std::min((int)(u * width), width - 1);
        int j = std::min((int)(v * height), height - 1);
        return spectral_cache_[j * width + i].sample(lambdas);
    }
};

// ============================================================================
// pkg219b — ProgramTexture: a per-texel op-VM chain wrapping input textures.
//
// Holds up to VM_MAX_TEX child textures + a compiled ShaderVMProgram. The
// program transforms the sampled child RGBs into the final base colour (Color
// Ramp / Mix / Math / Map Range downstream of a texture). Coord-mode + Mapping
// live on the ProgramTexture itself (the base Texture machinery), so children
// are plain samplers evaluated at the resolved (uv, p). The GPU twin runs the
// SAME svm_eval on the sampled image colour, so parity is by construction.
// ============================================================================
class ProgramTexture : public Texture {
    std::vector<std::shared_ptr<Texture>> inputs_;
    astroray::svm::ShaderVMProgram program_;
public:
    void setProgram(const astroray::svm::ShaderVMProgram& p) { program_ = p; }
    void addInput(const std::shared_ptr<Texture>& t) { inputs_.push_back(t); }
    const astroray::svm::ShaderVMProgram& getProgram() const { return program_; }
    size_t numInputs() const { return inputs_.size(); }
    std::shared_ptr<Texture> getInput(size_t i) const { return inputs_[i]; }

    Vec3 value(const Vec2& uv, const Vec3& p) const override {
        GVec3 in[astroray::svm::VM_MAX_TEX];
        int nt = program_.numTex;
        if (nt > astroray::svm::VM_MAX_TEX) nt = astroray::svm::VM_MAX_TEX;
        for (int i = 0; i < nt; ++i) {
            Vec3 c = i < (int)inputs_.size() ? inputs_[i]->value(uv, p) : Vec3(0.f);
            in[i] = GVec3(c.x, c.y, c.z);
        }
        GVec3 r = astroray::svm::svm_eval(program_, in);
        return Vec3(r.x, r.y, r.z);
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
        // pkg115 parity fixes per Cycles intern/cycles/kernel/svm/gradient.h::svm_gradient (Apache-2.0).
        Vec3 sp = p * scale;
        float t = 0;
        switch (gradType) {
            case 1: { // quadratic: max(x,0)², then saturate
                float r = std::max(sp.x, 0.0f);
                t = r * r;
                break;
            }
            case 2: { // easing: clamp then r²(3-2r)
                float r = std::clamp(sp.x, 0.0f, 1.0f);
                float t2 = r * r;
                t = 3.0f * t2 - 2.0f * t2 * r;
                break;
            }
            case 3: // diagonal: (x+y)·0.5
                t = (sp.x + sp.y) * 0.5f;
                break;
            case 4: { // spherical: max(0.999999 - len, 0) — inverted from engine (was increasing)
                float len = std::sqrt(sp.x*sp.x + sp.y*sp.y + sp.z*sp.z);
                t = std::max(0.999999f - len, 0.0f);
                break;
            }
            case 5: { // quadratic sphere: (max(0.999999 - len, 0))² — was 1-r²
                float len = std::sqrt(sp.x*sp.x + sp.y*sp.y + sp.z*sp.z);
                float r = std::max(0.999999f - len, 0.0f);
                t = r * r;
                break;
            }
            case 6: // radial: atan2(y,x)/2π + 0.5 — was +1.0 then fmod (half-turn phase offset)
                t = std::atan2(sp.y, sp.x) / (2.0f * float(M_PI)) + 0.5f;
                break;
            default: // linear: x (saturate applied after switch)
                t = sp.x;
                break;
        }
        t = std::clamp(t, 0.0f, 1.0f);  // Blender applies saturate at the end
        return color1 * (1.0f - t) + color2 * t;
    }
};

// --- Wave texture ---
// Ported from Blender intern/cycles/kernel/svm/wave.h (Apache-2.0).
// SPDX-FileCopyrightText: 2011-2022 Blender Foundation
// SPDX-License-Identifier: Apache-2.0
//
// pkg115 chunk 3: full parity with Blender/Cycles Wave node.
// wave_type: 0=Bands, 1=Rings
// bands_direction: 0=X, 1=Y, 2=Z, 3=Diagonal
// rings_direction: 0=X, 1=Y, 2=Z, 3=Spherical
// profile: 0=Sine, 1=Saw, 2=Triangle
// NOTE (pkg115 chunk 3): the hash/perlin/fractal namespaces are defined
// ABOVE WaveTexture because the Cycles Wave port consumes
// fractal_noise::noise_fbm for its detail distortion.
namespace cycles_hash {

inline uint32_t rot(uint32_t x, int k) {
    return (x << k) | (x >> (32 - k));
}

#define HASH_MIX(a, b, c) \
    do { \
        a -= c; a ^= rot(c, 4); c += b; \
        b -= a; b ^= rot(a, 6); a += c; \
        c -= b; c ^= rot(b, 8); b += a; \
        a -= c; a ^= rot(c, 16); c += b; \
        b -= a; b ^= rot(a, 19); a += c; \
        c -= b; c ^= rot(b, 4); b += a; \
    } while(0)

#define HASH_FINAL(a, b, c) \
    do { \
        c ^= b; c -= rot(b, 14); \
        a ^= c; a -= rot(c, 11); \
        b ^= a; b -= rot(a, 25); \
        c ^= b; c -= rot(b, 16); \
        a ^= c; a -= rot(c, 4); \
        b ^= a; b -= rot(a, 14); \
        c ^= b; c -= rot(b, 24); \
    } while(0)

inline uint32_t hash_uint(uint32_t kx) {
    uint32_t a, b, c;
    a = b = c = 0xdeadbeefu + (1u << 2) + 13u;
    a += kx;
    HASH_FINAL(a, b, c);
    return c;
}

inline uint32_t hash_uint2(uint32_t kx, uint32_t ky) {
    uint32_t a, b, c;
    a = b = c = 0xdeadbeefu + (2u << 2) + 13u;
    b += ky;
    a += kx;
    HASH_FINAL(a, b, c);
    return c;
}

inline uint32_t hash_uint3(uint32_t kx, uint32_t ky, uint32_t kz) {
    uint32_t a, b, c;
    a = b = c = 0xdeadbeefu + (3u << 2) + 13u;
    c += kz;
    b += ky;
    a += kx;
    HASH_FINAL(a, b, c);
    return c;
}

inline uint32_t hash_uint4(uint32_t kx, uint32_t ky, uint32_t kz, uint32_t kw) {
    uint32_t a, b, c;
    a = b = c = 0xdeadbeefu + (4u << 2) + 13u;
    a += kx;
    b += ky;
    c += kz;
    HASH_MIX(a, b, c);
    a += kw;
    HASH_FINAL(a, b, c);
    return c;
}

inline float uint_to_float_incl(uint32_t n) {
    return (float)n * (1.0f / (float)0xFFFFFFFFu);
}

inline uint32_t float_as_uint(float f) {
    union { float f; uint32_t u; } conv;
    conv.f = f;
    return conv.u;
}

inline float hash_uint_to_float(uint32_t kx) {
    return uint_to_float_incl(hash_uint(kx));
}

inline float hash_uint2_to_float(uint32_t kx, uint32_t ky) {
    return uint_to_float_incl(hash_uint2(kx, ky));
}

inline float hash_uint3_to_float(uint32_t kx, uint32_t ky, uint32_t kz) {
    return uint_to_float_incl(hash_uint3(kx, ky, kz));
}

inline float hash_uint4_to_float(uint32_t kx, uint32_t ky, uint32_t kz, uint32_t kw) {
    return uint_to_float_incl(hash_uint4(kx, ky, kz, kw));
}

inline float hash_float_to_float(float k) {
    return hash_uint_to_float(float_as_uint(k));
}

inline float hash_float2_to_float(float kx, float ky) {
    return hash_uint2_to_float(float_as_uint(kx), float_as_uint(ky));
}

inline float hash_float3_to_float(float kx, float ky, float kz) {
    return hash_uint3_to_float(float_as_uint(kx), float_as_uint(ky), float_as_uint(kz));
}

inline float hash_float4_to_float(float kx, float ky, float kz, float kw) {
    return hash_uint4_to_float(float_as_uint(kx), float_as_uint(ky), float_as_uint(kz), float_as_uint(kw));
}

// PCG3D hash for int3 -> float3 (required by Voronoi cell colors).
// Cycles util/hash.h hash_pcg3d_i (Apache-2.0). NOTE: Cycles runs this on
// SIGNED int3, so the >>16 is an ARITHMETIC shift — emulate it by casting
// through int32_t for the shift only (all other arithmetic stays unsigned
// for defined wraparound). pkg98 review: the logical-shift version diverged
// bit-wise for negative intermediates.
inline uint32_t pcg_xorshift_signed16(uint32_t v) {
    return v ^ (uint32_t)(((int32_t)v) >> 16);
}

inline Vec3 hash_int3_to_float3(int ix, int iy, int iz) {
    uint32_t vx = (uint32_t)ix;
    uint32_t vy = (uint32_t)iy;
    uint32_t vz = (uint32_t)iz;
    vx = vx * 1664525u + 1013904223u;
    vy = vy * 1664525u + 1013904223u;
    vz = vz * 1664525u + 1013904223u;
    vx += vy * vz;
    vy += vz * vx;
    vz += vx * vy;
    vx = pcg_xorshift_signed16(vx);
    vy = pcg_xorshift_signed16(vy);
    vz = pcg_xorshift_signed16(vz);
    vx += vy * vz;
    vy += vz * vx;
    vz += vx * vy;
    vx = vx & 0x7FFFFFFFu;
    vy = vy & 0x7FFFFFFFu;
    vz = vz & 0x7FFFFFFFu;
    return Vec3((float)vx * (1.0f / (float)0x7FFFFFFFu),
                (float)vy * (1.0f / (float)0x7FFFFFFFu),
                (float)vz * (1.0f / (float)0x7FFFFFFFu));
}

inline Vec3 hash_float3_to_float3(float kx, float ky, float kz) {
    return Vec3(hash_float3_to_float(kx, ky, kz),
                hash_float4_to_float(kx, ky, kz, 1.0f),
                hash_float4_to_float(kx, ky, kz, 2.0f));
}

}  // namespace cycles_hash

// ============================================================================
// PERLIN NOISE CORE (pkg115 chunk 2)
// ============================================================================
// Ported from Blender intern/cycles/kernel/svm/noise.h (BSD-3-Clause).
// SPDX-FileCopyrightText: 2009-2010 Sony Pictures Imageworks Inc., et al.
// SPDX-FileCopyrightText: 2011-2022 Blender Foundation
// SPDX-License-Identifier: BSD-3-Clause
// Adapted code from Open Shading Language.

namespace perlin_noise {

inline float floorfrac(float x, int* i) {
    *i = (int)std::floor(x);
    return x - (float)(*i);
}

inline float negate_if(float val, int condition) {
    return condition ? -val : val;
}

inline float fade(float t) {
    return t * t * t * (t * (t * 6.0f - 15.0f) + 10.0f);
}

inline float grad3(int hash, float x, float y, float z) {
    int h = hash & 15;
    float u = (h < 8) ? x : y;
    float vt = ((h == 12) || (h == 14)) ? x : z;
    float v = (h < 4) ? y : vt;
    return negate_if(u, h & 1) + negate_if(v, h & 2);
}

inline float tri_mix(float v0, float v1, float v2, float v3,
                     float v4, float v5, float v6, float v7,
                     float x, float y, float z) {
    float x1 = 1.0f - x;
    float y1 = 1.0f - y;
    float z1 = 1.0f - z;
    return z1 * (y1 * (v0 * x1 + v1 * x) + y * (v2 * x1 + v3 * x)) +
           z * (y1 * (v4 * x1 + v5 * x) + y * (v6 * x1 + v7 * x));
}

inline float perlin_3d(float x, float y, float z) {
    int X, Y, Z;
    float fx = floorfrac(x, &X);
    float fy = floorfrac(y, &Y);
    float fz = floorfrac(z, &Z);
    float u = fade(fx);
    float v = fade(fy);
    float w = fade(fz);
    using cycles_hash::hash_uint3;
    float r = tri_mix(
        grad3(hash_uint3(X, Y, Z), fx, fy, fz),
        grad3(hash_uint3(X + 1, Y, Z), fx - 1.0f, fy, fz),
        grad3(hash_uint3(X, Y + 1, Z), fx, fy - 1.0f, fz),
        grad3(hash_uint3(X + 1, Y + 1, Z), fx - 1.0f, fy - 1.0f, fz),
        grad3(hash_uint3(X, Y, Z + 1), fx, fy, fz - 1.0f),
        grad3(hash_uint3(X + 1, Y, Z + 1), fx - 1.0f, fy, fz - 1.0f),
        grad3(hash_uint3(X, Y + 1, Z + 1), fx, fy - 1.0f, fz - 1.0f),
        grad3(hash_uint3(X + 1, Y + 1, Z + 1), fx - 1.0f, fy - 1.0f, fz - 1.0f),
        u, v, w);
    return r;
}

inline float noise_scale3(float result) {
    return 0.9820f * result;
}

inline float snoise_3d(Vec3 p) {
    // Precision guard per Cycles noise.h:725-736.
    const float precision_limit = 1000000.0f;
    Vec3 correction(0.0f);
    if (std::abs(p.x) >= precision_limit) correction.x = 0.5f;
    if (std::abs(p.y) >= precision_limit) correction.y = 0.5f;
    if (std::abs(p.z) >= precision_limit) correction.z = 0.5f;
    p.x = std::fmod(p.x, 100000.0f) + correction.x;
    p.y = std::fmod(p.y, 100000.0f) + correction.y;
    p.z = std::fmod(p.z, 100000.0f) + correction.z;
    return noise_scale3(perlin_3d(p.x, p.y, p.z));
}

inline float noise_3d(Vec3 p) {
    return 0.5f * snoise_3d(p) + 0.5f;
}

}  // namespace perlin_noise

// ============================================================================
// FRACTAL NOISE STACK (pkg115 chunk 2)
// ============================================================================
// Ported from Blender intern/cycles/kernel/svm/fractal_noise.h (Apache-2.0).
// SPDX-FileCopyrightText: 2011-2022 Blender Foundation
// SPDX-License-Identifier: Apache-2.0

namespace fractal_noise {

using perlin_noise::snoise_3d;

inline float noise_fbm(Vec3 p, float detail, float roughness, float lacunarity, bool normalize) {
    float fscale = 1.0f;
    float amp = 1.0f;
    float maxamp = 0.0f;
    float sum = 0.0f;
    int octaves = (int)detail;
    for (int i = 0; i <= octaves; i++) {
        float t = snoise_3d(p * fscale);
        sum += t * amp;
        maxamp += amp;
        amp *= roughness;
        fscale *= lacunarity;
    }
    float rmd = detail - std::floor(detail);
    if (rmd != 0.0f) {
        float t = snoise_3d(p * fscale);
        float sum2 = sum + t * amp;
        float result = normalize ?
            (0.5f * sum / maxamp + 0.5f) * (1.0f - rmd) + (0.5f * sum2 / (maxamp + amp) + 0.5f) * rmd :
            sum * (1.0f - rmd) + sum2 * rmd;
        return result;
    }
    return normalize ? 0.5f * sum / maxamp + 0.5f : sum;
}

inline float noise_multi_fractal(Vec3 p, float detail, float roughness, float lacunarity) {
    float value = 1.0f;
    float pwr = 1.0f;
    int octaves = (int)detail;
    for (int i = 0; i <= octaves; i++) {
        value *= (pwr * snoise_3d(p) + 1.0f);
        pwr *= roughness;
        p = p * lacunarity;
    }
    float rmd = detail - std::floor(detail);
    if (rmd != 0.0f) {
        value *= (rmd * pwr * snoise_3d(p) + 1.0f);
    }
    return value;
}

inline float noise_hetero_terrain(Vec3 p, float detail, float roughness, float lacunarity, float offset) {
    float pwr = roughness;
    float value = offset + snoise_3d(p);
    p = p * lacunarity;
    int octaves = (int)detail;
    for (int i = 1; i <= octaves; i++) {
        float increment = (snoise_3d(p) + offset) * pwr * value;
        value += increment;
        pwr *= roughness;
        p = p * lacunarity;
    }
    float rmd = detail - std::floor(detail);
    if (rmd != 0.0f) {
        float increment = (snoise_3d(p) + offset) * pwr * value;
        value += rmd * increment;
    }
    return value;
}

inline float noise_hybrid_multi_fractal(Vec3 p, float detail, float roughness,
                                        float lacunarity, float offset, float gain) {
    float pwr = 1.0f;
    float value = 0.0f;
    float weight = 1.0f;
    int octaves = (int)detail;
    for (int i = 0; (weight > 0.001f) && (i <= octaves); i++) {
        weight = std::min(weight, 1.0f);
        float signal = (snoise_3d(p) + offset) * pwr;
        pwr *= roughness;
        value += weight * signal;
        weight *= gain * signal;
        p = p * lacunarity;
    }
    float rmd = detail - std::floor(detail);
    if ((rmd != 0.0f) && (weight > 0.001f)) {
        weight = std::min(weight, 1.0f);
        float signal = (snoise_3d(p) + offset) * pwr;
        value += rmd * weight * signal;
    }
    return value;
}

inline float noise_ridged_multi_fractal(Vec3 p, float detail, float roughness,
                                        float lacunarity, float offset, float gain) {
    float pwr = roughness;
    float signal = offset - std::abs(snoise_3d(p));
    signal *= signal;
    float value = signal;
    float weight = 1.0f;
    int octaves = (int)detail;
    for (int i = 1; i <= octaves; i++) {
        p = p * lacunarity;
        weight = std::clamp(signal * gain, 0.0f, 1.0f);
        signal = offset - std::abs(snoise_3d(p));
        signal *= signal;
        signal *= weight;
        value += signal * pwr;
        pwr *= roughness;
    }
    return value;
}

}  // namespace fractal_noise

// ============================================================================
// WHITE NOISE TEXTURE (pkg115 chunk 2)
// ============================================================================

class WaveTexture : public Texture {
    int waveType;           // 0=bands, 1=rings
    int bandsDirection;     // 0=X, 1=Y, 2=Z, 3=Diagonal
    int ringsDirection;     // 0=X, 1=Y, 2=Z, 3=Spherical
    int profile;            // 0=sine, 1=saw, 2=triangle
    float scale, distortion, detail, detailScale, detailRoughness, phaseOffset;
    Vec3 colorLow, colorHigh;
public:
    WaveTexture(int wt = 0, int bd = 0, int rd = 0, int prof = 0,
                float sc = 5.0f, float dist = 0.0f, float det = 2.0f,
                float dscale = 1.0f, float drough = 0.5f, float phase = 0.0f,
                const Vec3& c1 = Vec3(0), const Vec3& c2 = Vec3(1))
        : waveType(wt), bandsDirection(bd), ringsDirection(rd), profile(prof),
          scale(sc), distortion(dist), detail(det), detailScale(dscale),
          detailRoughness(drough), phaseOffset(phase), colorLow(c1), colorHigh(c2) {}

    Vec3 value(const Vec2&, const Vec3& p) const override {
        // Cycles intern/cycles/kernel/svm/wave.h::svm_wave (Apache-2.0).
        // Precision guard per Cycles.
        Vec3 pp = (p + Vec3(0.000001f)) * 0.999999f;
        pp = pp * scale;

        float n = 0.0f;
        if (waveType == 0) {
            // Bands
            switch (bandsDirection) {
                case 0: n = pp.x * 20.0f; break;  // X
                case 1: n = pp.y * 20.0f; break;  // Y
                case 2: n = pp.z * 20.0f; break;  // Z
                case 3: n = (pp.x + pp.y + pp.z) * 10.0f; break;  // Diagonal
            }
        } else {
            // Rings: zero one axis then len * 20
            Vec3 rp = pp;
            switch (ringsDirection) {
                case 0: rp.x = 0.0f; break;  // X
                case 1: rp.y = 0.0f; break;  // Y
                case 2: rp.z = 0.0f; break;  // Z
                case 3: break;  // Spherical (no zeroing)
            }
            float r = std::sqrt(rp.x*rp.x + rp.y*rp.y + rp.z*rp.z);
            n = r * 20.0f;
        }

        n += phaseOffset;

        if (distortion != 0.0f) {
            // Distortion via SIGNED fBM (lacunarity fixed 2.0, normalized).
            float distort = fractal_noise::noise_fbm(pp * detailScale, detail,
                                                     detailRoughness, 2.0f, true);
            n += distortion * (distort * 2.0f - 1.0f);
        }

        float t;
        const float pi = 3.14159265358979323846f;
        const float two_pi = 2.0f * pi;
        switch (profile) {
            case 1: {  // Saw
                float frac = n / two_pi;
                t = frac - std::floor(frac);
                break;
            }
            case 2: {  // Triangle
                float frac = n / two_pi;
                t = std::abs(frac - std::floor(frac + 0.5f)) * 2.0f;
                break;
            }
            default: {  // Sine
                t = 0.5f + 0.5f * std::sin(n - pi / 2.0f);
                break;
            }
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
        // pkg115 parity fix: verbatim port of Cycles intern/cycles/kernel/svm/magic.h::svm_magic (Apache-2.0).
        // Key differences from old engine math: fmod(p·scale, 2π) then ·5 (not scale·π),
        // *= distortion per branch + final /= (2·distortion), depth ≤ 10 (was 5),
        // output is true RGB (0.5-x, 0.5-y, 0.5-z), not a scalar 2-color lerp.
        // Keep color1/color2 params for backward compat with standalone factory calls;
        // addon passes (0,0,0)/(1,1,1) so this becomes a tint.
        float px = std::fmod(p.x * scale, 2.0f * float(M_PI));
        float py = std::fmod(p.y * scale, 2.0f * float(M_PI));
        float pz = std::fmod(p.z * scale, 2.0f * float(M_PI));
        float x = std::sin((px + py + pz) * 5.0f);
        float y = std::cos((-px + py - pz) * 5.0f);
        float z = -std::cos((-px - py + pz) * 5.0f);
        int n = turbDepth;
        float dist = distortion;
        if (n > 0) {
            x *= dist; y *= dist; z *= dist;
            y = -std::cos(x - y + z);
            y *= dist;
            if (n > 1) {
                x = std::cos(x - y - z);
                x *= dist;
                if (n > 2) {
                    z = std::sin(-x - y - z);
                    z *= dist;
                    if (n > 3) {
                        x = -std::cos(-x + y - z);
                        x *= dist;
                        if (n > 4) {
                            y = -std::sin(-x + y + z);
                            y *= dist;
                            if (n > 5) {
                                y = -std::cos(-x + y + z);
                                y *= dist;
                                if (n > 6) {
                                    x = std::cos(x + y + z);
                                    x *= dist;
                                    if (n > 7) {
                                        z = std::sin(x + y - z);
                                        z *= dist;
                                        if (n > 8) {
                                            x = -std::cos(-x - y + z);
                                            x *= dist;
                                            if (n > 9) {
                                                y = -std::sin(x - y + z);
                                                y *= dist;
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        if (dist != 0.0f) {
            dist *= 2.0f;
            x /= dist;
            y /= dist;
            z /= dist;
        }
        // Cycles svm_node_tex_magic: the Color socket carries the raw float3
        // (0.5-x, 0.5-y, 0.5-z); Fac is its average. Reproduce the float3 with
        // color1/color2 as a PER-CHANNEL lerp tint for standalone factory
        // callers (the addon passes black/white, making this the identity).
        // pkg115 residual fix: the previous code collapsed the float3 to its
        // average, rendering Magic greyscale instead of Cycles' colored swirls.
        Vec3 rgb(0.5f - x, 0.5f - y, 0.5f - z);
        return Vec3(color1.x + (color2.x - color1.x) * rgb.x,
                    color1.y + (color2.y - color1.y) * rgb.y,
                    color1.z + (color2.z - color1.z) * rgb.z);
    }
};

// --- Voronoi texture ---
// Ported from Blender intern/cycles/kernel/svm/voronoi.h (Apache-2.0).
// SPDX-FileCopyrightText: 2011-2022 Blender Foundation
// SPDX-License-Identifier: Apache-2.0
//
// SPDX-License-Identifier: MIT
// Original code is copyright (c) 2013 Inigo Quilez.
// Smooth Voronoi and Distance-to-Edge formulas from:
//   https://www.iquilezles.org/www/articles/voronoilines/voronoilines.htm
//
// pkg115 chunk 4: full parity with Blender/Cycles Voronoi node.
// Distance metrics: Euclidean / Manhattan / Chebychev / Minkowski(exponent param).
// Features (Blender order): 0=F1, 1=Smooth F1, 2=F2, 3=Distance to Edge, 4=N-Sphere Radius.
// Standalone-only legacy features: 5=F1+F2, 6=F2-F1.
// Fractal: detail, roughness, lacunarity. Normalize divides by max_amplitude * max_distance.
// Hash: uses cycles_hash::hash_int3_to_float3 (ported in chunk 2) for identical pattern to Cycles.
//
// VoronoiOutput: distance, color (cell hash RGB), position (jittered cell center).
struct VoronoiOutput {
    float distance;
    Vec3 color;
    Vec3 position;
    float radius;  // N-Sphere Radius feature only
};

class VoronoiTexture : public Texture {
    float scale, detail, roughness, lacunarity, smoothness, exponent, randomness;
    float maxDistance;  // computed from randomness and feature
    bool normalize;
    int distMetric, feature;
    Vec3 colorLow, colorHigh;

    // Cycles voronoi.h:57-72 distance metrics.
    float voronoi_distance(const Vec3& a, const Vec3& b) const {
        Vec3 d = a - b;
        switch (distMetric) {
            case 1: return std::abs(d.x) + std::abs(d.y) + std::abs(d.z);  // Manhattan
            case 2: return std::max({std::abs(d.x), std::abs(d.y), std::abs(d.z)});  // Chebychev
            case 3: {  // Minkowski with exponent param (default 0.5)
                float sum = std::pow(std::abs(d.x), exponent) +
                            std::pow(std::abs(d.y), exponent) +
                            std::pow(std::abs(d.z), exponent);
                return std::pow(sum, 1.0f / exponent);
            }
            default: return std::sqrt(d.dot(d));  // Euclidean
        }
    }

    // Cycles voronoi.h:479-510 voronoi_f1 3D.
    VoronoiOutput voronoi_f1(const Vec3& coord) const {
        Vec3 cellPositionF = Vec3(std::floor(coord.x), std::floor(coord.y), std::floor(coord.z));
        Vec3 localPosition = coord - cellPositionF;

        float minDistance = 1e9f;
        Vec3 targetOffset(0.0f);
        Vec3 targetPosition(0.0f);

        for (int k = -1; k <= 1; ++k) {
            for (int j = -1; j <= 1; ++j) {
                for (int i = -1; i <= 1; ++i) {
                    Vec3 cellOffset((float)i, (float)j, (float)k);
                    Vec3 cellPos((int)cellPositionF.x + i, (int)cellPositionF.y + j, (int)cellPositionF.z + k);
                    Vec3 pointPosition = cellOffset +
                        cycles_hash::hash_int3_to_float3((int)cellPos.x, (int)cellPos.y, (int)cellPos.z) * randomness;
                    float d = voronoi_distance(pointPosition, localPosition);
                    if (d < minDistance) {
                        minDistance = d;
                        targetOffset = cellOffset;
                        targetPosition = pointPosition;
                    }
                }
            }
        }

        VoronoiOutput out;
        out.distance = minDistance;
        Vec3 targetCell = cellPositionF + targetOffset;
        out.color = cycles_hash::hash_int3_to_float3((int)targetCell.x, (int)targetCell.y, (int)targetCell.z);
        out.position = targetPosition + cellPositionF;
        out.radius = 0.0f;
        return out;
    }

    // Cycles voronoi.h:512-552 voronoi_smooth_f1 3D (5x5x5 neighborhood, polynomial smooth-min).
    VoronoiOutput voronoi_smooth_f1(const Vec3& coord) const {
        Vec3 cellPositionF = Vec3(std::floor(coord.x), std::floor(coord.y), std::floor(coord.z));
        Vec3 localPosition = coord - cellPositionF;

        float smoothDistance = 1e9f;
        Vec3 smoothColor(0.0f);
        Vec3 smoothPosition(0.0f);
        float h = -1.0f;

        for (int k = -2; k <= 2; ++k) {
            for (int j = -2; j <= 2; ++j) {
                for (int i = -2; i <= 2; ++i) {
                    Vec3 cellOffset((float)i, (float)j, (float)k);
                    Vec3 cellPos((int)cellPositionF.x + i, (int)cellPositionF.y + j, (int)cellPositionF.z + k);
                    Vec3 pointPosition = cellOffset +
                        cycles_hash::hash_int3_to_float3((int)cellPos.x, (int)cellPos.y, (int)cellPos.z) * randomness;
                    float d = voronoi_distance(pointPosition, localPosition);
                    Vec3 cellColor = cycles_hash::hash_int3_to_float3((int)cellPos.x, (int)cellPos.y, (int)cellPos.z);

                    h = (h == -1.0f) ? 1.0f :
                        std::clamp(0.5f + 0.5f * (smoothDistance - d) / smoothness, 0.0f, 1.0f);
                    h = h * h * (3.0f - 2.0f * h);  // smoothstep
                    float correction = smoothness * h * (1.0f - h);
                    smoothDistance = smoothDistance * (1.0f - h) + d * h - correction;
                    correction /= 1.0f + 3.0f * smoothness;
                    smoothColor = smoothColor * (1.0f - h) + cellColor * h - Vec3(correction);
                    smoothPosition = smoothPosition * (1.0f - h) + pointPosition * h - Vec3(correction);
                }
            }
        }

        VoronoiOutput out;
        out.distance = smoothDistance;
        out.color = smoothColor;
        out.position = smoothPosition + cellPositionF;
        out.radius = 0.0f;
        return out;
    }

    // Cycles voronoi.h:553-596 voronoi_f2 3D (two nearest).
    VoronoiOutput voronoi_f2(const Vec3& coord) const {
        Vec3 cellPositionF = Vec3(std::floor(coord.x), std::floor(coord.y), std::floor(coord.z));
        Vec3 localPosition = coord - cellPositionF;

        float dist1 = 1e9f, dist2 = 1e9f;
        Vec3 offset1(0.0f), offset2(0.0f);
        Vec3 position1(0.0f), position2(0.0f);

        for (int k = -1; k <= 1; ++k) {
            for (int j = -1; j <= 1; ++j) {
                for (int i = -1; i <= 1; ++i) {
                    Vec3 cellOffset((float)i, (float)j, (float)k);
                    Vec3 cellPos((int)cellPositionF.x + i, (int)cellPositionF.y + j, (int)cellPositionF.z + k);
                    Vec3 pointPosition = cellOffset +
                        cycles_hash::hash_int3_to_float3((int)cellPos.x, (int)cellPos.y, (int)cellPos.z) * randomness;
                    float d = voronoi_distance(pointPosition, localPosition);

                    if (d < dist1) {
                        dist2 = dist1; offset2 = offset1; position2 = position1;
                        dist1 = d; offset1 = cellOffset; position1 = pointPosition;
                    } else if (d < dist2) {
                        dist2 = d; offset2 = cellOffset; position2 = pointPosition;
                    }
                }
            }
        }

        VoronoiOutput out;
        out.distance = dist2;
        Vec3 cell2 = cellPositionF + offset2;
        out.color = cycles_hash::hash_int3_to_float3((int)cell2.x, (int)cell2.y, (int)cell2.z);
        out.position = position2 + cellPositionF;
        out.radius = 0.0f;
        return out;
    }

    // Cycles voronoi.h:597+ voronoi_distance_to_edge 3D (IQ two-pass perpendicular edge distance).
    // Both passes work in vectors RELATIVE to localPosition (vectorToPoint = pointPosition -
    // localPosition), matching Cycles. First pass uses squared Euclidean and IGNORES the metric.
    // Edge distance = dot((vectorToClosest + vectorToPoint)/2, normalize(perpendicularToEdge)).
    VoronoiOutput voronoi_distance_to_edge(const Vec3& coord) const {
        Vec3 cellPositionF = Vec3(std::floor(coord.x), std::floor(coord.y), std::floor(coord.z));
        Vec3 localPosition = coord - cellPositionF;

        float minDistance = 1e9f;
        Vec3 targetOffset(0.0f);
        Vec3 vectorToClosest(0.0f);

        // First pass: find closest point (squared Euclidean, metric ignored per Cycles).
        for (int k = -1; k <= 1; ++k) {
            for (int j = -1; j <= 1; ++j) {
                for (int i = -1; i <= 1; ++i) {
                    Vec3 cellOffset((float)i, (float)j, (float)k);
                    Vec3 cellPos((int)cellPositionF.x + i, (int)cellPositionF.y + j, (int)cellPositionF.z + k);
                    Vec3 vectorToPoint = cellOffset +
                        cycles_hash::hash_int3_to_float3((int)cellPos.x, (int)cellPos.y, (int)cellPos.z) * randomness
                        - localPosition;
                    float d = vectorToPoint.dot(vectorToPoint);
                    if (d < minDistance) {
                        minDistance = d;
                        targetOffset = cellOffset;
                        vectorToClosest = vectorToPoint;
                    }
                }
            }
        }

        // Second pass: perpendicular distance to the edge between closest and neighbor.
        minDistance = 1e9f;
        for (int k = -1; k <= 1; ++k) {
            for (int j = -1; j <= 1; ++j) {
                for (int i = -1; i <= 1; ++i) {
                    Vec3 cellOffset((float)i, (float)j, (float)k);
                    Vec3 cellPos((int)cellPositionF.x + i, (int)cellPositionF.y + j, (int)cellPositionF.z + k);
                    Vec3 vectorToPoint = cellOffset +
                        cycles_hash::hash_int3_to_float3((int)cellPos.x, (int)cellPos.y, (int)cellPos.z) * randomness
                        - localPosition;
                    Vec3 perpendicularToEdge = vectorToPoint - vectorToClosest;
                    if (perpendicularToEdge.dot(perpendicularToEdge) > 1e-4f) {
                        Vec3 perpN = perpendicularToEdge /
                            std::sqrt(perpendicularToEdge.dot(perpendicularToEdge));
                        float d = ((vectorToClosest + vectorToPoint) * 0.5f).dot(perpN);
                        minDistance = std::min(minDistance, d);
                    }
                }
            }
        }

        VoronoiOutput out;
        out.distance = minDistance;
        Vec3 targetCell = cellPositionF + targetOffset;
        out.color = cycles_hash::hash_int3_to_float3((int)targetCell.x, (int)targetCell.y, (int)targetCell.z);
        out.position = vectorToClosest + localPosition + cellPositionF;
        out.radius = 0.0f;
        return out;
    }

    // Cycles voronoi.h:645+ voronoi_n_sphere_radius 3D (half distance between closest point and its closest neighbor).
    VoronoiOutput voronoi_n_sphere_radius(const Vec3& coord) const {
        Vec3 cellPositionF = Vec3(std::floor(coord.x), std::floor(coord.y), std::floor(coord.z));
        Vec3 localPosition = coord - cellPositionF;

        float minDistance = 1e9f;
        Vec3 targetOffset(0.0f);
        Vec3 targetPosition(0.0f);

        // First pass: find closest point.
        for (int k = -1; k <= 1; ++k) {
            for (int j = -1; j <= 1; ++j) {
                for (int i = -1; i <= 1; ++i) {
                    Vec3 cellOffset((float)i, (float)j, (float)k);
                    Vec3 cellPos((int)cellPositionF.x + i, (int)cellPositionF.y + j, (int)cellPositionF.z + k);
                    Vec3 pointPosition = cellOffset +
                        cycles_hash::hash_int3_to_float3((int)cellPos.x, (int)cellPos.y, (int)cellPos.z) * randomness;
                    float d = voronoi_distance(pointPosition, localPosition);
                    if (d < minDistance) {
                        minDistance = d;
                        targetOffset = cellOffset;
                        targetPosition = pointPosition;
                    }
                }
            }
        }

        // Second pass: find closest neighbor to the closest point.
        float closestNeighborDist = 1e9f;
        for (int k = -1; k <= 1; ++k) {
            for (int j = -1; j <= 1; ++j) {
                for (int i = -1; i <= 1; ++i) {
                    if (i == 0 && j == 0 && k == 0) continue;
                    Vec3 cellOffset((float)i, (float)j, (float)k);
                    Vec3 cellPos((int)cellPositionF.x + (int)targetOffset.x + i,
                                 (int)cellPositionF.y + (int)targetOffset.y + j,
                                 (int)cellPositionF.z + (int)targetOffset.z + k);
                    Vec3 pointPosition = cellOffset +
                        cycles_hash::hash_int3_to_float3((int)cellPos.x, (int)cellPos.y, (int)cellPos.z) * randomness;
                    float d = voronoi_distance(Vec3(0.0f), pointPosition);
                    closestNeighborDist = std::min(closestNeighborDist, d);
                }
            }
        }

        VoronoiOutput out;
        out.distance = minDistance;
        Vec3 targetCell = cellPositionF + targetOffset;
        out.color = cycles_hash::hash_int3_to_float3((int)targetCell.x, (int)targetCell.y, (int)targetCell.z);
        out.position = targetPosition + cellPositionF;
        out.radius = closestNeighborDist / 2.0f;
        return out;
    }

    // Cycles voronoi.h:940-992 fractal_voronoi_x_fx (octave loop with normalize).
    VoronoiOutput fractal_voronoi(const Vec3& coord) const {
        float octaveScale = 1.0f;  // accumulated per-octave scale (member `scale` is params.scale)
        float amplitude = 1.0f;
        float maxAmplitude = 0.0f;
        VoronoiOutput sum;
        sum.distance = 0.0f;
        sum.color = Vec3(0.0f);
        sum.position = Vec3(0.0f);
        sum.radius = 0.0f;

        int octaves = (int)std::ceil(detail);
        for (int i = 0; i <= octaves; ++i) {
            VoronoiOutput octave;
            switch (feature) {
                case 1: octave = voronoi_smooth_f1(coord * octaveScale); break;
                case 2: octave = voronoi_f2(coord * octaveScale); break;
                case 3: octave = voronoi_distance_to_edge(coord * octaveScale); break;
                case 4: octave = voronoi_n_sphere_radius(coord * octaveScale); break;
                default: octave = voronoi_f1(coord * octaveScale); break;
            }

            if (i <= (int)detail) {
                sum.distance += octave.distance * amplitude;
                sum.color = sum.color + octave.color * amplitude;
                sum.position = sum.position + octave.position * amplitude;
                sum.radius += octave.radius * amplitude;
                maxAmplitude += amplitude;
            } else {
                // Fractional detail: lerp last octave.
                float rmd = detail - std::floor(detail);
                sum.distance = sum.distance * (1.0f - rmd) + (sum.distance + octave.distance * amplitude) * rmd;
                sum.color = sum.color * (1.0f - rmd) + (sum.color + octave.color * amplitude) * rmd;
                sum.position = sum.position * (1.0f - rmd) + (sum.position + octave.position * amplitude) * rmd;
                sum.radius = sum.radius * (1.0f - rmd) + (sum.radius + octave.radius * amplitude) * rmd;
                if (normalize) {
                    maxAmplitude = maxAmplitude * (1.0f - rmd) + (maxAmplitude + amplitude) * rmd;
                }
            }

            octaveScale *= lacunarity;
            amplitude *= roughness;
        }

        if (normalize) {
            sum.distance /= maxAmplitude * maxDistance;
            sum.color = sum.color / maxAmplitude;
        }
        // Cycles voronoi.h fractal_voronoi_x_fx: output.position = safe_divide(position, params.scale).
        // `scale` here is the class member (= params.scale), not the per-octave accumulator.
        sum.position = (scale != 0.0f) ? (sum.position / scale) : sum.position;
        return sum;
    }

public:
    VoronoiTexture(float sc = 5.0f, float det = 0.0f, float rough = 0.5f, float lac = 2.0f,
                   float smooth = 1.0f, float exp = 0.5f, float rand = 1.0f,
                   bool norm = false, int dm = 0, int feat = 0,
                   const Vec3& c1 = Vec3(0), const Vec3& c2 = Vec3(1))
        : scale(sc), detail(det), roughness(rough), lacunarity(lac),
          smoothness(smooth), exponent(exp), randomness(rand), normalize(norm),
          distMetric(dm), feature(feat), colorLow(c1), colorHigh(c2) {
        // Cycles voronoi.h:1065+ svm_node_tex_voronoi conditioning.
        detail = std::clamp(detail, 0.0f, 15.0f);
        roughness = std::clamp(roughness, 0.0f, 1.0f);
        randomness = std::clamp(randomness, 0.0f, 1.0f);
        smoothness = std::clamp(smoothness / 2.0f, 0.0f, 0.5f);  // Node UI passes 0-1; Cycles uses 0-0.5.

        // Compute max_distance for normalization.
        Vec3 ones(0.5f + 0.5f * randomness);
        if (feature == 3) {
            // Distance to edge.
            maxDistance = 0.5f + 0.5f * randomness;
        } else {
            maxDistance = voronoi_distance(Vec3(0.0f), ones);
            if (feature == 2) maxDistance *= 2.0f;  // F2
        }
    }

    Vec3 value(const Vec2&, const Vec3& p) const override {
        // Legacy single-output: Distance mapped to a 2-color lerp.
        VoronoiOutput out = evalFull(p);
        float t = std::clamp(out.distance, 0.0f, 1.0f);
        return colorLow * (1.0f - t) + colorHigh * t;
    }

    // Full multi-output eval for plugin use. Features 0-4 ALWAYS route through the
    // fractal wrapper -- Cycles svm_node_tex_voronoi calls fractal_voronoi_x_fx even at
    // detail=0 (single octave), so `normalize` must apply at detail=0 too. Standalone-only
    // features 5/6 (F1+F2, F2-F1) have no Cycles counterpart and bypass fractal/normalize.
    VoronoiOutput evalFull(const Vec3& p) const {
        Vec3 coord = p * scale;
        if (feature <= 4) {
            return fractal_voronoi(coord);
        }
        switch (feature) {
            case 5: {  // Standalone-only F1+F2
                VoronoiOutput f1 = voronoi_f1(coord);
                VoronoiOutput f2 = voronoi_f2(coord);
                f1.distance = (f1.distance + f2.distance) * 0.5f;
                return f1;
            }
            case 6: {  // Standalone-only F2-F1
                VoronoiOutput f1 = voronoi_f1(coord);
                VoronoiOutput f2 = voronoi_f2(coord);
                f1.distance = f2.distance - f1.distance;
                return f1;
            }
            default: return voronoi_f1(coord);
        }
    }
};

// --- Brick texture ---
// Ported from Blender intern/cycles/kernel/svm/brick.h (Apache-2.0).
// SPDX-FileCopyrightText: 2011-2022 Blender Foundation
// SPDX-License-Identifier: Apache-2.0
//
// pkg115 chunk 3: full parity with Blender/Cycles Brick node.
// 3D input (p.x, p.y), mortar_smooth, bias, per-brick color variation,
// offset_frequency, squash/squash_frequency.
class BrickTexture : public Texture {
    Vec3 color1, color2, colorMortar;
    float scale, mortarSize, mortarSmooth, bias, brickWidth, rowHeight;
    float offsetAmount, squashAmount;
    int offsetFrequency, squashFrequency;

    static inline uint32_t brick_noise(uint32_t n) {
        // Cycles intern/cycles/kernel/svm/brick.h:14-21 (Apache-2.0).
        // Integer hash for per-brick color variation.
        uint32_t nn = (n + 1013u) & 0x7fffffffu;
        nn = (nn >> 13u) ^ nn;
        uint32_t nnn = (nn * (nn * nn * 60493u + 19990303u) + 1376312589u) & 0x7fffffffu;
        return nnn;
    }

public:
    BrickTexture(const Vec3& c1 = Vec3(0.8f),
                 const Vec3& c2 = Vec3(0.2f),
                 const Vec3& mortar = Vec3(0.0f),
                 float sc = 5.0f, float mort = 0.02f, float msmooth = 0.1f,
                 float b = 0.0f, float bw = 0.5f, float rh = 0.25f,
                 float off = 0.5f, int offfreq = 2, float sq = 1.0f, int sqfreq = 2)
        : color1(c1), color2(c2), colorMortar(mortar),
          scale(sc), mortarSize(mort), mortarSmooth(msmooth), bias(b),
          brickWidth(bw), rowHeight(rh), offsetAmount(off), squashAmount(sq),
          offsetFrequency(offfreq), squashFrequency(sqfreq) {}

    Vec3 value(const Vec2&, const Vec3& p) const override {
        // Cycles intern/cycles/kernel/svm/brick.h::svm_brick (Apache-2.0).
        // 3D input: uses p.x, p.y (ignores p.z per Cycles).
        Vec3 coord = p * scale;

        int rownum = static_cast<int>(std::floor(coord.y / rowHeight));

        float brick_w = brickWidth;
        float offset = 0.0f;
        if (offsetFrequency != 0 && squashFrequency != 0) {
            brick_w *= (rownum % squashFrequency) ? 1.0f : squashAmount;
            offset = (rownum % offsetFrequency) ? 0.0f : brick_w * offsetAmount;
        }

        int bricknum = static_cast<int>(std::floor((coord.x + offset) / brick_w));

        float x = (coord.x + offset) - brick_w * bricknum;
        float y = coord.y - rowHeight * rownum;

        // Per-brick random tint: mix color1 -> color2 by (hash + bias).
        uint32_t hash_in = (static_cast<uint32_t>(rownum) << 16) + (static_cast<uint32_t>(bricknum) & 0xFFFFu);
        float tint_raw = static_cast<float>(brick_noise(hash_in)) / 2147483647.0f;
        float tint = std::clamp(tint_raw + bias, 0.0f, 1.0f);
        Vec3 brick_color = color1 * (1.0f - tint) + color2 * tint;

        // Mortar test: minimum distance to brick edge.
        float min_dist = std::min({x, y, brick_w - x, rowHeight - y});
        float mortar;
        if (min_dist >= mortarSize) {
            mortar = 0.0f;
        } else if (mortarSmooth == 0.0f) {
            mortar = 1.0f;
        } else {
            // Cycles smoothstep inversion: (1 - min_dist / mortar_size) / mortar_smooth.
            float t = (1.0f - min_dist / mortarSize) / mortarSmooth;
            t = std::clamp(t, 0.0f, 1.0f);
            mortar = t * t * (3.0f - 2.0f * t);
        }

        return brick_color * (1.0f - mortar) + colorMortar * mortar;
    }
};

// --- Musgrave (fBm) texture ---
// ============================================================================
// HASH FAMILY (pkg115 chunk 2)
// ============================================================================
// Ported from Blender intern/cycles/util/hash.h (Apache-2.0).
// SPDX-FileCopyrightText: 2011-2022 Blender Foundation
// SPDX-License-Identifier: Apache-2.0
//
// Jenkins Lookup3 hash core. Required by Perlin, Voronoi, White Noise, and
// the Noise node's random offsets. Bit-identical to Cycles for parity.

class WhiteNoiseTexture : public Texture {
public:
    WhiteNoiseTexture() = default;
    Vec3 value(const Vec2&, const Vec3& p) const override {
        // Cycles intern/cycles/kernel/svm/white_noise.h::svm_node_tex_white_noise (Apache-2.0).
        // 3D white noise: color = hash_float3_to_float3, value = hash_float3_to_float.
        return cycles_hash::hash_float3_to_float3(p.x, p.y, p.z);
    }
};

// ============================================================================
// NOISE TEXTURE (real Perlin-based, pkg115 chunk 2)
// ============================================================================
// Blender "Noise Texture" node (includes Musgrave semantics since Blender 4.1).
// Cycles intern/cycles/kernel/svm/noisetex.h (Apache-2.0).
// Default noise_type = fBM (0), normalize = true. Musgrave types map to the
// noise_type enum: 1=MULTIFRACTAL, 2=HYBRID_MULTIFRACTAL, 3=RIDGED_MULTIFRACTAL, 4=HETERO_TERRAIN.
class NoiseTextureCycles : public Texture {
    float scale, detail, roughness, lacunarity, offset, gain, distortion;
    int noise_type;  // 0=fBM, 1=multifractal, 2=hybrid, 3=ridged, 4=hetero
    bool normalize;
public:
    NoiseTextureCycles(float s = 5.0f, float det = 2.0f, float rough = 0.5f,
                       float lac = 2.0f, float off = 0.0f, float g = 1.0f,
                       float dist = 0.0f, int type = 0, bool norm = true)
        : scale(s), detail(det), roughness(rough), lacunarity(lac),
          offset(off), gain(g), distortion(dist), noise_type(type), normalize(norm) {}

    static Vec3 random_float3_offset(float seed) {
        // Cycles noisetex.h:32-37 (Apache-2.0).
        using cycles_hash::hash_float2_to_float;
        return Vec3(100.0f + hash_float2_to_float(seed, 0.0f) * 100.0f,
                    100.0f + hash_float2_to_float(seed, 1.0f) * 100.0f,
                    100.0f + hash_float2_to_float(seed, 2.0f) * 100.0f);
    }

    float noise_select(Vec3 p, float det, float rough, float lac, float off, float g, int type, bool norm) const {
        // Cycles noisetex.h:48-78 (Apache-2.0).
        using namespace fractal_noise;
        switch (type) {
            case 1: return noise_multi_fractal(p, det, rough, lac);
            case 2: return noise_hybrid_multi_fractal(p, det, rough, lac, off, g);
            case 3: return noise_ridged_multi_fractal(p, det, rough, lac, off, g);
            case 4: return noise_hetero_terrain(p, det, rough, lac, off);
            case 0:
            default:
                return noise_fbm(p, det, rough, lac, norm);
        }
    }

    Vec3 value(const Vec2&, const Vec3& p) const override {
        // Cycles noisetex.h:161-201 noise_texture_3d (Apache-2.0).
        // Clamp detail [0,15], roughness >= 0 per svm_node_tex_noise:245+.
        float det = std::clamp(detail, 0.0f, 15.0f);
        float rough = std::max(roughness, 0.0f);
        Vec3 co = p * scale;
        Vec3 distorted = co;
        if (distortion != 0.0f) {
            distorted.x += perlin_noise::snoise_3d(co + random_float3_offset(0.0f)) * distortion;
            distorted.y += perlin_noise::snoise_3d(co + random_float3_offset(1.0f)) * distortion;
            distorted.z += perlin_noise::snoise_3d(co + random_float3_offset(2.0f)) * distortion;
        }
        float fac = noise_select(distorted, det, rough, lacunarity, offset, gain, noise_type, normalize);
        float r = noise_select(distorted + random_float3_offset(3.0f), det, rough, lacunarity, offset, gain, noise_type, normalize);
        float g = noise_select(distorted + random_float3_offset(4.0f), det, rough, lacunarity, offset, gain, noise_type, normalize);
        return Vec3(fac, r, g);
    }
};

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
    // pkg186 — expose the bound texture so scene_upload.cu can detect an image
    // texture and bake it for the GPU path.
    std::shared_ptr<Texture> getTexture() const { return albedo; }
    Vec3 getAlbedo() const override { return Vec3(0.5f); }
    std::string getGPUTypeName() const override { return "lambertian"; }
    MaterialBackendCapabilities backendCapabilities() const override {
        MaterialBackendCapabilities caps = Material::backendCapabilities();
        // pkg186: image (ImageTexture) base colors now sample on the GPU path
        // (nearest, CPU-parity). Procedural-node textures and instanced-mesh UV
        // still flatten to base albedo on GPU, so this stays gpuApproximate.
        caps.gpuApproximate = true;
        caps.notes = "GPU: image textures sampled (pkg186); procedural/instanced "
                     "textures still approximated as flat albedo";
        return caps;
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
    astroray::SampledSpectrum evalSpectral(
            const HitRecord& rec, const Vec3& wo, const Vec3& wi,
            const astroray::SampledWavelengths& lambdas) const override {
        float cosTheta = wi.dot(rec.normal);
        if (cosTheta <= 0.0f) return astroray::SampledSpectrum(0.0f);
        return albedo->sampleSpectral(rec, wo, lambdas) * (cosTheta / float(M_PI));
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
        // Keep the inner hit's normal AND rec.frontFace. Translation does not rotate
        // normals; re-running setFaceNormal on the already-front-facing inner normal
        // would force rec.frontFace = true, breaking refraction enter/exit (the
        // dielectric keys off frontFace) on transformed glass meshes.
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
        // The Ray ctor normalizes the direction, discarding the length change the
        // scale introduces. Track that factor so the hit parameter t stays a WORLD
        // distance: the inner shape measures t in normalized scaled space, so scale
        // the t-bounds in and rec.t back out by |d|. Without this, rec.t for a scaled
        // mesh comes back ~1/scale too large and the scene BVH mis-orders the mesh
        // behind nearer primitives, so a scaled mesh becomes invisible to rays.
        const float sdlen = d.length();
        if (sdlen <= 0.0f) return false;
        Ray scaled(o, d, r.time, r.screenU, r.screenV);
        scaled.hasCameraFrame = r.hasCameraFrame;
        scaled.cameraOrigin = r.cameraOrigin;
        scaled.cameraU = r.cameraU;
        scaled.cameraV = r.cameraV;
        scaled.cameraW = r.cameraW;
        if (!object->hit(scaled, tMin * sdlen, tMax * sdlen, rec)) return false;
        rec.t /= sdlen;
        rec.point = Vec3(rec.point.x*scale.x, rec.point.y*scale.y, rec.point.z*scale.z);
        Vec3 n(rec.normal.x/scale.x, rec.normal.y/scale.y, rec.normal.z/scale.z);
        // Transform the (already front-facing) normal but PRESERVE rec.frontFace —
        // setFaceNormal would clobber it to always-true and break refraction
        // enter/exit on scaled glass. (Assumes orientation-preserving positive scale.)
        rec.normal = n.normalized();
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
        // Rotate the (already front-facing) normal but PRESERVE rec.frontFace —
        // setFaceNormal would clobber it to always-true and break refraction on
        // rotated glass. Rotation preserves the front-facing relationship.
        rec.normal = Vec3(cosT*n.x - sinT*n.z, n.y, sinT*n.x + cosT*n.z);
        return true;
    }
    bool boundingBox(AABB& box) const override { return object->boundingBox(box); }
};

// Mesh class body moved to include/astroray/shapes.h (pkg04).
class Mesh;
