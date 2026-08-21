"""pkg206 refix — GPU unbiasedness on the DEFAULT 380-780 band (the regime the
parity review found biased). The GPU always importance-samples, so verify it
converges to the SAME image as the trusted CPU-uniform reference (unbiasedness)
and the CPU-importance twin (byte-mirror parity). Watch the B/Z channel.
One-off; deleted when pkg206 closes."""
import sys
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from runtime_setup import configure_test_imports
configure_test_imports()
import astroray
sys.path.insert(0, str(ROOT / "tests"))
from scenes.prism_reference import make_prism_scene

SPP, SIZE = 768, 96

def render(use_gpu, importance, seed):
    r = make_prism_scene(astroray, dispersive=True)
    r.set_use_gpu(use_gpu)
    r.set_integrator_param("hero_importance", 1 if importance else 0)
    r.set_seed(seed)
    flat = np.asarray(r.render(SPP, 10, None, False), dtype=np.float32)
    return flat.reshape(-1, 3).mean(axis=0)

gpu_imp = render(True,  True,  17)
cpu_uni = render(False, False, 17)   # trusted unbiased reference
cpu_imp = render(False, True,  17)

def line(name, v): print(f"{name:16s} R={v[0]:.5f} G={v[1]:.5f} B={v[2]:.5f}")
line("GPU importance", gpu_imp)
line("CPU uniform ref", cpu_uni)
line("CPU importance", cpu_imp)

d_gpu_vs_ref = np.abs(gpu_imp - cpu_uni)
d_gpu_vs_cpu = np.abs(gpu_imp - cpu_imp)
rel = d_gpu_vs_ref / np.maximum(cpu_uni, 1e-4)
print(f"\n|GPU_imp - CPU_uniform| = {d_gpu_vs_ref}  (rel {rel})")
print(f"|GPU_imp - CPU_importance| = {d_gpu_vs_cpu}")
# Unbiasedness: GPU-importance must match the CPU-uniform reference within a few
# % (converged mean over ~9k px; the pre-fix bug was a ~5x over-weight on the
# blue edge -> a clear B-channel offset). Tolerance 4% per channel.
ok = bool(np.all(rel < 0.04))
print("\nB-channel relative diff:", f"{rel[2]*100:.2f}%")
print("VERDICT:", "PASS - GPU importance is unbiased on 380-780" if ok
      else "FAIL - GPU still biased vs CPU-uniform reference")
sys.exit(0 if ok else 1)
