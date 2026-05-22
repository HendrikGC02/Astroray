// Cryptomatte pass plugin — normalisation (pkg87c)
// References:
// - Cycles intern/cycles/kernel/film/cryptomatte_passes.h film_cryptomatte_post (Apache-2.0)
// - Psyop Cryptomatte Specification v1.2.0 §2 weight normalization (BSD-3-Clause)

#include "astroray/pass.h"
#include "astroray/register.h"
#include "astroray/cryptomatte.h"
#include <cstring>

class CryptomattePass : public Pass {
public:
    explicit CryptomattePass(const astroray::ParamDict&) {}

    std::string name() const override { return "Cryptomatte"; }

    void execute(Framebuffer& fb) override {
        float* objBuf = fb.buffer("crypto_object");
        float* matBuf = fb.buffer("crypto_material");
        if (!objBuf || !matBuf) {
            return;  // Crypto passes not enabled
        }

        int width = fb.width();
        int height = fb.height();
        int depth = fb.cryptomatteDepth();  // typically 6

        // Step 1: Sort each pixel's ranks weight-descending
        // Per Cycles film_cryptomatte_post (Apache-2.0): sorting happens before normalization.
        for (int y = 0; y < height; ++y) {
            for (int x = 0; x < width; ++x) {
                int pixelOffset = (y * width + x) * depth * 2;
                crypto_sort_ranks(objBuf + pixelOffset, depth);
                crypto_sort_ranks(matBuf + pixelOffset, depth);
            }
        }

        // Step 2: Normalize per-pixel weights (Σ weight = 1 on hit pixels, 0 on sky)
        // Per Cycles film_cryptomatte_post, normalisation happens after sorting.
        for (int y = 0; y < height; ++y) {
            for (int x = 0; x < width; ++x) {
                int pixelOffset = (y * width + x) * depth * 2;

                // Object normalization
                float objSum = 0.0f;
                for (int rank = 0; rank < depth; ++rank) {
                    objSum += objBuf[pixelOffset + rank * 2 + 1];
                }
                if (objSum > 0.0f) {
                    for (int rank = 0; rank < depth; ++rank) {
                        objBuf[pixelOffset + rank * 2 + 1] /= objSum;
                    }
                }

                // Material normalization
                float matSum = 0.0f;
                for (int rank = 0; rank < depth; ++rank) {
                    matSum += matBuf[pixelOffset + rank * 2 + 1];
                }
                if (matSum > 0.0f) {
                    for (int rank = 0; rank < depth; ++rank) {
                        matBuf[pixelOffset + rank * 2 + 1] /= matSum;
                    }
                }
            }
        }

        // Note: Channel packing + EXR emission happens in Blender addon (blender_module.cpp),
        // which reads the normalised crypto buffers and writes them to RenderResult passes.
        // The pass plugin only sorts and normalises the ranked histograms.
    }
};

ASTRORAY_REGISTER_PASS("cryptomatte", CryptomattePass)
