#pragma once
// pkg113 Phase 2 — GPU photon EMISSION + BOUNCE → deposit.
//
// The GPU port of the GENERAL deterministic-refraction path of the CPU forward
// light tracer (plugins/integrators/light_tracer_caustic.cpp, lines 276-326): a
// batch of collimated-sun photons is traced through a flagged glass caster
// (Snell refraction + Schlick-Fresnel reflect/transmit + enter/exit from the
// geometric-normal sign + per-λ Sellmeier iorAt + TIR) and the surviving per-λ
// CIE flux is deposited as GPhoton records on the receiver. The Phase-1 store
// (gpu_photon_store.h) then ingests these GPhotons. EMISSION + BOUNCE only — NO
// integrator gather wiring (Phase 3).
//
// Flat-prism decision (pkg113 Phase 2, see
// .astroray_plan/docs/pkg113-phase2-photon-emission-research.md): the flat-prism
// explicit 2-face path STAYS CPU-only. The general deterministic loop ported
// here covers the glass SPHERE (the spec's primary GPU caustic target) and any
// solid/curved caster; the 2-face path depends on host-side geometry
// classification not uploaded to the GPU, and the general loop on a flat 2-quad
// caster scatters into chromatic noise (CPU header l.20-23, memory
// [[general-photon-loop-needs-solid-glass]]).
//
// Citations (CLAUDE.md §6; see the research note above):
//   Arvo 1986 (forward light transport); Jensen 1996 (diffuse photon deposit);
//   Schlick 1994 (Fresnel approximation); Sellmeier 1871 (n(λ), REUSED via
//   gpu_dispersion.cuh's gpu_sellmeier_ior, pkg64-gpu upload); CIE 1964 10° CMF
//   (data/spectra/cie_cmf.inc, the same table src/spectrum.cpp uses).
//
// Mirrors the Phase-1 host-callable pattern (cuda_photon_store_query): a
// host-callable entry the pybind binding reaches under #ifdef
// ASTRORAY_CUDA_ENABLED, used by tests/test_gpu_photon_emission.py to gate the
// GPU deposit set against a numpy float64 oracle (aggregate energy/position
// bounds — NOT bit-exact, the trace is a stochastic forward trace).

#include "astroray/gpu_photon_store.h"   // GPhoton (deposit target)
#include "astroray/gpu_types.h"          // GVec3, GDispersion

#include <vector>

namespace astroray {
namespace photon {
namespace gpu {

// A single-glass-sphere forward-trace scene description for the Phase-2 parity
// harness. Deliberately minimal (one sphere + one flat receiver plane + a
// collimated sun): the parity test isolates the refraction/deposit MATH, not the
// full scene-upload path (that is exercised separately by the integrator wiring
// in Phase 3). The aperture is a deterministic jittered lattice (NOT curand) so
// the oracle can feed the SAME entry samples and the comparison isolates the
// math from Monte-Carlo noise — the same "inject the same samples both sides"
// tactic sms_attempt_device.cuh uses for its Phase-1 unit test.
struct PhotonEmitSphereScene {
    GVec3       sphereCenter;
    float       sphereRadius;
    GDispersion dispersion;    // Sellmeier coefficients (pkg64-gpu); B*=C*=0 => flat IOR
    float       flatIor;       // used when dispersion is all-zero (non-dispersive glass)
    bool        isDispersive;  // true => use gpu_sellmeier_ior, false => flatIor

    GVec3       sunDir;        // collimated propagation direction (unit, toward the sphere)
    GVec3       apertureCenter;// center of the entry aperture disc (in front of the sphere)
    float       apertureRadius;// disc radius spanning the sphere's projected extent

    float       receiverY;     // y of the horizontal diffuse receiver plane (normal +y)

    int         apertureN;     // sqrt of the photon count: photons = apertureN*apertureN
    float       lambdaMin;     // emission band lower bound (nm), e.g. 380
    float       lambdaMax;     // emission band upper bound (nm), e.g. 720
    int         maxDepth;      // max refraction bounces through the glass (CPU maxDepth_)
};

// One deposited photon read back to the host (the GPU deposit set).
struct PhotonEmitDeposit {
    GVec3 position;   // world-space deposit point on the receiver
    GVec3 power;      // CIE XYZ flux (cmf(λ) * accumulated transmittance)
    float lambda;     // sampled wavelength (nm)
};

// Forward-trace apertureN*apertureN photons through the single glass sphere onto
// the receiver plane and return the surviving deposit set. The aperture is a
// deterministic apertureN*apertureN jittered lattice (stratified jitter from a
// fixed hash, NOT curand) so the parity oracle can reproduce the exact entry
// samples. Photons that miss the sphere, TIR out, or never reach the receiver
// are dropped (deposit set is the survivors, like the CPU `photons` vector).
std::vector<PhotonEmitDeposit> cuda_photon_emit_sphere(
    const PhotonEmitSphereScene& scene);

}  // namespace gpu
}  // namespace photon
}  // namespace astroray
