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
void crypto_insert(float* ranks, int depth, float id, float weight);

// crypto_sort_ranks: Sort ranked histogram by weight descending
// Adapted from Cycles film_sort_cryptomatte_slots (Apache-2.0)
//
// ranks: flat array of [id0, weight0, id1, weight1, ...]
// depth: number of (id, weight) pairs
//
// Uses insertion sort (depth is small, typically 6).
// Empty slots (id == CRYPTO_ID_NONE) bubble to the end.
void crypto_sort_ranks(float* ranks, int depth);
