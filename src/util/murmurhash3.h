// MurmurHash3 was written by Austin Appleby, and is placed in the public
// domain. The author hereby disclaims copyright to this source code.
//
// Adapted from smhasher MurmurHash3.cpp (public domain, Austin Appleby)
// https://github.com/aappleby/smhasher/blob/master/src/MurmurHash3.cpp

#pragma once

#include <cstdint>

// Platform-specific functions
#if defined(_MSC_VER)
#include <stdlib.h>
#define ROTL32(x, y) _rotl(x, y)
#else
inline uint32_t rotl32(uint32_t x, int8_t r) {
    return (x << r) | (x >> (32 - r));
}
#define ROTL32(x, y) rotl32(x, y)
#endif

// MurmurHash3_x86_32: produces a 32-bit hash for x86 platforms
// key: input data buffer
// len: length of input data in bytes
// seed: hash seed (use 0 for Cryptomatte per Psyop spec)
// out: pointer to uint32_t output
void MurmurHash3_x86_32(const void* key, int len, uint32_t seed, void* out);
