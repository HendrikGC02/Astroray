# cuobjdump resource table, batchS 49ff1efe vs main build_cuda (916907b engine)

Kernels: 385 main / 385 batchS. stageShadeBucketedKernel: 128/128 instantiations identical (REG 254, STACK unchanged).

Changed (all call gpu_material_emitted):

| kernel | REG main -> batchS | STACK main -> batchS |
|---|---|---|
| astroray::wavefront::stageShadeNeeMisKernel<false> | 254 -> 254 | 4280 -> 4248 |
| astroray::wavefront::stageShadeNeeMisKernel<true> | 254 -> 254 | 8376 -> 8344 |
| astroray::wavefront::stageShadowKernel<false, true, false> | 121 -> 122 | 584 -> 584 |
| astroray::wavefront::stageShadowKernel<false, false, true> | 109 -> 110 | 864 -> 864 |
| astroray::wavefront::stageShadowKernel<false, true, true> | 117 -> 116 | 864 -> 864 |
| astroray::wavefront::stageShadowKernel<true, false, true> | 158 -> 158 | 1848 -> 1832 |
| astroray::wavefront::stageIntersectQueuedKernel<false, false, false, false> | 125 -> 132 | 616 -> 584 |
| astroray::wavefront::stageIntersectQueuedKernel<false, true, false, false> | 127 -> 133 | 616 -> 584 |
| astroray::wavefront::stageIntersectQueuedKernel<true, false, false, false> | 135 -> 140 | 632 -> 600 |
| astroray::wavefront::stageIntersectQueuedKernel<true, true, false, false> | 137 -> 141 | 632 -> 600 |
| astroray::wavefront::stageIntersectQueuedKernel<false, false, true, false> | 158 -> 158 | 1704 -> 1672 |
| astroray::wavefront::stageIntersectQueuedKernel<false, true, true, false> | 158 -> 158 | 1704 -> 1672 |
| astroray::wavefront::stageIntersectQueuedKernel<false, false, false, true> | 134 -> 136 | 944 -> 944 |
| astroray::wavefront::stageIntersectQueuedKernel<false, true, false, true> | 136 -> 134 | 944 -> 944 |

Everything else is byte-identical in REG/STACK/SHARED/LOCAL (anonymous-namespace hashes normalised; 7 renamed kernels checked by hand).
