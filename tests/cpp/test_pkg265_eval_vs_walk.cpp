// ============================================================================
// pkg265 Phase 10 — eval-vs-sample cross-check for the Heitz-2016 (Eq 42)
// stochastic evaluation shipped in include/astroray/microsurface_dielectric.h.
//
// The walk `sampleWalk` is a perfect importance sampler for the lossless
// dielectric, so its escape density IS the BSDF: p_walk(wi) = f(wo,wi)|cos wi|
// in direction-space units (the eta^2 radiance compression is applied
// separately, see stochasticEvalHashed / test_pkg265_walk_eta.cpp). Therefore
//
//     integral over the upper hemisphere of stochasticEval  ==  R  (walk),
//     integral over the lower hemisphere of stochasticEval  ==  T  (walk),
//
// which is what this test measures. The eval integral uses a STRATIFIED
// uniform-sphere estimator (jittered NxN grid over (cos theta, phi)), one
// hash-seeded walk per direction — i.e. exactly the estimator the materials
// call, so a scaling or frame bug in stochasticEvalHashed shows up here.
//
// The C++ numbers are compared against the numpy oracle's Phase 9 table in
// .astroray_plan/docs/pkg265-multiscatter-microfacet-research.md (uniform-sphere
// MC vs the walk R/T), which this reproduces independently in the engine.
//
// Tolerance: uniform-sphere integration of a peaked BTDF is variance-limited
// (research note Phase 9 — a +-2% gate at low roughness needs an
// importance-sampled integrator, which uniform-sphere MC cannot reach at
// feasible sample counts). The gate is therefore +-12% at r >= 0.85 (the broad
// multiple-scattering regime this package exists for) and +-30% at r = 0.5,
// with the measured values printed either way. R+T from the eval must also
// stay within +-10% of 1 (the model is lossless).
//
// Build & run (from the worktree root, MSVC in a vcvars shell):
//   cl /std:c++17 /O2 /EHsc /I include tests\cpp\test_pkg265_eval_vs_walk.cpp \
//      /Fe:build_eval_vs_walk_test.exe && build_eval_vs_walk_test.exe
// Exit code 0 = all assertions pass.
// ============================================================================
#include "astroray/microsurface_dielectric.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <random>
#include <vector>

// Vec3 is a global type in raytracer.h (not in namespace astroray).
namespace md = astroray::msdiel;

struct WalkRT {
    double R = 0.0, T = 0.0, dead = 0.0;
};

static WalkRT walkRT(const Vec3& wo, float alpha, float ior, bool entering,
                     long n, std::mt19937& gen) {
    std::uniform_real_distribution<float> dist(0.0f, 1.0f);
    auto rng = [&]() { return dist(gen); };
    long r = 0, t = 0, d = 0;
    for (long i = 0; i < n; ++i) {
        md::WalkSample w = md::sampleWalk(wo, alpha, ior, entering, rng,
                                          md::kMsScatterMax);
        if (!w.escaped) { ++d; continue; }
        if (w.reflected) ++r; else ++t;
    }
    WalkRT out;
    out.R = double(r) / double(n);
    out.T = double(t) / double(n);
    out.dead = double(d) / double(n);
    return out;
}

struct EvalRT {
    double R = 0.0, T = 0.0, maxSample = 0.0, semR = 0.0, semT = 0.0;
};

// Stratified uniform-sphere estimate of the two hemisphere integrals.
static EvalRT evalRT(const Vec3& wo, float alpha, float ior, bool entering,
                     int nMu, int nPhi, std::mt19937& gen) {
    std::uniform_real_distribution<float> dist(0.0f, 1.0f);
    const double solid = 4.0 * M_PI;
    const long n = long(nMu) * long(nPhi);
    double sumR = 0.0, sumT = 0.0, sum2R = 0.0, sum2T = 0.0, mx = 0.0;
    for (int i = 0; i < nMu; ++i) {
        for (int j = 0; j < nPhi; ++j) {
            double u = (i + dist(gen)) / double(nMu);
            double v = (j + dist(gen)) / double(nPhi);
            double z = 1.0 - 2.0 * u;                       // uniform on [-1,1]
            double rxy = std::sqrt(std::max(0.0, 1.0 - z * z));
            double phi = 2.0 * M_PI * v;
            Vec3 wi(float(rxy * std::cos(phi)), float(rxy * std::sin(phi)), float(z));
            md::HashRng rng = md::hashRngFor(wo, wi, alpha, ior, entering);
            float e = md::stochasticEval(wo, wi, alpha, ior, entering, rng,
                                         md::kMsScatterMax);
            if (!(e > 0.0f) || !std::isfinite(e)) e = 0.0f;
            mx = std::max(mx, double(e));
            if (z > 0.0) { sumR += e; sum2R += double(e) * double(e); }
            else         { sumT += e; sum2T += double(e) * double(e); }
        }
    }
    EvalRT out;
    out.R = solid * sumR / double(n);
    out.T = solid * sumT / double(n);
    out.maxSample = mx;
    out.semR = solid * std::sqrt(std::max(0.0, sum2R / n - (sumR / n) * (sumR / n))
                                 / double(n));
    out.semT = solid * std::sqrt(std::max(0.0, sum2T / n - (sumT / n) * (sumT / n))
                                 / double(n));
    return out;
}

int main() {
    std::mt19937 gen(20260909u);
    const float ior = 1.45f;
    const long nWalk = 200000;
    const int nMu = 900, nPhi = 900;           // 810k stratified directions

    struct Cell { float r, mu; float tol; };
    const Cell cells[] = {
        {0.85f, 0.1f, 0.12f}, {0.85f, 0.5f, 0.12f}, {0.85f, 0.9f, 0.12f},
        {1.00f, 0.1f, 0.12f}, {1.00f, 0.9f, 0.12f},
        {0.50f, 0.5f, 0.30f}, {0.50f, 0.9f, 0.30f},
    };

    int fails = 0;
    std::printf("pkg265 eval(Eq 42) vs walk R/T  (ior=%.2f, %ld walks, %d x %d "
                "stratified dirs)\n", ior, nWalk, nMu, nPhi);
    std::printf("   r   mu | walk R  walk T | eval R  eval T |  errR    errT | "
                "R+T   maxSample\n");
    for (const Cell& c : cells) {
        float alpha = std::max(c.r * c.r, 0.0064f);
        float st = std::sqrt(std::max(0.0f, 1.0f - c.mu * c.mu));
        Vec3 wo(st, 0.0f, c.mu);
        WalkRT w = walkRT(wo, alpha, ior, /*entering=*/true, nWalk, gen);
        EvalRT e = evalRT(wo, alpha, ior, true, nMu, nPhi, gen);
        double errR = (w.R > 1e-4) ? (e.R - w.R) / w.R : 0.0;
        double errT = (w.T > 1e-4) ? (e.T - w.T) / w.T : 0.0;
        double sum = e.R + e.T;
        std::printf("%5.2f %4.2f | %6.4f  %6.4f | %6.4f  %6.4f | %+6.1f%% %+6.1f%% | "
                    "%5.3f  %8.2f\n",
                    c.r, c.mu, w.R, w.T, e.R, e.T, 100.0 * errR, 100.0 * errT,
                    sum, e.maxSample);
        if (std::abs(errR) > c.tol) {
            std::printf("  FAIL: reflection integral off by %+.1f%% (tol %.0f%%)\n",
                        100.0 * errR, 100.0 * c.tol);
            ++fails;
        }
        if (std::abs(errT) > c.tol) {
            std::printf("  FAIL: transmission integral off by %+.1f%% (tol %.0f%%)\n",
                        100.0 * errT, 100.0 * c.tol);
            ++fails;
        }
        if (std::abs(sum - 1.0) > 0.10) {
            std::printf("  FAIL: eval R+T = %.3f, the lossless dielectric must "
                        "integrate to 1\n", sum);
            ++fails;
        }
        // scatterMax = 16 truncation. Measured worst cell r1.0/mu0.1: 1 walk in
        // 200,000 (0.0005%) -- an energy sink of 5e-6, three orders below the
        // integration error above. Gated at 0.01% so a regression that raises it
        // (e.g. a scatterMax cut) is still caught.
        if (w.dead > 1e-4) {
            std::printf("  FAIL: walk dead fraction %.4f%% (scatterMax truncation)\n",
                        100.0 * w.dead);
            ++fails;
        }
    }
    if (fails) {
        std::printf("FAILED: %d assertion(s)\n", fails);
        return 1;
    }
    std::printf("PASS: the stochastic eval integrates to the walk's own R/T split.\n");
    return 0;
}
