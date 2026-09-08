# -*- coding: utf-8 -*-
"""pkg264-cont — under the GPU lock, check whether the GPU (closure-graph) native
'principled' rough-glass furnace ALREADY conserves on the current main build.
If it does, the pkg264 bug is CPU-only (principled.cpp) and gpu_materials.h needs
no change (its gpu_disney_sample already has the dead-sample delta fallback)."""
import os
import sys
import subprocess
import time

LOCK = "C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray/.astroray_plan/.orchestrator.gpu.lock"
sys.path.insert(0, "C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray/scripts")
from roadmap_orchestrator.locks import acquire_lock, release_lock, lock_status  # noqa: E402

PROBE = r'''
import os, sys
os.environ.setdefault("ASTRORAY_BUILD_DIR", r"{build}")
sys.path.insert(0, os.path.join(r"{repo}", "tests"))
from runtime_setup import configure_test_imports
configure_test_imports()
import numpy as np, astroray
print("features:", astroray.__features__)
if not astroray.Renderer().gpu_available:
    print("NO_GPU"); raise SystemExit
def furnace(kind, roughness, spp=128, depth=32, ior=1.45, gpu=True):
    r = astroray.Renderer()
    r.set_background_color([1.0,1.0,1.0])
    if kind == "principled":
        p = {{"transmission_weight":1.0,"ior":ior,"roughness":roughness}}
    else:
        p = {{"transmission":1.0,"ior":ior,"roughness":roughness,"metallic":0.0}}
    g = r.create_material(kind,[1,1,1],p)
    r.add_sphere([0,0,0],1.0,g)
    r.set_integrator("path_tracer")
    if gpu: r.set_use_gpu(True)
    r.setup_camera([0,0,4],[0,0,0],[0,1,0],40.0,1.0,0.0,4.0,80,80)
    r.set_seed(7)
    img = np.asarray(r.render(spp,depth,None,False),dtype=np.float32).reshape(80,80,3)
    return float(img[28:52,28:52].mean())
print("GPU furnace (target 1.0)  principled / disney")
for rr in (0.2,0.5,0.85,1.0):
    print(f"r={{rr}}: principled={{furnace('principled',rr):.4f}} disney={{furnace('disney',rr):.4f}}")
'''


def main():
    build = "C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray/build_cuda"
    repo = "C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray-pkg264"
    deadline = time.time() + 40 * 60
    while not acquire_lock(LOCK, 5400, {"job": "pkg264cont", "what": "gpu furnace probe"}):
        if time.time() > deadline:
            raise SystemExit("gpu lock wait timeout: " + str(lock_status(LOCK, 5400)))
        time.sleep(30)
    try:
        code = PROBE.format(build=build, repo=repo)
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=900)
        print(r.stdout)
        sys.stderr.write(r.stderr[-2000:] if r.stderr else "")
    finally:
        release_lock(LOCK)


if __name__ == "__main__":
    main()
