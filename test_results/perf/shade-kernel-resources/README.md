# Shade kernel register / stack cost of the GPU emission fix
cuobjdump resource usage, main vs the fix: only kernels that call gpu_material_emitted changed.
Verdict: the REG:254 stageShadeBucketedKernel is untouched (128/128 instantiations identical); the 14 changed
kernels move by at most +7 registers and -32 stack bytes.
Provenance: Batch S (issue #835/#843), sm_120, 2026-09-20.
