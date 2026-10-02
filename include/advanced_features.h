#pragma once
#include "raytracer.h"
#include "astroray/shader_vm.h"   // pkg219b — bounded per-texel op-VM
#include "astroray/gpu_types.h"   // #1004 — GImgExt / gpu_imageWrapTexel
#include "astroray/procedural_tex.h"  // #1007 — host+device Noise / Wave / Voronoi
#include <utility>
#include <cstdio>   // pkg242 — visible warning for singular Mapping matrices

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

    // pkg242 — determinant of the 3x3 linear block of the 3x4 Mapping matrix.
    // Near-zero means a singular (collapsing) transform: the coordinate field
    // degenerates to a plane/line/point and the procedural becomes constant.
    float mappingLinearDet() const {
        float a = mapping_[0], b = mapping_[1], c = mapping_[2];
        float d = mapping_[4], e = mapping_[5], f = mapping_[6];
        float g = mapping_[8], h = mapping_[9], i = mapping_[10];
        return a*(e*i - f*h) - b*(d*i - f*g) + c*(d*h - e*g);
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

    // #1005: `dP` displaces the hit point (world == object space: the addon bakes world
    // transforms into vertices) for procedural bump taps; zero everywhere else.
    std::pair<Vec2, Vec3> textureCoordinates(const HitRecord& rec, const Vec3& wo,
                                             const Vec3& dP = Vec3(0.0f)) const {
        const Vec3 pt = rec.point + dP, opt = rec.objectPoint + dP;
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
                // #847 — per-vertex object-space Generated (rotation-correct,
                // per object) takes precedence over the per-texture bbox.
                {
                    Vec3 g;
                    if (rec.hitObject && rec.hitObject->generatedCoord(pt, g)) {
                        g = Vec3(std::clamp(g.x, 0.0f, 1.0f),
                                 std::clamp(g.y, 0.0f, 1.0f),
                                 std::clamp(g.z, 0.0f, 1.0f));
                        return {Vec2(g.x, g.y), g};
                    }
                }
                if (hasGenBBox_) {
                    Vec3 size = genSize_;
                    Vec3 p = opt;
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
                        Vec3 p = opt;
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
                return {uv, opt};
            }
            case CoordMode::Object: {
                // #1006 — object-local position (Cycles svm/tex_coord.h
                // NODE_TEXCO_OBJECT, object_inverse_position_transform). The addon
                // bakes world transforms into the vertices, so the triangle carries
                // per-vertex object-local positions (set_objects_object_transform);
                // without them (API scenes, spheres) world == object space.
                Vec3 o;
                if (rec.hitObject && rec.hitObject->objectCoord(pt, o))
                    return {Vec2(o.x, o.y), o};
                return {Vec2(opt.x, opt.y), opt};
            }
            case CoordMode::Camera: {
                if (!rec.hasCameraFrame) return {Vec2(pt.x, pt.y), pt};
                Vec3 rel = pt - rec.cameraOrigin;
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
    // #776 — a single representative colour for this texture, used where a
    // per-hit UV is unavailable (textured mesh-light NEE power importance in
    // src/light_tree.cpp and the flat GPU emitter upload in scene_upload.cu).
    // The default is one sample at the texture centre; ImageTexture/SolidColor
    // override with an exact mean. This is an importance/degradation estimate,
    // NOT the per-hit radiance (that stays textured via value(rec,...)).
    virtual Vec3 average() const {
        return value(Vec2(0.5f, 0.5f), Vec3(0.5f, 0.5f, 0.5f));
    }
    Vec3 value(const HitRecord& rec, const Vec3& wo) const {
        auto [uv, p] = textureCoordinates(rec, wo);
        // pkg242 — one transformed-coordinate contract: the 3-D Mapping applies
        // to BOTH the 2-D image sample coord (M*p).xy AND the procedural point
        // fed to value(uv,p), so Checker/Wave/Noise sample the transformed field
        // (identical to the GPU bake domain folded in scene_upload.cu). Image
        // and program consumers ignore p, so their behavior is unchanged
        // (pkg230b retained). hasMapping_==false keeps the legacy path
        // byte-identical (untransformed baseline).
        if (hasMapping_) {
            Vec3 mp = applyMappingPoint(p);
            return valueAtHit(Vec2(mp.x, mp.y), mp, rec, wo);
        }
        return valueAtHit(applyUVTransform(uv), p, rec, wo);
    }
    // #989 — value at a resolved coordinate that may also read the hit itself
    // (op-VM per-hit shading inputs, ProgramTexture). Default: value(uv, p).
    virtual Vec3 valueAtHit(const Vec2& uv, const Vec3& p,
                            const HitRecord& /*rec*/, const Vec3& /*wo*/) const {
        return value(uv, p);
    }
    // #962 — value at an already-built texture coordinate (uv, p), applying the
    // SAME transform chain as value(HitRecord) above (3-D Mapping if set, else
    // the legacy UV transform). Used by the GPU scene-upload bake so baked
    // fields sample the CPU's coordinates.
    Vec3 valueAtCoord(const Vec2& uv, const Vec3& p) const {
        if (hasMapping_) {
            Vec3 mp = applyMappingPoint(p);
            return value(Vec2(mp.x, mp.y), mp);
        }
        return value(applyUVTransform(uv), p);
    }
    // #1005 - value with the hit point displaced by a WORLD-space step dP (procedural
    // bump taps for Object / Generated / Camera coordinates). valueOffset() steps in
    // UV units, which is the right domain only for UV coordinates and images.
    Vec3 valueDisplaced(const HitRecord& rec, const Vec3& wo, const Vec3& dP) const {
        auto [uv, p] = textureCoordinates(rec, wo, dP);
        if (hasMapping_) {
            Vec3 mp = applyMappingPoint(p);
            return valueAtHit(Vec2(mp.x, mp.y), mp, rec, wo);
        }
        return valueAtHit(applyUVTransform(uv), p, rec, wo);
    }
    Vec3 valueOffset(const HitRecord& rec, const Vec3& wo, float du, float dv) const {
        auto [uv, p] = textureCoordinates(rec, wo);
        if (hasMapping_) {  // pkg242 — transform the procedural point too (see value())
            Vec3 mp = applyMappingPoint(p);
            // pkg242 follow-up (#737): perturb the mapped 3-D point by the same
            // (du,dv) the 2-D sample coord moves. Previously only the 2-D image
            // coord was offset while `mp` stayed fixed, so p-reading procedurals
            // (Noise/Wave/Musgrave) read an identical point for the base and
            // offset taps and produced a ZERO bump gradient under a Mapping.
            // Moving mp by (du,dv,0) keeps the 2-D image/Checker step
            // byte-identical to before AND gives the 3-D evaluators a finite
            // in-plane gradient (z left unperturbed: du,dv are tangent-plane
            // finite-difference steps).
            return value(Vec2(mp.x + du, mp.y + dv), mp + Vec3(du, dv, 0.0f));
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
        // pkg242 — a singular (rank-deficient) linear part collapses the
        // coordinate field, so the procedural degenerates to a constant. Report
        // it visibly instead of silently shading a flat surface. The test is
        // SCALE-RELATIVE (see mappingIsSingular): a legitimate tiny uniform
        // scale is no longer mis-flagged, only a genuinely rank-deficient frame.
        if (mappingIsSingular())
            std::fprintf(stderr,
                "[pkg242] warning: texture Mapping matrix is singular "
                "(det=%.3g); the procedural coordinate field collapses to a "
                "constant.\n", mappingLinearDet());
    }
    bool hasMapping() const { return hasMapping_; }
    const float* getMappingMatrix() const { return mapping_; }
    // pkg242 — public coordinate transform onto the approved contract: applies
    // the 3-D Mapping matrix when set, else identity (byte-identical). The GPU
    // scene-upload folds this into the procedural bake so the device fetch stays
    // transform-agnostic and register-neutral (no new per-hit shade state).
    // pkg242 follow-up (#737): SCALE-RELATIVE singular test. The old absolute
    // |det| < 1e-8 flagged a legitimate uniform scale s below ~0.002 as
    // singular (det = s^3 = 8e-9 < 1e-8), even though such a matrix is perfectly
    // invertible — it just magnifies the field. Compare |det| against the
    // product of the three column norms instead, i.e. the normalized determinant
    // |det| / (||c0|| ||c1|| ||c2||) in [0,1] (1 for an orthogonal frame at any
    // scale, ~0 when a column is near-zero or two are near-parallel, which is
    // what actually collapses the coordinate field). A uniform scale s gives
    // det=s^3 and norm-product=s^3 → ratio 1 at every scale.
    bool mappingIsSingular() const {
        const float n0 = std::sqrt(mapping_[0]*mapping_[0] + mapping_[4]*mapping_[4] + mapping_[8]*mapping_[8]);
        const float n1 = std::sqrt(mapping_[1]*mapping_[1] + mapping_[5]*mapping_[5] + mapping_[9]*mapping_[9]);
        const float n2 = std::sqrt(mapping_[2]*mapping_[2] + mapping_[6]*mapping_[6] + mapping_[10]*mapping_[10]);
        const float vol = n0 * n1 * n2;
        if (vol < 1e-20f) return true;  // a zero/near-zero column collapses it
        return std::fabs(mappingLinearDet()) < 1e-6f * vol;  // rank-deficient
    }
    Vec3 mappedPoint(const Vec3& p) const {
        return hasMapping_ ? applyMappingPoint(p) : p;
    }
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
        // pkg242 — full 3-D Mapping applies to the sample coord AND p (see value()).
        if (hasMapping_) {
            Vec3 mp = applyMappingPoint(p);
            return sampleSpectralAtHit(Vec2(mp.x, mp.y), mp, rec, wo, lambdas);
        }
        return sampleSpectralAtHit(applyUVTransform(uv), p, rec, wo, lambdas);
    }
    // #989 — spectral twin of valueAtHit (default: sampleSpectral(uv, p)).
    virtual astroray::SampledSpectrum sampleSpectralAtHit(
            const Vec2& uv, const Vec3& p, const HitRecord& /*rec*/, const Vec3& /*wo*/,
            const astroray::SampledWavelengths& lambdas) const {
        return sampleSpectral(uv, p, lambdas);
    }
};

class SolidColor : public Texture {
    Vec3 color;
public:
    SolidColor(const Vec3& c) : color(c) {}
    Vec3 value(const Vec2&, const Vec3&) const override { return color; }
    Vec3 average() const override { return color; }  // #776 — exact mean
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
    Vec3 average() const override {  // #776 — 50/50 cell mean
        return (odd->average() + even->average()) * 0.5f;
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
    Vec3 mean_{1, 0, 1};  // #776 — cached pixel mean for average()
    int extension_ = 0;   // #1004 - GImgExt::G_IMG_EXTEND
    // Spectral cache: one RGBAlbedoSpectrum per texel, built eagerly in setData().
    std::vector<astroray::RGBAlbedoSpectrum> spectral_cache_;
public:
    void setData(const std::vector<Vec3>& d, int w, int h) {
        data = d; width = w; height = h;
        spectral_cache_.resize(data.size());
        Vec3 sum(0);
        for (size_t i = 0; i < data.size(); ++i) {
            const Vec3& c = data[i];
            spectral_cache_[i] = astroray::RGBAlbedoSpectrum({c.x, c.y, c.z});
            sum += c;
        }
        if (!data.empty()) mean_ = sum * (1.0f / static_cast<float>(data.size()));
    }
    Vec3 average() const override { return mean_; }  // #776 — exact pixel mean
    // pkg186 — read-only accessors so the GPU scene-upload (scene_upload.cu) can
    // bake this image into a device buffer. The device sampler mirrors value()'s
    // nearest-neighbour clamp+v-flip exactly (see gpu_sampleImageTexture).
    int getWidth()  const { return width; }
    int getHeight() const { return height; }
    const std::vector<Vec3>& getData() const { return data; }
    // #1004 - Image Texture extension (GImgExt, shared with the GPU sampler).
    // Default EXTEND (clamp) keeps every untagged texture byte-identical; the
    // addon tags REPEAT / CLIP / MIRROR from the node.
    void setExtension(int ext) { extension_ = ext; }
    int getExtension() const { return extension_; }
    Vec3 value(const Vec2& uv, const Vec3&) const override {
        if (data.empty()) return Vec3(1, 0, 1);
        if (extension_ != G_IMG_EXTEND) {
            int wi, wj;
            if (!gpu_imageWrapTexel(extension_, width, height, uv.u, uv.v, &wi, &wj))
                return Vec3(0, 0, 0);
            return data[wj * width + wi];
        }
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
        if (extension_ != G_IMG_EXTEND) {
            int wi, wj;
            if (!gpu_imageWrapTexel(extension_, width, height, uv.u, uv.v, &wi, &wj))
                return astroray::RGBAlbedoSpectrum({0.f, 0.f, 0.f}).sample(lambdas);
            return spectral_cache_[wj * width + wi].sample(lambdas);
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
        return eval(uv, p, nullptr);
    }
    // #989 — per-hit shading context for OP_SHADING: cos between the view
    // direction (wo, Cycles sd->wi) and the shading normal, and the back-face flag.
    Vec3 valueAtHit(const Vec2& uv, const Vec3& p, const HitRecord& rec,
                    const Vec3& wo) const override {
        astroray::svm::SvmShading sh;
        sh.cosI = wo.dot(rec.normal);
        sh.backfacing = rec.frontFace ? 0.0f : 1.0f;
        return eval(uv, p, &sh);
    }
    astroray::SampledSpectrum sampleSpectralAtHit(
            const Vec2& uv, const Vec3& p, const HitRecord& rec, const Vec3& wo,
            const astroray::SampledWavelengths& lambdas) const override {
        Vec3 rgb = valueAtHit(uv, p, rec, wo);
        return astroray::RGBAlbedoSpectrum({rgb.x, rgb.y, rgb.z}).sample(lambdas);
    }

private:
    Vec3 eval(const Vec2& uv, const Vec3& p, const astroray::svm::SvmShading* sh) const {
        GVec3 in[astroray::svm::VM_MAX_TEX];
        int nt = program_.numTex;
        if (nt > astroray::svm::VM_MAX_TEX) nt = astroray::svm::VM_MAX_TEX;
        for (int i = 0; i < nt; ++i) {
            Vec3 c = i < (int)inputs_.size() ? inputs_[i]->value(uv, p) : Vec3(0.f);
            in[i] = GVec3(c.x, c.y, c.z);
        }
        GVec3 r = astroray::svm::svm_eval(program_, in, sh);
        return Vec3(r.x, r.y, r.z);
    }
};

// ============================================================================
// pkg277 (#822) — CoordProgramTexture: a procedural child sampled at a
// coordinate warped by an op-VM program (Separate XYZ -> Math(Sin) -> Combine
// XYZ -> Noise). OP_LOAD_TEX 0 reads the resolved (+Mapped) point p; the child
// is sampled at p' = svm_eval(prog, {p}). Coord mode + Mapping live on the
// wrapper, so Mapping precedes the warp. GPU: evaluated per hit when the child
// and input are Noise / Wave / Voronoi (#1007, gpu_procTexEval), else value() is
// baked via scene_upload.cu bakeProceduralTexId (pkg190).
// Design: .astroray_plan/docs/issue822-coordinate-side-opvm-design.md
// ============================================================================
class CoordProgramTexture : public Texture {
    std::shared_ptr<Texture> child_;
    astroray::svm::ShaderVMProgram program_;
    // #891 — texture-driven warps (Noise -> Vector Math -> ...): OP_LOAD_TEX k>=1
    // reads inputs_[k-1] sampled at the same resolved point p (the compiler only
    // admits inputs sharing the wrapper's base coordinate).
    std::vector<std::shared_ptr<Texture>> inputs_;
public:
    CoordProgramTexture(std::shared_ptr<Texture> child,
                        const astroray::svm::ShaderVMProgram& p,
                        std::vector<std::shared_ptr<Texture>> inputs = {})
        : child_(std::move(child)), program_(p), inputs_(std::move(inputs)) {}
    // #1007: read by the GPU per-hit lowering (scene_upload.cu lowerProcTexture).
    const std::shared_ptr<Texture>& child() const { return child_; }
    const astroray::svm::ShaderVMProgram& program() const { return program_; }
    size_t numInputs() const { return inputs_.size(); }
    const std::shared_ptr<Texture>& getInput(size_t i) const { return inputs_[i]; }
    Vec3 value(const Vec2&, const Vec3& p) const override {
        GVec3 in[astroray::svm::VM_MAX_TEX];
        for (int i = 0; i < astroray::svm::VM_MAX_TEX; ++i) in[i] = GVec3(p.x, p.y, p.z);
        for (size_t i = 0; i < inputs_.size() && i + 1 < (size_t)astroray::svm::VM_MAX_TEX; ++i) {
            Vec3 c = inputs_[i]->value(Vec2(p.x, p.y), p);
            in[i + 1] = GVec3(c.x, c.y, c.z);
        }
        GVec3 w = astroray::svm::svm_eval(program_, in);
        return child_->value(Vec2(w.x, w.y), Vec3(w.x, w.y, w.z));
    }
    // #891 — GPU emitters upload average() (flat); the default centre sample of the
    // UNWARPED point picked one checker cell (MapAfterWarp read flat blue). The warp
    // only moves the sample point, so the child's own mean is the right estimate.
    Vec3 average() const override { return child_->average(); }
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
// Cycles intern/cycles/kernel/svm/wave.h svm_wave (Apache-2.0), pkg115 chunk 3.
// The evaluator lives in astroray/procedural_tex.h (host + device, #1007): the
// GPU runs the same code per hit.
// wave_type: 0=Bands, 1=Rings; bands_direction: 0=X, 1=Y, 2=Z, 3=Diagonal;
// rings_direction: 0=X, 1=Y, 2=Z, 3=Spherical; profile: 0=Sine, 1=Saw, 2=Triangle.
inline GVec3 toProcVec(const Vec3& v) { return GVec3(v.x, v.y, v.z); }
inline Vec3 fromProcVec(const GVec3& v) { return Vec3(v.x, v.y, v.z); }

class WaveTexture : public Texture {
    astroray::proc::WaveParams params_;
public:
    WaveTexture(int wt = 0, int bd = 0, int rd = 0, int prof = 0,
                float sc = 5.0f, float dist = 0.0f, float det = 2.0f,
                float dscale = 1.0f, float drough = 0.5f, float phase = 0.0f,
                const Vec3& c1 = Vec3(0), const Vec3& c2 = Vec3(1))
        : params_{wt, bd, rd, prof, sc, dist, det, dscale, drough, phase,
                  toProcVec(c1), toProcVec(c2)} {}
    // #1007: the GPU per-hit evaluator reads the same parameters.
    const astroray::proc::WaveParams& procParams() const { return params_; }
    Vec3 value(const Vec2&, const Vec3& p) const override {
        return fromProcVec(astroray::proc::wave_texture(params_, toProcVec(p)));
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
// Cycles intern/cycles/kernel/svm/voronoi.h (Apache-2.0; smooth F1 / distance to
// edge after Inigo Quilez 2013, MIT), pkg115 chunk 4. The evaluator lives in
// astroray/procedural_tex.h (host + device, #1007).
// Distance metrics: Euclidean / Manhattan / Chebychev / Minkowski(exponent param).
// Features (Blender order): 0=F1, 1=Smooth F1, 2=F2, 3=Distance to Edge, 4=N-Sphere Radius.
// Standalone-only legacy features: 5=F1+F2, 6=F2-F1.
// VoronoiOutput: distance, color (cell hash RGB), position (jittered cell center).
struct VoronoiOutput {
    float distance;
    Vec3 color;
    Vec3 position;
    float radius;  // N-Sphere Radius feature only
};

class VoronoiTexture : public Texture {
    astroray::proc::VoronoiParams params_;
public:
    VoronoiTexture(float sc = 5.0f, float det = 0.0f, float rough = 0.5f, float lac = 2.0f,
                   float smooth = 1.0f, float exp = 0.5f, float rand = 1.0f,
                   bool norm = false, int dm = 0, int feat = 0,
                   const Vec3& c1 = Vec3(0), const Vec3& c2 = Vec3(1),
                   bool colorOut = false)
        : params_{sc, det, rough, lac, smooth, exp, rand, 0.0f, norm ? 1 : 0, colorOut ? 1 : 0,
                  dm, feat, toProcVec(c1), toProcVec(c2)} {
        // Cycles svm_node_tex_voronoi conditioning + max_distance for normalize.
        astroray::proc::voronoi_condition(params_);
    }
    // #1007: the GPU per-hit evaluator reads the same (conditioned) parameters.
    const astroray::proc::VoronoiParams& procParams() const { return params_; }

    // #944: Color output returns the hashed cell colour; Distance is a 2-colour lerp.
    Vec3 value(const Vec2&, const Vec3& p) const override {
        return fromProcVec(astroray::proc::voronoi_texture(params_, toProcVec(p)));
    }

    // Full multi-output eval (distance, color, position, radius).
    VoronoiOutput evalFull(const Vec3& p) const {
        astroray::proc::VoronoiOut o = astroray::proc::voronoi_eval_full(params_, toProcVec(p));
        return VoronoiOutput{o.distance, fromProcVec(o.color), fromProcVec(o.position), o.radius};
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

class WhiteNoiseTexture : public Texture {
public:
    WhiteNoiseTexture() = default;
    Vec3 value(const Vec2&, const Vec3& p) const override {
        // Cycles intern/cycles/kernel/svm/white_noise.h::svm_node_tex_white_noise (Apache-2.0).
        // 3D white noise: color = hash_float3_to_float3 (astroray/procedural_tex.h).
        return fromProcVec(astroray::proc::hash_float3_to_float3(p.x, p.y, p.z));
    }
};

// ============================================================================
// NOISE TEXTURE (real Perlin-based, pkg115 chunk 2)
// ============================================================================
// Blender "Noise Texture" node (includes Musgrave semantics since Blender 4.1).
// Cycles intern/cycles/kernel/svm/noisetex.h (Apache-2.0); evaluator in
// astroray/procedural_tex.h (host + device, #1007).
// Default noise_type = fBM (0), normalize = true. Musgrave types map to the
// noise_type enum: 1=MULTIFRACTAL, 2=HYBRID_MULTIFRACTAL, 3=RIDGED_MULTIFRACTAL, 4=HETERO_TERRAIN.
class NoiseTextureCycles : public Texture {
    astroray::proc::NoiseParams params_;
public:
    NoiseTextureCycles(float s = 5.0f, float det = 2.0f, float rough = 0.5f,
                       float lac = 2.0f, float off = 0.0f, float g = 1.0f,
                       float dist = 0.0f, int type = 0, bool norm = true,
                       int dims = 3, float w = 0.0f, bool facOnly = false)
        : params_{s, det, rough, lac, off, g, dist, type, norm ? 1 : 0} {
        // #881: Noise dimensions (1D-4D) + W, and the grey Fac-only output.
        params_.dimensions = (dims >= 1 && dims <= 4) ? dims : 3;
        params_.w = w;
        params_.facOnly = facOnly ? 1 : 0;
    }
    // #1007: the GPU per-hit evaluator reads the same parameters.
    const astroray::proc::NoiseParams& procParams() const { return params_; }

    Vec3 value(const Vec2&, const Vec3& p) const override {
        return fromProcVec(astroray::proc::noise_texture(params_, toProcVec(p)));
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

// #762 — textured Emission Color. Neither DiffuseLightPlugin ("light"/
// "emission", plugins/materials/diffuse_light.cpp) nor EmissivePlugin
// ("emissive") has a texture slot, so a procedural/image texture wired
// directly into a Blender Emission node's Color input rendered flat white
// (the addon's get_color_input() fallback default) with no per-texel
// evaluation. Mirrors TexturedLambertian above: front-face-only emission
// (matches DiffuseLightPlugin, NOT the two-sided EmissivePlugin), same
// intensity*color-then-upsample convention DiffuseLightPlugin uses.
class TexturedLight : public Material {
    std::shared_ptr<Texture> emission;
    float intensity_;
public:
    TexturedLight(std::shared_ptr<Texture> e, float intensity) : emission(e), intensity_(intensity) {}
    // Mirrors TexturedLambertian::getTexture(). #962: scene_upload.cu bakes it
    // (+ getIntensity()) for the GPU wavefront's per-hit emission fetch.
    std::shared_ptr<Texture> getTexture() const { return emission; }
    float getIntensity() const { return intensity_; }
    // No HitRecord available here (used for the mesh-light NEE power importance
    // in light_tree.cpp and the flat GPU emitter upload in scene_upload.cu).
    // #776: return the texture MEAN × intensity (not flat white × intensity) so
    // both the light-tree power estimate and the GPU upload carry the emitter's
    // actual average colour. Per-hit radiance stays textured via emitted()/
    // emittedSpectral() below.
    Vec3 getEmission() const override {
        return (emission ? emission->average() : Vec3(1.0f)) * intensity_;
    }
    bool isEmissive() const override { return true; }
    std::string getGPUTypeName() const override { return "diffuse_light"; }
    MaterialBackendCapabilities backendCapabilities() const override {
        MaterialBackendCapabilities caps = Material::backendCapabilities();
        caps.gpuApproximate = true;
        caps.notes = "GPU: textured Emission Color sampled per hit on the wavefront path (#962; "
                     "procedurals baked at 64^2/64^3); ReSTIR light reuse still uses the texture MEAN";
        return caps;
    }
    Vec3 emitted(const HitRecord& rec) const override {
        if (!rec.frontFace) return Vec3(0);
        return emission->value(rec, Vec3(0)) * intensity_;
    }
    astroray::SampledSpectrum emittedSpectral(
            const HitRecord& rec,
            const astroray::SampledWavelengths& lambdas) const override {
        if (!rec.frontFace) return astroray::SampledSpectrum(0.0f);
        Vec3 c = emission->value(rec, Vec3(0)) * intensity_;
        return astroray::RGBIlluminantSpectrum({c.x, c.y, c.z}).sample(lambdas);
    }
    astroray::SampledSpectrum evalSpectral(
            const HitRecord&, const Vec3&, const Vec3&,
            const astroray::SampledWavelengths&) const override {
        return astroray::SampledSpectrum(0.0f);
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
