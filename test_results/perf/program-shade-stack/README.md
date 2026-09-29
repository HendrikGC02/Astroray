# stageShadeBucketed HasProgram resources (main vs Batch R)
REG / STACK per template instantiation of the op-VM shade kernel.
Verdict: no change. All 64 instantiations stay at REG 254 with identical stack (4512-8736 bytes);
the only new symbol is gpu_progInputTexel.
Provenance: Batch R (build 0f4f62d1 vs main .pyd), sm_120, 2026-09-19.
