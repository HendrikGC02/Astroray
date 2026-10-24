#pragma once
// PKG306_DIAG: TEMPORARY Phase 0 ablation switches (spec pkg306 "Phase 0: attribution",
// pkg294 ASTRORAY_PKG294_DIAG pattern). Remove after Phase 1. Unset or empty
// ASTRORAY_PKG306_DIAG = production behaviour: every switch below is then a no-op.
//
// ASTRORAY_PKG306_DIAG = comma-separated tokens:
//   nee_only      light sampling only: NEE MIS weights forced to 1, every BSDF/phase-sampled
//                 emitter or background hit after bounce 0 dropped (drops caustic/glint transport: biased)
//   bsdf_only     BSDF/phase sampling only: lamp, env and medium-segment NEE off (unbiased)
//   photon_off    no CPU photon map (the path tracer then takes the SMS branch for flagged casters)
//   sms_off       no SMS casters
//   no_term2      dispersive refraction keeps all 4 wavelength lanes (biased, diagnostic only)
//   equi_only / dist_only   medium segment direct light: equiangular / exponential distance only
//   spot_cone_cycles  light-tree spot cone theta_o = 0, theta_e = half angle (Cycles) instead of both = half angle
//   drop_<cls> / only_<cls>  drop one contribution class / keep only it (same paths, same RNG
//                 stream: the only_<cls> renders of all classes sum to the baseline), cls in
//                 camera glint caustic bsdfhit nee envnee voldirect volemit photon sms, and
//                 spechit = glint + caustic (the GPU classifies only this union)
#include <cstdlib>
#include <string>

namespace astroray {
namespace pkg306 {

enum Cls : unsigned {
    kCamera    = 1u << 0,  // emission / background on the camera segment (bounce 0)
    kGlint     = 1u << 1,  // emitter / lamp / background hit after camera -> delta+ (no non-delta vertex yet)
    kCaustic   = 1u << 2,  // the same right after a delta vertex on a path with a non-delta vertex (D S+ L)
    kBsdfHit   = 1u << 3,  // the same after a non-delta (BSDF / phase sampled) vertex, MIS-weighted
    kNee       = 1u << 4,  // lamp NEE at a surface vertex
    kEnvNee    = 1u << 5,  // environment NEE
    kVolDirect = 1u << 6,  // medium segment direct light
    kVolEmit   = 1u << 7,  // volume emission
    kPhoton    = 1u << 8,  // CPU photon-map gather
    kSms       = 1u << 9,  // SMS connection
};

struct Diag {
    bool active = false;
    unsigned keep = ~0u;
    bool neeOnly = false, bsdfOnly = false, photonOff = false, smsOff = false, noTerm2 = false;
    bool equiOnly = false, distOnly = false, spotConeCycles = false;
};

inline Diag parseDiag(const char* env) {
    Diag d;
    if (!env || !*env) return d;
    d.active = true;
    static const struct { const char* name; unsigned bit; } kNames[] = {
        {"camera", kCamera}, {"glint", kGlint}, {"caustic", kCaustic}, {"bsdfhit", kBsdfHit},
        {"nee", kNee}, {"envnee", kEnvNee}, {"voldirect", kVolDirect}, {"volemit", kVolEmit},
        {"photon", kPhoton}, {"sms", kSms}, {"spechit", kGlint | kCaustic}};
    std::string s(env);
    size_t p = 0;
    while (p <= s.size()) {
        size_t q = s.find(',', p);
        if (q == std::string::npos) q = s.size();
        const std::string t = s.substr(p, q - p);
        p = q + 1;
        if (t == "nee_only") { d.neeOnly = true; d.keep &= ~(kGlint | kCaustic | kBsdfHit); }
        else if (t == "bsdf_only") d.bsdfOnly = true;
        else if (t == "photon_off") d.photonOff = true;
        else if (t == "sms_off") d.smsOff = true;
        else if (t == "no_term2") d.noTerm2 = true;
        else if (t == "equi_only") d.equiOnly = true;
        else if (t == "dist_only") d.distOnly = true;
        else if (t == "spot_cone_cycles") d.spotConeCycles = true;
        else {
            for (const auto& n : kNames) {
                if (t == std::string("drop_") + n.name) d.keep &= ~n.bit;
                else if (t == std::string("only_") + n.name) d.keep &= n.bit;
            }
        }
    }
    return d;
}

inline const Diag& diag() {
    static const Diag d = parseDiag(std::getenv("ASTRORAY_PKG306_DIAG"));
    return d;
}

inline bool keep(unsigned cls) { return (diag().keep & cls) != 0u; }

// Class of an emitter / lamp / background hit: camera segment, glint, caustic or MIS'd BSDF hit.
inline unsigned hitClass(int bounce, bool wasSpecular, bool anyNonDelta) {
    if (bounce == 0) return kCamera;
    if (!wasSpecular) return kBsdfHit;
    return anyNonDelta ? kCaustic : kGlint;
}

}  // namespace pkg306
}  // namespace astroray
