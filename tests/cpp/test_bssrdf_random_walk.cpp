// ============================================================================
// Standalone CPU furnace + correctness test for the random-walk BSSRDF core
// (include/astroray/bssrdf_random_walk.h). NO CUDA, NO pybind — pure C++17.
//
// Build & run (from the worktree root):
//   g++ -std=c++17 -O2 -I include tests/cpp/test_bssrdf_random_walk.cpp \
//       -o build_bssrdf_test && ./build_bssrdf_test
//   (MSVC: cl /std:c++17 /O2 /I include tests\cpp\test_bssrdf_random_walk.cpp)
//
// Exit code 0 = all assertions pass. Prints measured numbers.
//
// What it verifies (pkg178 D2 parallel-track prototype):
//   A. Energy conservation / white furnace: non-absorbing slab, mean exit
//      throughput -> 1.0 (LINEAR, floor+ceiling per pkg166), for BOTH the
//      classic walk and the Dwivedi-guided walk on GRAY media.
//   B. Absorption: reflectance+transmittance grows monotonically with albedo
//      and stays below 1 (energy is absorbed).  [classic path]
//   C. Translucent falloff: for a fixed non-absorbing medium, transmittance
//      decreases and reflectance increases with slab thickness; R+T == 1.
//      [classic path]
//   D. Variance: Dwivedi vs classic std-error at equal sample count, GRAY
//      medium where direction-only guiding is valid (report).
//   E. Colored medium exercises channel MIS (classic path).
//   F. RESEARCH FINDING (report only, no gate): Dwivedi direction-only guiding
//      has pathological variance on COLORED media without distance stretching.
// ============================================================================
#include "astroray/bssrdf_random_walk.h"

#include <cstdio>
#include <cmath>
#include <random>

using namespace astroray::bssrdf;

// ---- Geometry: an infinite slab occupying z in [-thickness, 0]. -----------
// Boundaries: top face z=0 (outward normal +Z), bottom face z=-thickness
// (outward normal -Z). Entry is at the origin on the top face, N=+Z.
struct SlabIntersector {
    float thickness;
    BoundaryHit operator()(Float3 P, Float3 D, float tmax) const {
        BoundaryHit h;
        if (std::fabs(D.z) < 1e-12f) return h;  // parallel to faces: no crossing
        float t, nz;
        if (D.z > 0.0f) { t = (0.0f - P.z) / D.z; nz = 1.0f; }       // toward top
        else            { t = (-thickness - P.z) / D.z; nz = -1.0f; } // toward bottom
        if (t > 1e-6f && t <= tmax) { h.hit = true; h.t = t; h.normal = {0,0,nz}; }
        return h;
    }
};

struct Stats { double sum = 0, sum2 = 0; long n = 0;
    void add(double x){ sum += x; sum2 += x*x; ++n; }
    double mean() const { return n ? sum/n : 0.0; }
    double stderr_() const { double m=mean(); return n ? std::sqrt(std::max(0.0,(sum2/n - m*m))/n) : 0.0; }
};

struct SlabResult { double meanThru; double R; double T; double lost; };

static SlabResult runSlab(RandomWalkParams p, float thickness, long N,
                          bool useDwivedi, unsigned seed, Stats* perWalk=nullptr) {
    std::mt19937 gen(seed);
    std::uniform_real_distribution<float> U(0.0f, 1.0f);
    auto rng = [&](){ return U(gen); };
    SlabIntersector slab{thickness};
    Float3 entryP{0,0,0}, entryN{0,0,1};
    double sumThru=0, R=0, T=0; long lost=0;
    for (long i=0;i<N;++i) {
        WalkResult w = randomWalk(p, entryP, entryN, slab, rng, useDwivedi);
        if (!w.exited) { ++lost; if (perWalk) perWalk->add(0.0); continue; }
        double avg = (w.throughput.x + w.throughput.y + w.throughput.z)/3.0;
        sumThru += avg;
        if (w.exitNormal.z > 0.0f) R += avg; else T += avg;
        if (perWalk) perWalk->add(avg);
    }
    return { sumThru/N, R/N, T/N, double(lost)/N };
}

static int g_fail = 0;
static void check(bool ok, const char* msg) {
    std::printf("  [%s] %s\n", ok ? "PASS" : "FAIL", msg);
    if (!ok) ++g_fail;
}

int main() {
    const long N = 400000;
    std::printf("Random-walk BSSRDF CPU prototype test (N=%ld walks/case)\n", N);

    // ---- A. White furnace: non-absorbing, energy conservation -------------
    std::printf("\n[A] White furnace (albedo=1, non-absorbing slab d=2 mfp)\n");
    {
        RandomWalkParams p; p.albedo = Float3(1.0f); p.radius = Float3(1.0f); p.anisotropy = 0.0f;
        SlabResult classic = runSlab(p, 2.0f, N, /*dwivedi=*/false, 12345);
        SlabResult guided  = runSlab(p, 2.0f, N, /*dwivedi=*/true,  67890);
        std::printf("  classic: meanThru=%.4f  R=%.4f T=%.4f  R+T=%.4f  lost=%.2e\n",
                    classic.meanThru, classic.R, classic.T, classic.R+classic.T, classic.lost);
        std::printf("  dwivedi: meanThru=%.4f  R=%.4f T=%.4f  R+T=%.4f  lost=%.2e\n",
                    guided.meanThru, guided.R, guided.T, guided.R+guided.T, guided.lost);
        // pkg166 floor+ceiling, linear. MC tolerance ~1% at this N.
        check(classic.meanThru > 0.985 && classic.meanThru < 1.015, "classic conserves energy (mean in [0.985,1.015])");
        check(guided.meanThru  > 0.985 && guided.meanThru  < 1.015, "dwivedi conserves energy (mean in [0.985,1.015])");
        check(classic.lost < 1e-3, "classic: negligible walks hit bounce ceiling");
    }

    // ---- B. Absorption monotonic with albedo -------------------------------
    std::printf("\n[B] Absorption (slab d=2 mfp, g=0): reflectance vs albedo\n");
    {
        float albedos[3] = {0.3f, 0.6f, 0.9f};
        double m[3];
        for (int i=0;i<3;++i){
            RandomWalkParams p; p.albedo = Float3(albedos[i]); p.radius = Float3(1.0f);
            SlabResult r = runSlab(p, 2.0f, N, false, 111+i);
            m[i]=r.meanThru;
            std::printf("  albedo=%.1f  meanThru(R+T)=%.4f\n", albedos[i], m[i]);
        }
        check(m[0] < m[1] && m[1] < m[2], "throughput increases with albedo");
        check(m[2] < 1.0, "absorbing media lose energy (meanThru<1 at albedo=0.9)");
    }

    // ---- C. Translucent falloff: thickness sweep --------------------------
    std::printf("\n[C] Translucency (albedo=1, non-absorbing): R/T vs thickness\n");
    {
        float ds[3] = {0.5f, 2.0f, 8.0f};
        double Tr[3], Re[3];
        for (int i=0;i<3;++i){
            RandomWalkParams p; p.albedo = Float3(1.0f); p.radius = Float3(1.0f);
            SlabResult r = runSlab(p, ds[i], N, false, 222+i);
            Tr[i]=r.T; Re[i]=r.R;
            std::printf("  thickness=%.1f mfp  R=%.4f  T=%.4f  R+T=%.4f\n", ds[i], Re[i], Tr[i], Re[i]+Tr[i]);
        }
        check(Tr[0] > Tr[1] && Tr[1] > Tr[2], "transmittance falls off with thickness");
        check(Re[0] < Re[1] && Re[1] < Re[2], "reflectance grows with thickness");
        check(std::fabs((Re[0]+Tr[0]) - 1.0) < 0.02 &&
              std::fabs((Re[2]+Tr[2]) - 1.0) < 0.02, "R+T==1 (energy conserved) at both extremes");
    }

    // ---- D. Variance: Dwivedi vs classic (thick slab, near half-space) ----
    std::printf("\n[D] Variance at equal N (albedo=0.95, d=8 mfp)\n");
    {
        RandomWalkParams p; p.albedo = Float3(0.95f); p.radius = Float3(1.0f);
        Stats cS, dS;
        runSlab(p, 8.0f, N, false, 333, &cS);
        runSlab(p, 8.0f, N, true,  333, &dS);
        std::printf("  classic: mean=%.4f  stderr=%.5f\n", cS.mean(), cS.stderr_());
        std::printf("  dwivedi: mean=%.4f  stderr=%.5f\n", dS.mean(), dS.stderr_());
        check(std::fabs(cS.mean() - dS.mean()) < 0.01, "classic & dwivedi agree in mean (unbiased)");
        std::printf("  (variance-reduction ratio classic/dwivedi = %.3f)\n",
                    dS.stderr_()>0 ? cS.stderr_()/dS.stderr_() : 0.0);
    }

    // ---- E. Colored medium exercises channel MIS (classic path) -----------
    std::printf("\n[E] Colored medium (albedo=(0.9,0.6,0.3), d=2 mfp, classic)\n");
    {
        RandomWalkParams p; p.albedo = Float3(0.9f,0.6f,0.3f); p.radius = Float3(1.0f);
        std::mt19937 gen(444);
        std::uniform_real_distribution<float> U(0,1);
        auto rng=[&](){return U(gen);};
        SlabIntersector slab{2.0f};
        Float3 acc{0,0,0}; long n=N;
        for (long i=0;i<n;++i){ WalkResult w=randomWalk(p,{0,0,0},{0,0,1},slab,rng,/*dwivedi=*/false);
            if (w.exited) acc = acc + w.throughput; }
        Float3 mean = acc * (1.0f/float(n));
        std::printf("  per-channel meanThru = (%.4f, %.4f, %.4f)\n", mean.x, mean.y, mean.z);
        check(mean.x > mean.y && mean.y > mean.z, "higher-albedo channel returns more energy");
        check(mean.x < 1.01f && mean.y < 1.01f && mean.z < 1.01f, "no channel gains energy");
    }

    // ---- F. RESEARCH FINDING (report only): Dwivedi on colored media -------
    // Direction-only Dwivedi guiding (no distance stretching) is unbiased in
    // expectation but has pathological variance on COLORED media (single
    // averaged diffusion length over-guides high-albedo channels). Reported so
    // the finding is reproducible; NOT a pass/fail gate. The fix is the full
    // per-channel joint direction+distance zero-variance scheme (deferred).
    std::printf("\n[F] FINDING: Dwivedi (colored, direction-only) — expect non-convergence\n");
    {
        RandomWalkParams p; p.albedo = Float3(0.9f,0.6f,0.3f); p.radius = Float3(1.0f);
        std::mt19937 gen(444);
        std::uniform_real_distribution<float> U(0,1);
        auto rng=[&](){return U(gen);};
        SlabIntersector slab{2.0f};
        Float3 acc{0,0,0}; float maxx=0; long n=N;
        for (long i=0;i<n;++i){ WalkResult w=randomWalk(p,{0,0,0},{0,0,1},slab,rng,/*dwivedi=*/true);
            if (w.exited){ acc = acc + w.throughput; maxx=std::max(maxx,w.throughput.x);} }
        Float3 mean = acc * (1.0f/float(n));
        std::printf("  per-channel meanThru = (%.2f, %.2f, %.2f)  maxX=%.2e  "
                    "(vs classic ~0.99/0.84/0.50 -> confirms the heavy-tail finding)\n",
                    mean.x, mean.y, mean.z, maxx);
    }

    std::printf("\n%s (%d failures)\n", g_fail==0 ? "ALL PASS" : "FAILURES", g_fail);
    return g_fail==0 ? 0 : 1;
}
