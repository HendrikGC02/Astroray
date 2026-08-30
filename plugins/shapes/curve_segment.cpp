#include "astroray/register.h"
#include "astroray/curves.h"

// pkg225 Stage 1 — ShapeRegistry entry for a single CurveSegment (one cubic
// Catmull-Rom window). Mirrors SpherePlugin/MeshPlugin (plugins/shapes/*.cpp):
// pulls its params from ParamDict and delegates to the real shape class.
// Strand-level construction (phantom endpoints, many segments) goes through
// CurveStrip::buildCurveSegments() instead — see module/blender_module.cpp
// PyRenderer::addCurvesBulk, the actual bulk ingest path used by the addon.
class CurveSegmentPlugin : public CurveSegment {
public:
    explicit CurveSegmentPlugin(const astroray::ParamDict& p)
        : CurveSegment(p.getVec3("p0", Vec3(-1.0f, 0.0f, 0.0f)),
                       p.getVec3("p1", Vec3(0.0f, 0.0f, 0.0f)),
                       p.getVec3("p2", Vec3(1.0f, 0.0f, 0.0f)),
                       p.getVec3("p3", Vec3(2.0f, 0.0f, 0.0f)),
                       p.getFloat("radius0", 0.05f),
                       p.getFloat("radius1", 0.05f),
                       astroray::MaterialRegistry::instance().create(
                           p.getString("material_type", "lambertian"), p)) {}
};

ASTRORAY_REGISTER_SHAPE("curve_segment", CurveSegmentPlugin)
