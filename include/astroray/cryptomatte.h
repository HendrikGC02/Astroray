// Cryptomatte infrastructure for Astroray
// References:
// - Psyop Cryptomatte Specification v1.2.0 (BSD-3-Clause)
// - Cycles intern/cycles/kernel/film/cryptomatte_passes.h (Apache-2.0)
// - alShaders2 cryptomatte/cryptomatte.h (Apache-2.0)

#pragma once

#include <cstdint>
#include <cstring>
#include <string>

// Per-pixel cryptomatte sample: (hashed_id, coverage_weight)
struct CryptoSample {
    float id;
    float weight;
};

// Sentinel value for empty crypto slots
constexpr float CRYPTO_ID_NONE = 0.0f;

// hash_to_float: Convert uint32 hash to IEEE 754 float with subnormal/inf guard
// Adapted from alShaders2 cryptomatte.h (Apache-2.0)
// https://github.com/anderslanglands/alShaders2/blob/master/cryptomatte/cryptomatte.h
//
// If all exponent bits are 0 (subnormals, +zero, -zero), set exponent to 1.
// If all exponent bits are 1 (NaNs, +inf, -inf), set exponent to 254.
// This ensures the float ID can round-trip through EXR without hitting
// problematic IEEE 754 special values.
inline float hash_to_float(uint32_t hash) {
    uint32_t exponent = (hash >> 23) & 255;
    if (exponent == 0 || exponent == 255) {
        hash ^= 1 << 23; // toggle bit 23
    }
    float f;
    std::memcpy(&f, &hash, 4);
    return f;
}

// crypto_hash_name: Hash a name string to a Cryptomatte float ID
// Uses MurmurHash3_x86_32 with seed 0, per Psyop spec
float crypto_hash_name(const std::string& name);

// crypto_insert: Insert (id, weight) into a ranked histogram
// Adapted from Cycles film_write_cryptomatte_slots (Apache-2.0)
// https://projects.blender.org/blender/blender/src/branch/main/intern/cycles/kernel/film/cryptomatte_passes.h
//
// ranks: flat array of [id0, weight0, id1, weight1, ..., id_{depth-1}, weight_{depth-1}]
// depth: number of (id, weight) pairs in the array
// id: hashed ID to insert
// weight: coverage weight to accumulate
//
// Algorithm:
// 1. Search for an empty slot (id == CRYPTO_ID_NONE) or matching id.
// 2. If empty slot found, insert (id, weight) and break.
// 3. If matching id found, accumulate weight and break.
// 4. If last slot reached, accumulate weight there (overflow bucket).
//
// Note: This function does NOT sort. Call crypto_sort_ranks() after all insertions.
// pkg87b: Made __host__ __device__ for CPU/GPU shared codepath.
#ifdef __CUDACC__
__host__ __device__
#endif
inline void crypto_insert(float* ranks, int depth, float id, float weight) {
    if (weight == 0.0f) {
        return;
    }

    // Search for empty slot or matching id
    for (int slot = 0; slot < depth; slot++) {
        float slot_id = ranks[slot * 2];

        // Empty slot found - insert here
        if (slot_id == CRYPTO_ID_NONE) {
            ranks[slot * 2] = id;
            ranks[slot * 2 + 1] = weight;
            return;
        }

        // Matching id found - accumulate weight
        if (slot_id == id) {
            ranks[slot * 2 + 1] += weight;
            return;
        }

        // Last slot reached - accumulate here (overflow bucket)
        if (slot == depth - 1) {
            ranks[slot * 2 + 1] += weight;
            return;
        }
    }
}

// crypto_sort_ranks: Sort ranked histogram by weight descending
// Adapted from Cycles film_sort_cryptomatte_slots (Apache-2.0)
//
// ranks: flat array of [id0, weight0, id1, weight1, ...]
// depth: number of (id, weight) pairs
//
// Uses insertion sort (depth is small, typically 6).
// Empty slots (id == CRYPTO_ID_NONE) bubble to the end.
void crypto_sort_ranks(float* ranks, int depth);

// crypto_accumulate_shade_point: Accumulate cryptomatte data at a shade point
// Adapted from Cycles kernel_write_data_passes (Apache-2.0)
// https://projects.blender.org/blender/blender/src/branch/main/intern/cycles/kernel/integrator/shade_surface.h
//
// Weight computation per Cycles film_write_cryptomatte_slots:
//   weight = average(throughput · bsdf_eval)
// where throughput is the path throughput *before* this BSDF interaction,
// and bsdf_eval is the BSDF response at this vertex. Component-wise product
// averaged over RGB channels (Cycles uses average() on float3).
//
// Parameters:
//   objectRanks, materialRanks: per-pixel rank arrays (width*height*depth*2 floats)
//   pixelIndex: linear pixel index (y*width + x)
//   depth: number of (id, weight) pairs per pixel (typically 6)
//   objectId, materialId: hashed Cryptomatte float IDs
//   weight: Cycles-style coverage weight = average(throughput · bsdf_eval)
//
// pkg87b: Shared __host__ __device__ helper so CPU and GPU integrators use
// identical accumulation logic (prevents CPU/GPU crypto mismatch).
#ifdef __CUDACC__
__host__ __device__
#endif
inline void crypto_accumulate_shade_point(
    float* objectRanks,
    float* materialRanks,
    int pixelIndex,
    int depth,
    float objectId,
    float materialId,
    float weight)
{
    if (weight <= 0.0f) {
        return;
    }
    int offset = pixelIndex * depth * 2;
    crypto_insert(objectRanks + offset, depth, objectId, weight);
    crypto_insert(materialRanks + offset, depth, materialId, weight);
}
