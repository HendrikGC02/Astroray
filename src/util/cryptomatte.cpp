// Cryptomatte infrastructure implementation
// References:
// - Cycles intern/cycles/kernel/film/cryptomatte_passes.h (Apache-2.0)

#include "astroray/cryptomatte.h"
#include "murmurhash3.h"

float crypto_hash_name(const std::string& name) {
    uint32_t hash;
    MurmurHash3_x86_32(name.c_str(), static_cast<int>(name.length()), 0, &hash);
    return hash_to_float(hash);
}

void crypto_insert(float* ranks, int depth, float id, float weight) {
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

void crypto_sort_ranks(float* ranks, int depth) {
    // Insertion sort by weight descending (adapted from Cycles)
    // Empty slots (id == CRYPTO_ID_NONE) will naturally bubble to the end
    for (int slot = 1; slot < depth; ++slot) {
        float id = ranks[slot * 2];
        float weight = ranks[slot * 2 + 1];

        if (id == CRYPTO_ID_NONE) {
            return; // All remaining slots are empty
        }

        // Insert current element into sorted portion
        int i = slot;
        while (i > 0 && weight > ranks[(i - 1) * 2 + 1]) {
            // Swap with previous element
            ranks[i * 2] = ranks[(i - 1) * 2];
            ranks[i * 2 + 1] = ranks[(i - 1) * 2 + 1];
            --i;
        }
        ranks[i * 2] = id;
        ranks[i * 2 + 1] = weight;
    }
}
