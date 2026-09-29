# Heterogeneous smoke grid (CPU | GPU)
Small smoke grid volume rendered on CPU and GPU (48x48 tiles scaled up).
Verdict: CPU and GPU agree in shape and brightness.
Test tests/test_pkg269_gpu_hetero_parity.py now writes to test_results/_runs/ (issue #861).
Provenance: pkg269 (GPU heterogeneous volumes), Batch K (PR #820), 2026-09.
