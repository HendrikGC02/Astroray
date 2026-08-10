#pragma once
// pkg178 Stage 4 PR-3 — GPU upload of the Rec.709-baked thin-film CIE
// sensitivity LUT (astroray::thinfilm::kThinFilmCieTable, thin_film_cie_table.h).
//
// The RGB legs of the thin-film iridescence Fresnel (gpu_materials.h
// gpu_pr_thinFilm*RGB / *Spectral-conductor) need the [512][6] CIE sensitivity
// table on-device. It lives in device GLOBAL memory (not __constant__), uploaded
// once by uploadThinFilmTable() — mirrors the pkg151 glass / pkg152 ggx table
// pattern in gpu_ggx_tables.cuh/.cu EXACTLY (same rationale: gpu_materials.h is
// included by many .cu translation units, so a single extern global pointer
// avoids constant-memory duplication / device-linker multiple-definition errors).
//
// Same data + citations as include/astroray/thin_film_cie_table.h (Cycles
// table_thin_film_cmf, Apache-2.0; Belcour & Barla 2017). Layout [512][6] =
// {re_R, re_G, re_B, im_R, im_G, im_B}, flattened row-major for the device copy.
//
// Only include this from .cu files compiled by nvcc.

#include "gpu_types.h"
#include "thin_film_fresnel.h"
#include <cuda_runtime.h>

// Defined once in gpu_thin_film_table.cu; populated by uploadThinFilmTable().
// Flat [512*6] row-major (== kThinFilmCieTable[512][6]).
extern __device__ const float* g_thinFilmCie;

// Host-callable one-time upload (defined in gpu_thin_film_table.cu); copies the
// same host-side kThinFilmCieTable data the CPU sensitivityRGB reads.
void uploadThinFilmTable();

// Device sensitivity provider (RGB leg) — reinterprets the flat device pointer
// back into [.][6] and forwards to the SHARED core (thin_film_fresnel.h
// sensitivityRGB), so the GPU RGB leg is byte-identical to the CPU one.
__device__ inline astroray::thinfilm::TFComplex gpu_pr_sensitivityRGB(float argOPD, int channel) {
    return astroray::thinfilm::sensitivityRGB(
        argOPD, channel, reinterpret_cast<const float (*)[6]>(g_thinFilmCie));
}
