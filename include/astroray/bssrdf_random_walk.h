// ============================================================================
// Random-walk BSSRDF (subsurface scattering) — CPU prototype core.
//
// Source (math ported, cited per-function; not a verbatim file copy):
//   Blender Cycles, src/kernel/integrator/subsurface_random_walk.h
//                    src/kernel/closure/bssrdf.h
//   github.com/blender/cycles @ main (fetched 2026-08-08, Blender 5.2-era)
//   License: Apache-2.0 (SPDX-FileCopyrightText: 2011-2022 Blender Foundation)
//            — compatible with Astroray's MIT LICENSE (attribution retained;
//            recorded in THIRD_PARTY.md). Same port convention as
//            energy_compensation.h / disney.cpp.
//
// Papers:
//   Chiang, Kutz, Burley, "Practical and Controllable Subsurface Scattering
//     for Production Path Tracing", SIGGRAPH 2016 Talks. (color remap)
//   d'Eon, "A Hitchhiker's Guide to Multiple Scattering", 2016, Eq. 53.7.
//     (van de Hulst similarity inversion)
//   Krivanek & d'Eon, "A Zero-variance-based Sampling Scheme...", SIGGRAPH
//     2014 Talks. (Dwivedi direction guiding)
//   Meng, Hanika, Dachsbacher, "Improving the Dwivedi Sampling Scheme",
//     EGSR 2016. (eval/sample_phase_dwivedi — Eq. 9/10)
//   d'Eon & Krivanek, "Zero-Variance Theory for Efficient Subsurface
//     Scattering", SIGGRAPH 2020 Courses, Eq. 67. (diffusion length)
//   Henyey & Greenstein 1941. (phase function)
//
// Research note: .astroray_plan/docs/bssrdf-random-walk-research.md
//
// SCOPE (pkg178 D2 parallel-track prototype): CPU only.
//   * VERIFIED / DEFAULT: the transport backbone — color/radius -> coefficients,
//     the classic channel-MIS random walk (boundary handling, absorption,
//     translucent falloff). Furnace-clean and unbiased for colored media.
//   * EXPERIMENTAL (opt-in, useDwivedi=true): Dwivedi *direction* guiding.
//     MEASURED FINDING (see test [D]/[E]): direction-only guiding is unbiased
//     and low-variance for GRAY/achromatic media, but WITHOUT the companion
//     distance-stretching it has pathological variance for COLORED media
//     (per-channel diffusion lengths differ, so a single averaged guiding v
//     over-guides high-albedo channels — infinite-variance-like tails). The
//     zero-variance property REQUIRES the joint per-channel direction+distance
//     scheme (Meng 2016 stretched sigma_t + backward guiding), which is
//     DEFERRED to the GPU/follow-up stage. Formulas are in the research note.
//   Deliberately omits: distance stretching, backward guiding, the g<0 arctan
//   remap, and the SKIN dipole rescale (all recorded in the research note).
//
// GPU: DEFERRED. This header is intentionally POD + templated (Float3 == CUDA
// float3, intersector/RNG are template params, no std::function, no STL in the
// hot path) so a __device__ twin is a mechanical port.
// ============================================================================
#ifndef ASTRORAY_BSSRDF_RANDOM_WALK_H
#define ASTRORAY_BSSRDF_RANDOM_WALK_H

#include <cmath>
#include <algorithm>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

namespace astroray {
namespace bssrdf {

// POD RGB / vector. Layout-identical to CUDA float3 (x,y,z contiguous floats).
struct Float3 {
    float x = 0.0f, y = 0.0f, z = 0.0f;
    Float3() = default;
    Float3(float v) : x(v), y(v), z(v) {}
    Float3(float x_, float y_, float z_) : x(x_), y(y_), z(z_) {}
    float operator[](int i) const { return (&x)[i]; }
    float& operator[](int i) { return (&x)[i]; }
};

inline Float3 operator+(Float3 a, Float3 b) { return {a.x+b.x, a.y+b.y, a.z+b.z}; }
inline Float3 operator-(Float3 a, Float3 b) { return {a.x-b.x, a.y-b.y, a.z-b.z}; }
inline Float3 operator*(Float3 a, Float3 b) { return {a.x*b.x, a.y*b.y, a.z*b.z}; }
inline Float3 operator*(Float3 a, float s)  { return {a.x*s, a.y*s, a.z*s}; }
inline Float3 operator*(float s, Float3 a)  { return {a.x*s, a.y*s, a.z*s}; }
inline Float3 operator-(Float3 a)           { return {-a.x, -a.y, -a.z}; }
inline float  dot(Float3 a, Float3 b)       { return a.x*b.x + a.y*b.y + a.z*b.z; }
inline float  reduce_max(Float3 a)          { return std::max(a.x, std::max(a.y, a.z)); }
inline float  reduce_min(Float3 a)          { return std::min(a.x, std::min(a.y, a.z)); }
inline float  reduce_add(Float3 a)          { return a.x + a.y + a.z; }
inline Float3 normalize(Float3 a) {
    float l = std::sqrt(dot(a, a));
    return l > 0.0f ? a * (1.0f / l) : Float3(0.0f);
}

// Right-handed orthonormal basis around unit n (Duff et al. 2017, branchless).
inline void basis(Float3 n, Float3& t, Float3& b) {
    float sign = std::copysign(1.0f, n.z);
    float a = -1.0f / (sign + n.z);
    float d = n.x * n.y * a;
    t = {1.0f + sign * n.x * n.x * a, sign * d, -sign * n.x};
    b = {d, sign + n.y * n.y * a, -n.y};
}

// Direction whose angle with unit axis has cosine == cos_theta, azimuth from u.
inline Float3 direction_from_cosine(Float3 axis, float cos_theta, float u) {
    float sin_theta = std::sqrt(std::max(0.0f, 1.0f - cos_theta * cos_theta));
    float phi = 2.0f * float(M_PI) * u;
    Float3 t, b;
    basis(axis, t, b);
    return normalize(t * (std::cos(phi) * sin_theta)
                   + b * (std::sin(phi) * sin_theta)
                   + axis * cos_theta);
}

// -------- Henyey-Greenstein phase (Henyey & Greenstein 1941) ----------------
// Solid-angle pdf == phase value (energy-normalized over the sphere).
inline float hg_pdf(float cos_theta, float g) {
    float d = 1.0f + g * g - 2.0f * g * cos_theta;
    return (1.0f - g * g) / (4.0f * float(M_PI) * d * std::sqrt(std::max(d, 1e-8f)));
}
inline Float3 hg_sample(Float3 wi, float g, float u1, float u2) {
    float cos_theta;
    if (std::fabs(g) < 1e-3f) {
        cos_theta = 1.0f - 2.0f * u1;               // isotropic
    } else {
        float s = (1.0f - g * g) / (1.0f - g + 2.0f * g * u1);
        cos_theta = (1.0f + g * g - s * s) / (2.0f * g);
    }
    return direction_from_cosine(wi, cos_theta, u2);
}

// -------- Dwivedi / zero-variance guiding ----------------------------------
// diffusion length v (d'Eon & Krivanek 2020, Eq. 67).
inline float dwivedi_diffusion_length(float alpha) {
    alpha = std::clamp(alpha, 1e-4f, 0.999999f);
    float e = 2.44294f - 0.0215813f * alpha + 0.578637f / alpha;
    return 1.0f / std::sqrt(1.0f - std::pow(alpha, e));
}
// Meng 2016 Eq. 9 (eval, normalized on mu in [-1,1]) — mu is cos-to-outward-N.
inline float dwivedi_eval_mu(float v, float phase_log, float mu) {
    return 1.0f / ((v - mu) * phase_log);
}
// Meng 2016 Eq. 10 (sample mu).
inline float dwivedi_sample_mu(float v, float phase_log, float u) {
    return v - (v + 1.0f) * std::exp(-u * phase_log);
}

// ---------------------------------------------------------------------------
struct RandomWalkParams {
    Float3 albedo   = Float3(0.8f);   // subsurface color (per channel, in [0,1])
    Float3 radius   = Float3(1.0f);   // subsurface_radius * subsurface_scale (world units)
    float  anisotropy = 0.0f;         // g in [-1,1]
    float  ior        = 1.4f;         // reserved for boundary Fresnel (unused in prototype)
};

struct RandomWalkCoefficients {
    Float3 sigma_t = Float3(1.0f);    // extinction per channel
    Float3 alpha   = Float3(1.0f);    // single-scatter albedo per channel (post low-albedo clamp)
    Float3 tp_scale = Float3(1.0f);   // throughput compensation for the low-albedo clamp
    float  g = 0.0f;
};

// Cycles subsurface_random_walk.h: radius->sigma_t and color->single-scatter
// albedo (van de Hulst inversion, g>=0 path; d'Eon 2016 Eq. 53.7).
inline RandomWalkCoefficients setupCoefficients(const RandomWalkParams& p) {
    RandomWalkCoefficients c;
    c.g = std::clamp(p.anisotropy, -0.99f, 0.99f);
    for (int i = 0; i < 3; ++i) {
        float A = std::clamp(p.albedo[i], 0.0f, 1.0f);
        // van de Hulst similarity inversion (color -> single-scatter albedo).
        float s = 4.09712f + 4.20863f * A
                - std::sqrt(std::max(0.0f,
                    9.59217f + 41.6808f * A + 17.7126f * A * A));
        float alpha = (1.0f - s * s) / (1.0f - c.g * s * s);
        alpha = std::clamp(alpha, 0.0f, 1.0f);

        // Low-albedo clamp (Cycles): keep the estimator unbiased while bounding
        // walk length in nearly-absorbing media.
        float tp = 1.0f;
        if (alpha < 0.2f) {
            tp = alpha / 0.2f;
            alpha = 0.2f;
        }
        // sigma_t' = 1/radius ; sigma_t = sigma_t'/(1-g).
        float r = std::max(p.radius[i], 1e-16f);
        c.sigma_t[i] = (1.0f / r) / (1.0f - c.g);
        c.alpha[i]   = alpha;
        c.tp_scale[i] = tp;
    }
    return c;
}

// Boundary intersection result returned by the caller-supplied intersector.
struct BoundaryHit {
    float  t = 0.0f;          // distance along the ray to the object boundary
    Float3 normal = Float3(0.0f);  // outward geometric normal at the hit
    bool   hit = false;       // false: no boundary within tmax (open geometry)
};

struct WalkResult {
    bool   exited = false;    // true: reached the object boundary (valid exit)
    Float3 exitPoint = Float3(0.0f);
    Float3 exitNormal = Float3(0.0f);
    Float3 throughput = Float3(0.0f);  // per-channel weight of the exit diffuse lobe
    int    bounces = 0;
};

constexpr int   BSSRDF_MAX_BOUNCES = 256;
constexpr float VOLUME_THROUGHPUT_EPSILON = 1e-6f;

// Balance-heuristic channel pick proportional to |throughput|. Returns the
// channel index and fills channel_pdf[c] = w[c]/sum(w).
inline int pickChannel(Float3 tp, float u, float channel_pdf[3]) {
    float w0 = std::fabs(tp.x), w1 = std::fabs(tp.y), w2 = std::fabs(tp.z);
    float sum = w0 + w1 + w2;
    if (!(sum > 0.0f)) { channel_pdf[0]=channel_pdf[1]=channel_pdf[2]=1.0f/3.0f; return int(u*3.0f)%3; }
    channel_pdf[0] = w0/sum; channel_pdf[1] = w1/sum; channel_pdf[2] = w2/sum;
    float c = u * sum;
    if (c < w0) return 0;
    if (c < w0 + w1) return 1;
    return 2;
}

// ---------------------------------------------------------------------------
// The random walk. Enters the medium along -entryNormal and scatters until it
// reaches the object boundary (exit) or throughput is killed.
//
// Intersector: BoundaryHit operator()(Float3 origin, Float3 dir, float tmax) const;
//   must return the FIRST boundary crossing of the closed object along the ray.
// RNG: any callable/engine usable as `dist(rng)` via std::uniform... — here we
//   only require `float next()` semantics, so we take a lambda `rand()`.
// ---------------------------------------------------------------------------
// useDwivedi defaults to false: the classic walk is the verified path. Enable
// Dwivedi only for gray/achromatic media until the joint distance-stretching
// scheme lands (see the SCOPE/EXPERIMENTAL note above).
template <class Intersector, class RandFn>
WalkResult randomWalk(const RandomWalkParams& params,
                      Float3 entryPoint, Float3 entryNormal,
                      const Intersector& intersect, RandFn&& rand,
                      bool useDwivedi = false) {
    const RandomWalkCoefficients c = setupCoefficients(params);
    const Float3 N = normalize(entryNormal);   // outward normal at entry
    const float  g = c.g;

    WalkResult out;
    Float3 tp = c.tp_scale;                     // start with the clamp compensation
    Float3 P = entryPoint;
    Float3 D = -N;                              // enter straight into the surface

    // Precompute per-channel Dwivedi terms (angle-independent).
    Float3 v_len, phase_log;
    for (int i = 0; i < 3; ++i) {
        v_len[i]    = dwivedi_diffusion_length(c.alpha[i]);
        phase_log[i]= std::log((v_len[i] + 1.0f) / (v_len[i] - 1.0f));
    }
    // Cycles guided_fraction: less guiding for strongly anisotropic media.
    const float guided_fraction = useDwivedi
        ? (1.0f - std::max(0.5f, std::pow(std::fabs(g), 0.125f)))
        : 0.0f;

    for (int bounce = 0; bounce < BSSRDF_MAX_BOUNCES; ++bounce) {
        out.bounces = bounce + 1;

        // ---- direction (bounce > 0) --------------------------------------
        // one-sample MIS between the classic HG phase and Dwivedi guiding.
        // The integrand is the true HG phase; both are just samplers for it.
        float dir_weight = 1.0f;   // f_hg(w) / p_dir(w)
        if (bounce > 0) {
            bool guided = useDwivedi && (rand() < guided_fraction);
            Float3 newD;
            if (guided) {
                // guide toward the outward normal N (toward exiting).
                // pick the channel's diffusion length by luminance-ish average.
                float vh = (v_len.x + v_len.y + v_len.z) * (1.0f/3.0f);
                float ph = (phase_log.x + phase_log.y + phase_log.z) * (1.0f/3.0f);
                float mu = dwivedi_sample_mu(vh, ph, rand());
                newD = direction_from_cosine(N, mu, rand());
            } else {
                newD = hg_sample(D, g, rand(), rand());
            }
            // MIS pdf (solid angle) combining both strategies for THIS newD.
            float vh = (v_len.x + v_len.y + v_len.z) * (1.0f/3.0f);
            float ph = (phase_log.x + phase_log.y + phase_log.z) * (1.0f/3.0f);
            float mu = dot(newD, N);
            float p_dw = dwivedi_eval_mu(vh, ph, std::clamp(mu, -0.999999f, 0.999999f))
                         * (1.0f / (2.0f * float(M_PI)));
            float p_hg = hg_pdf(dot(D, newD), g);
            float p_dir = guided_fraction * p_dw + (1.0f - guided_fraction) * p_hg;
            dir_weight = (p_dir > 0.0f) ? (p_hg / p_dir) : 0.0f;  // f_hg == p_hg
            D = newD;
        }
        tp = tp * dir_weight;

        // ---- distance sampling (classic, channel MIS) --------------------
        float channel_pdf[3];
        int ch = pickChannel(tp, rand(), channel_pdf);
        float sample_sigma_t = c.sigma_t[ch];
        float t = -std::log(1.0f - rand()) / sample_sigma_t;

        float tmax = t;
        if (bounce == 0) {
            // Cycles: trace far on the first step to reliably reach the far
            // boundary of thin objects.
            tmax = std::max(t, 10.0f / std::max(reduce_min(c.sigma_t), 1e-16f));
        }
        BoundaryHit bh = intersect(P, D, tmax);

        bool exit_now = bh.hit && (bh.t <= t);
        float seg = exit_now ? bh.t : t;

        // per-channel transmittance over the travelled segment.
        Float3 T = {std::exp(-c.sigma_t.x * seg),
                    std::exp(-c.sigma_t.y * seg),
                    std::exp(-c.sigma_t.z * seg)};

        if (exit_now) {
            // reached the boundary without scattering in [0,seg].
            // balance-heuristic pdf of "no collision before the boundary".
            float P_exit = channel_pdf[0]*T.x + channel_pdf[1]*T.y + channel_pdf[2]*T.z;
            if (!(P_exit > 0.0f)) { out.exited = false; return out; }
            tp = tp * (1.0f / P_exit) * T;
            out.exited = true;
            out.exitPoint = P + D * bh.t;
            out.exitNormal = bh.normal;
            out.throughput = tp;
            return out;
        }

        // scatter event at distance t.
        Float3 sigma_s = c.sigma_t * c.alpha;
        // balance-heuristic pdf of a collision at t: sum_c cp[c]*sigma_t[c]*T[c].
        float P_coll = channel_pdf[0]*c.sigma_t.x*T.x
                     + channel_pdf[1]*c.sigma_t.y*T.y
                     + channel_pdf[2]*c.sigma_t.z*T.z;
        if (!(P_coll > 0.0f)) { out.exited = false; return out; }
        tp = tp * (sigma_s * T) * (1.0f / P_coll);

        P = P + D * t;

        if (reduce_max(tp) < VOLUME_THROUGHPUT_EPSILON) {
            out.exited = false;      // absorbed / killed inside the medium
            out.throughput = Float3(0.0f);
            return out;
        }
    }
    out.exited = false;              // hit the bounce ceiling
    out.throughput = Float3(0.0f);
    return out;
}

}  // namespace bssrdf
}  // namespace astroray

#endif  // ASTRORAY_BSSRDF_RANDOM_WALK_H
