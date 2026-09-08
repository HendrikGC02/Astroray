import os, sys, math
import numpy as np
sys.argv=['x']
import importlib.util
spec=importlib.util.spec_from_file_location("abh", os.path.join(os.path.dirname(os.path.abspath(__file__)),"ab_harness.py"))
# reuse ab_harness build/roi but override material kind
os.environ.setdefault("ASTRORAY_BUILD_DIR", r"C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray-pkg264/build_cuda")
abh=importlib.util.module_from_spec(spec); spec.loader.exec_module(abh)
astroray=abh.astroray
abh.RES=200; abh.SPP=128
def build_kind(r, roughness, kind):
    r.set_background_color([abh.WORLD]*3)
    if kind=="principled":
        p={"transmission_weight":1.0,"ior":abh.IOR,"roughness":roughness,"emission_color":[0,0,0],"emission_strength":0.0}
    else:
        p={"transmission":1.0,"ior":abh.IOR,"roughness":roughness,"metallic":0.0}
    glass=r.create_material(kind,[1,1,1],p)
    r.add_sphere([0,0,abh.Z],abh.SR,glass)
    floor=r.create_material("principled",[abh.PLANE]*3,{"roughness":0.6})
    h=10.0
    r.add_triangle([-h,-h,0],[h,-h,0],[h,h,0],floor); r.add_triangle([-h,-h,0],[h,h,0],[-h,h,0],floor)
    basis=abh.euler_xyz_matrix(*abh.LIGHT_EULER)
    au=list(basis@np.array([1.0,0,0])); av=list(basis@np.array([0,-1.0,0]))
    r.add_area_light_dedicated(list(abh.LIGHT_LOC),au,av,abh.LIGHT_SIZE,abh.LIGHT_SIZE,"RECTANGLE",{"mode":"rgb","color":[1,1,1]},abh.LIGHT_E,1.0)
    r.set_integrator("path_tracer")
    r.setup_camera([0,-abh.CAM_D,abh.Z],[0,0,abh.Z],[0,0,1.0],abh.FOV,1.0,0.0,abh.CAM_D,abh.RES,abh.RES)
def render(roughness,kind):
    r=astroray.Renderer(); build_kind(r,roughness,kind); r.set_seed(7)
    return np.asarray(r.render(abh.SPP,12,None,False,4,4,12),dtype=np.float32).reshape(abh.RES,abh.RES,3)
print("lit scene centre/limb  (Cyc ref in ab_harness)  principled-postfix vs disney")
for rr in (0.5,0.85):
    cc,cl=abh.CYCLES[rr]
    for kind in ("principled","disney"):
        img=render(rr,kind); c,l,_=abh.roi_means(img)
        print(f"r={rr} {kind:11} centre={c:.4f}({c/cc:.3f}Cyc) limb={l:.4f}({l/cl:.3f}Cyc)")
