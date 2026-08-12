#pragma once
// GPU Sellmeier dispersion evaluator — device-callable wavelength-to-IOR.
// Only include this from .cu files compiled by nvcc.

#include "gpu_types.h"

// Sellmeier 1871 dispersion equation (public domain via age):
//   n²(λ) = 1 + B1·λ²/(λ²−C1) + B2·λ²/(λ²−C2) + B3·λ²/(λ²−C3)
// with λ in μm. Mirrors the CPU-side sellmeierIOR() in
// plugins/materials/dielectric.cpp. The clamp to max(1.0f, n2) guards
// against pathological coefficients outside the valid wavelength range
// (Sellmeier equations are curve-fits and can extrapolate to n<1).
//
// References:
// - Sellmeier 1871 — Annalen der Physik 219(11):272-282 (public domain)
// - Cycles intern/cycles/kernel/svm/closure_principled.h wavelength-dependent
//   IOR (Apache-2.0) — same closed form
// - PBRT-v4 src/pbrt/bxdfs.h DielectricBxDF (Apache-2.0)
__device__ inline float gpu_sellmeier_ior(const GDispersion& d, float lambda_nm) {
    float lam_um = lambda_nm * 1e-3f; // nm → μm
    float l2 = lam_um * lam_um;
    float n2 = 1.0f
             + (d.b1 * l2) / (l2 - d.c1)
             + (d.b2 * l2) / (l2 - d.c2)
             + (d.b3 * l2) / (l2 - d.c3);
    return sqrtf(fmaxf(1.0f, n2));
}

// pkg187 — Cauchy empirical dispersion n(λ) = A + B/λ² (λ in μm), the model
// Cycles' WIP Principled dispersion uses (Blender PR #162041,
// intern/cycles/kernel/closure/bsdf_microfacet.h bsdf_glass_ior; OpenPBR Surface
// v1.1.1 Eq. 55). For a dispersive Principled material the host packs the fit into
// GDispersion.b1 = A, b2 = B (see scene_upload.cu closure-graph branch); this is
// the device twin of PrincipledPlugin::iorAt. NOT called for Sellmeier dielectrics
// (those use gpu_sellmeier_ior above). Mirrors the CPU cauchyAB evaluation exactly.
__device__ inline float gpu_cauchy_ior(float A, float B, float lambda_nm) {
    float lam_um = lambda_nm * 1e-3f; // nm → μm
    return A + B / (lam_um * lam_um);
}
