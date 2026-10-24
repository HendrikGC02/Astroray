"""#975 Voronoi Texture 1D / 2D / 4D dimensions (Cycles kernel/svm/voronoi.h).

Before: voronoi_dimensions != '3D' was evaluated as 3D and reported DEGRADED.

* Values: the CASES / W_CASES tables are Cycles 5.2 (blender-v5.2-release, CPU) Voronoi
  values - an emission-only plane under a top-down orthographic camera, Texture
  Coordinate > Object [> Mapping] > Voronoi > Emission, filter width 0.01, 1 spp, so each
  pixel is the node evaluated at its centre (x, y, 0) (W = the node's W socket, or the
  object x for W_CASES). Distance / Radius render as a grey, Color as the hashed colour.
  Reference + how it was produced: .astroray_plan/docs/issue975-voronoi-nd-research.md.
* 3D (#1108): the same Cycles 5.2 scene (exponent 1.5; astra_run/2026-10-18/i1108) - 3D runs the
  shared vnd_* port now, so N-Sphere Radius, unclamped F2 / Manhattan and the distance-to-edge
  fractal match Cycles point for point (58/58 cases float32-exact at the render level).
* Addon: the dimension and W reach the engine and the DEGRADED report is gone; a linked
  W is still reported (it is read as its default value).
"""
import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(__file__))
from test_issue818_procedural_opvm import Link, Node, Sock, _load_addon_stub

astroray_real = pytest.importorskip("astroray")

DM = {"EUCLIDEAN": 0, "MANHATTAN": 1, "CHEBYCHEV": 2, "MINKOWSKI": 3}
FE = {"F1": 0, "SMOOTH_F1": 1, "F2": 2, "DISTANCE_TO_EDGE": 3, "N_SPHERE_RADIUS": 4}
DIMS = {"1D": 1, "2D": 2, "3D": 3, "4D": 4}
ATOL = 1e-4   # exact to float32 in practice; headroom for compiler (FMA) differences
# Blender Mapping(Point) of the tilt cases: rotate X by atan2(.6,.8), translate (.13,.21,.37).
TILT = (math.atan2(0.6, 0.8), (0.13, 0.21, 0.37))

# (case name, dims, feature, metric, scale, randomness, smoothness, exponent, detail, roughness,
#  lacunarity, normalize, color, w, tilt, [(x, y, r, g, b), ...])  -- Cycles 5.2 values
CASES = [
    ('2D_F1_EUCLIDEAN_Distance', '2D', 'F1', 'EUCLIDEAN', 4.0, 1.0, 1.0, 0.5, 0.0, 0.5, 2.0, False, False, 0.0, False,
     [(-0.273438, -0.648438, 0.396463), (0.460938, 0.351562, 0.186201), (-0.023438, 0.617188, 0.73894), (-0.179688, -0.007812, 0.131076)]),
    ('2D_SMOOTH_F1_EUCLIDEAN_Distance', '2D', 'SMOOTH_F1', 'EUCLIDEAN', 4.0, 1.0, 1.0, 0.5, 0.0, 0.5, 2.0, False, False, 0.0, False,
     [(0.023438, 0.054688, 0.590438), (-0.585938, -0.320312, 0.183916), (-0.148438, -0.398438, 0.249381), (0.539062, 0.023438, 0.036837)]),
    ('2D_F2_EUCLIDEAN_Distance', '2D', 'F2', 'EUCLIDEAN', 4.0, 1.0, 1.0, 0.5, 0.0, 0.5, 2.0, False, False, 0.0, False,
     [(0.804688, -0.632812, 0.576296), (-0.273438, 0.414062, 0.87362), (-0.101562, -0.929688, 0.494738), (-0.523438, -0.476562, 0.577118)]),
    ('2D_DISTANCE_TO_EDGE_EUCLIDEAN_Distance', '2D', 'DISTANCE_TO_EDGE', 'EUCLIDEAN', 4.0, 1.0, 1.0, 0.5, 0.0, 0.5, 2.0, False, False, 0.0, False,
     [(-0.554688, 0.273438, 0.354941), (-0.304688, -0.617188, 0.099542), (-0.460938, 0.898438, 0.25405), (-0.320312, -0.273438, 0.227268)]),
    ('2D_N_SPHERE_RADIUS_EUCLIDEAN_Radius', '2D', 'N_SPHERE_RADIUS', 'EUCLIDEAN', 4.0, 1.0, 1.0, 0.5, 0.0, 0.5, 2.0, False, False, 0.0, False,
     [(-0.601562, 0.789062, 0.393615), (0.242188, 0.679688, 0.369869), (0.148438, -0.726562, 0.304896), (-0.742188, 0.148438, 0.414863)]),
    ('2D_F1_MANHATTAN_Distance_exp1.5', '2D', 'F1', 'MANHATTAN', 4.0, 1.0, 1.0, 1.5, 0.0, 0.5, 2.0, False, False, 0.0, False,
     [(-0.726562, 0.429688, 0.870591), (-0.539062, -0.914062, 0.480002), (-0.695312, -0.679688, 0.651005), (-0.117188, -0.710938, 0.482825)]),
    ('2D_F2_CHEBYCHEV_Distance_exp1.5', '2D', 'F2', 'CHEBYCHEV', 4.0, 1.0, 1.0, 1.5, 0.0, 0.5, 2.0, False, False, 0.0, False,
     [(-0.617188, -0.835938, 0.679386), (-0.664062, -0.523438, 0.65263), (0.664062, -0.210938, 0.813634), (-0.648438, 0.835938, 0.726217)]),
    ('2D_SMOOTH_F1_MINKOWSKI_Distance_exp1.5', '2D', 'SMOOTH_F1', 'MINKOWSKI', 4.0, 1.0, 1.0, 1.5, 0.0, 0.5, 2.0, False, False, 0.0, False,
     [(0.367188, -0.585938, 0.424272), (0.023438, -0.585938, 0.220341), (0.054688, 0.804688, 0.471346), (-0.679688, -0.132812, 0.282797)]),
    ('2D_F1_EUCLIDEAN_Color', '2D', 'F1', 'EUCLIDEAN', 4.0, 1.0, 1.0, 0.5, 0.0, 0.5, 2.0, False, True, 0.0, False,
     [(-0.570312, -0.117188, 0.796684, 0.627671, 0.015993), (0.773438, -0.101562, 0.077557, 0.375294, 0.925992), (0.148438, 0.648438, 0.803334, 0.578182, 0.13877), (0.679688, 0.257812, 0.705048, 0.58785, 0.243721)]),
    ('2D_F2_EUCLIDEAN_Color', '2D', 'F2', 'EUCLIDEAN', 4.0, 1.0, 1.0, 0.5, 0.0, 0.5, 2.0, False, True, 0.0, False,
     [(0.054688, 0.757812, 0.240596, 0.945572, 0.674578), (-0.179688, -0.320312, 0.947741, 0.622956, 0.063098), (0.648438, -0.460938, 0.635733, 0.732273, 0.405737), (-0.242188, -0.757812, 0.857377, 0.550314, 0.652313)]),
    ('2D_F1_EUCLIDEAN_Distance_ran0.5', '2D', 'F1', 'EUCLIDEAN', 4.0, 0.5, 1.0, 0.5, 0.0, 0.5, 2.0, False, False, 0.0, False,
     [(-0.070312, 0.164062, 0.662464), (-0.554688, -0.398438, 0.446295), (0.195312, -0.148438, 0.338617), (0.023438, -0.320312, 0.423151)]),
    ('2D_F2_EUCLIDEAN_Distance_det2.5_norTrue', '2D', 'F2', 'EUCLIDEAN', 4.0, 1.0, 1.0, 0.5, 2.5, 0.6, 2.2, True, False, 0.0, False,
     [(-0.117188, 0.601562, 0.267352), (0.117188, 0.460938, 0.193135), (0.601562, -0.820312, 0.259843), (0.460938, -0.242188, 0.25413)]),
    ('2D_DISTANCE_TO_EDGE_EUCLIDEAN_Distance_det2.5_norTrue', '2D', 'DISTANCE_TO_EDGE', 'EUCLIDEAN', 4.0, 1.0, 1.0, 0.5, 2.5, 0.6, 2.2, True, False, 0.0, False,
     [(0.085938, -0.414062, 0.090354), (0.414062, 0.273438, 0.19697), (-0.789062, -0.476562, 0.036612), (-0.601562, 0.492188, 0.242217)]),
    ('2D_F1_EUCLIDEAN_Distance_mapT', '2D', 'F1', 'EUCLIDEAN', 4.0, 1.0, 1.0, 0.5, 0.0, 0.5, 2.0, False, False, 0.0, True,
     [(-0.789062, -0.632812, 0.325486), (-0.007812, 0.257812, 0.418214), (-0.320312, -0.085938, 0.467319), (-0.070312, -0.898438, 0.167014)]),
    ('4D_F1_EUCLIDEAN_Distance_w0.37', '4D', 'F1', 'EUCLIDEAN', 4.0, 1.0, 1.0, 0.5, 0.0, 0.5, 2.0, False, False, 0.37, False,
     [(-0.179688, 0.648438, 0.263294), (-0.242188, -0.867188, 0.663326), (-0.070312, -0.351562, 0.46718), (-0.429688, 0.070312, 0.646519)]),
    ('4D_SMOOTH_F1_EUCLIDEAN_Distance_w0.37', '4D', 'SMOOTH_F1', 'EUCLIDEAN', 4.0, 1.0, 1.0, 0.5, 0.0, 0.5, 2.0, False, False, 0.37, False,
     [(0.132812, 0.882812, 0.30597), (-0.382812, -0.601562, 0.496729), (0.710938, 0.554688, 0.478959), (-0.789062, -0.882812, 0.505327)]),
    ('4D_F2_EUCLIDEAN_Distance_w0.37', '4D', 'F2', 'EUCLIDEAN', 4.0, 1.0, 1.0, 0.5, 0.0, 0.5, 2.0, False, False, 0.37, False,
     [(-0.445312, -0.820312, 0.723873), (-0.007812, -0.414062, 0.492761), (0.367188, -0.179688, 0.773603), (0.335938, 0.617188, 0.857996)]),
    ('4D_DISTANCE_TO_EDGE_EUCLIDEAN_Distance_w0.37', '4D', 'DISTANCE_TO_EDGE', 'EUCLIDEAN', 4.0, 1.0, 1.0, 0.5, 0.0, 0.5, 2.0, False, False, 0.37, False,
     [(-0.445312, -0.679688, 0.083852), (0.664062, 0.195312, 0.1679), (0.367188, 0.492188, 0.132799), (-0.304688, 0.851562, 0.162409)]),
    ('4D_N_SPHERE_RADIUS_EUCLIDEAN_Radius_w0.37', '4D', 'N_SPHERE_RADIUS', 'EUCLIDEAN', 4.0, 1.0, 1.0, 0.5, 0.0, 0.5, 2.0, False, False, 0.37, False,
     [(-0.710938, -0.523438, 0.399001), (0.632812, -0.445312, 0.368397), (0.476562, 0.804688, 0.263922), (0.335938, -0.617188, 0.276685)]),
    ('4D_F1_MANHATTAN_Distance_w0.37_exp1.5', '4D', 'F1', 'MANHATTAN', 4.0, 1.0, 1.0, 1.5, 0.0, 0.5, 2.0, False, False, 0.37, False,
     [(-0.164062, 0.304688, 1.264488), (-0.695312, 0.914062, 1.171575), (0.757812, -0.023438, 0.900137), (-0.382812, -0.039062, 1.112458)]),
    ('4D_F2_MINKOWSKI_Distance_w0.37_exp1.5', '4D', 'F2', 'MINKOWSKI', 4.0, 1.0, 1.0, 1.5, 0.0, 0.5, 2.0, False, False, 0.37, False,
     [(-0.898438, -0.742188, 1.143129), (-0.054688, 0.882812, 0.956412), (0.070312, -0.070312, 0.936736), (0.726562, 0.804688, 0.920182)]),
    ('4D_F1_EUCLIDEAN_Color_w0.37', '4D', 'F1', 'EUCLIDEAN', 4.0, 1.0, 1.0, 0.5, 0.0, 0.5, 2.0, False, True, 0.37, False,
     [(-0.195312, 0.351562, 0.020381, 0.223623, 0.178681), (-0.445312, 0.085938, 0.123505, 0.994705, 0.770187), (0.398438, -0.210938, 0.551585, 0.759339, 0.439438), (-0.679688, -0.679688, 0.938518, 0.80365, 0.809131)]),
    ('4D_F2_EUCLIDEAN_Distance_det2.5_norTrue_w0.37', '4D', 'F2', 'EUCLIDEAN', 4.0, 1.0, 1.0, 0.5, 2.5, 0.6, 2.2, True, False, 0.37, False,
     [(0.304688, 0.023438, 0.212661), (-0.914062, -0.695312, 0.207952), (-0.664062, 0.757812, 0.218688), (0.414062, 0.867188, 0.176949)]),
    ('4D_F1_EUCLIDEAN_Distance_mapT_w0.37', '4D', 'F1', 'EUCLIDEAN', 4.0, 1.0, 1.0, 0.5, 0.0, 0.5, 2.0, False, False, 0.37, True,
     [(-0.570312, -0.679688, 0.403217), (-0.726562, 0.570312, 0.309536), (0.460938, 0.726562, 0.206516), (0.132812, -0.398438, 0.332654)]),
    ('4D_F2_CHEBYCHEV_Distance_mapT_w0.37', '4D', 'F2', 'CHEBYCHEV', 4.0, 1.0, 1.0, 0.5, 0.0, 0.5, 2.0, False, False, 0.37, True,
     [(0.226562, 0.492188, 0.575197), (-0.460938, -0.132812, 0.578388), (0.710938, 0.304688, 0.532703), (-0.757812, 0.570312, 0.539259)]),
    ('1D_F1_EUCLIDEAN_Distance_w0.37', '1D', 'F1', 'EUCLIDEAN', 4.0, 1.0, 1.0, 0.5, 0.0, 0.5, 2.0, False, False, 0.37, False,
     [(0.117188, 0.664062, 0.33164)]),
    ('1D_F2_EUCLIDEAN_Distance_ran0.6_w1.9', '1D', 'F2', 'EUCLIDEAN', 4.0, 0.6, 1.0, 0.5, 0.0, 0.5, 2.0, False, False, 1.9, False,
     [(0.867188, 0.835938, 0.791502)]),
    ('1D_DISTANCE_TO_EDGE_EUCLIDEAN_Distance_w0.37', '1D', 'DISTANCE_TO_EDGE', 'EUCLIDEAN', 4.0, 1.0, 1.0, 0.5, 0.0, 0.5, 2.0, False, False, 0.37, False,
     [(-0.367188, -0.617188, 0.536624)]),
    ('1D_N_SPHERE_RADIUS_EUCLIDEAN_Radius_ran0.6_w1.9', '1D', 'N_SPHERE_RADIUS', 'EUCLIDEAN', 4.0, 0.6, 1.0, 0.5, 0.0, 0.5, 2.0, False, False, 1.9, False,
     [(-0.882812, 0.695312, 0.396594)]),
    ('1D_F1_EUCLIDEAN_Color_w0.37', '1D', 'F1', 'EUCLIDEAN', 4.0, 1.0, 1.0, 0.5, 0.0, 0.5, 2.0, False, True, 0.37, False,
     [(0.132812, 0.414062, 0.14836, 0.622926, 0.540482)]),
    ('1D_F1_EUCLIDEAN_Distance_det2.5_norTrue_w0.37', '1D', 'F1', 'EUCLIDEAN', 4.0, 1.0, 1.0, 0.5, 2.5, 0.6, 2.2, True, False, 0.37, False,
     [(0.429688, 0.414062, 0.320191)]),
    # 3D (#1108): Cycles 5.2 values from astra_run/2026-10-18/i1108/ref3d (same scene, exponent 1.5)
    ('3D_F1_EUCLIDEAN_Distance_det0.0', '3D', 'F1', 'EUCLIDEAN', 4.0, 1.0, 1.0, 1.5, 0.0, 0.5, 2.0, False, False, 0.0, False,
     [(-0.132812, -0.710938, 0.70974), (0.210938, 0.960938, 0.157016), (-0.585938, -0.351562, 0.67226), (0.320312, -0.914062, 0.647023)]),
    ('3D_F1_MANHATTAN_Distance_det0.0', '3D', 'F1', 'MANHATTAN', 4.0, 1.0, 1.0, 1.5, 0.0, 0.5, 2.0, False, False, 0.0, False,
     [(0.304688, 0.039062, 0.889664), (-0.960938, -0.179688, 1.081763), (-0.929688, 0.929688, 0.692452), (0.445312, 0.367188, 0.906469)]),
    ('3D_F1_CHEBYCHEV_Distance_det2.0', '3D', 'F1', 'CHEBYCHEV', 4.0, 1.0, 1.0, 1.5, 2.0, 0.6, 2.2, False, False, 0.0, False,
     [(0.070312, -0.445312, 0.997644), (-0.648438, -0.664062, 0.663341), (0.257812, 0.257812, 1.00768), (-0.664062, -0.101562, 0.810819)]),
    ('3D_F1_MINKOWSKI_Distance_det0.0', '3D', 'F1', 'MINKOWSKI', 4.0, 1.0, 1.0, 1.5, 0.0, 0.5, 2.0, False, False, 0.0, False,
     [(0.726562, -0.929688, 0.548209), (-0.460938, -0.929688, 0.784927), (-0.648438, 0.710938, 0.323861), (0.789062, -0.507812, 0.271974)]),
    ('3D_SMOOTH_F1_EUCLIDEAN_Distance_det0.0', '3D', 'SMOOTH_F1', 'EUCLIDEAN', 4.0, 1.0, 1.0, 1.5, 0.0, 0.5, 2.0, False, False, 0.0, False,
     [(0.210938, -0.429688, 0.526845), (-0.007812, -0.382812, 0.359221), (0.960938, 0.679688, 0.391951), (-0.710938, 0.242188, 0.300236)]),
    ('3D_SMOOTH_F1_MINKOWSKI_Distance_det2.0', '3D', 'SMOOTH_F1', 'MINKOWSKI', 4.0, 1.0, 1.0, 1.5, 2.0, 0.6, 2.2, False, False, 0.0, False,
     [(0.445312, 0.023438, 1.051213), (-0.257812, -0.617188, 1.009334), (0.039062, -0.007812, 0.780491), (0.632812, -0.132812, 1.205294)]),
    ('3D_SMOOTH_F1_EUCLIDEAN_Distance_det0.0_smo0.3', '3D', 'SMOOTH_F1', 'EUCLIDEAN', 4.0, 1.0, 0.3, 1.5, 0.0, 0.5, 2.0, False, False, 0.0, False,
     [(-0.085938, -0.945312, 0.440499), (-0.898438, -0.507812, 0.622495), (-0.539062, -0.492188, 0.388015), (-0.585938, 0.710938, 0.214461)]),
    ('3D_F2_EUCLIDEAN_Distance_det0.0', '3D', 'F2', 'EUCLIDEAN', 4.0, 1.0, 1.0, 1.5, 0.0, 0.5, 2.0, False, False, 0.0, False,
     [(-0.960938, -0.179688, 0.918738), (0.320312, -0.351562, 0.699437), (0.179688, -0.335938, 0.722592), (0.601562, -0.867188, 0.634305)]),
    ('3D_F2_MANHATTAN_Distance_det0.0', '3D', 'F2', 'MANHATTAN', 4.0, 1.0, 1.0, 1.5, 0.0, 0.5, 2.0, False, False, 0.0, False,
     [(0.710938, 0.398438, 0.872101), (0.820312, 0.851562, 0.986131), (0.210938, -0.554688, 0.997973), (0.898438, -0.882812, 1.032537)]),
    ('3D_F2_MANHATTAN_Distance_det2.5_norTrue', '3D', 'F2', 'MANHATTAN', 4.0, 1.0, 1.0, 1.5, 2.5, 0.6, 2.2, True, False, 0.0, False,
     [(-0.414062, 0.054688, 0.182104), (0.429688, -0.179688, 0.174617), (0.445312, 0.226562, 0.198232), (-0.945312, 0.507812, 0.173375)]),
    ('3D_F2_EUCLIDEAN_Distance_det0.0_ran0.5', '3D', 'F2', 'EUCLIDEAN', 4.0, 0.5, 1.0, 1.5, 0.0, 0.5, 2.0, False, False, 0.0, False,
     [(0.570312, -0.304688, 0.620152), (-0.476562, -0.679688, 0.805281), (-0.804688, 0.429688, 0.661666), (0.851562, -0.117188, 0.683713)]),
    ('3D_DISTANCE_TO_EDGE_EUCLIDEAN_Distance_det0.0', '3D', 'DISTANCE_TO_EDGE', 'EUCLIDEAN', 4.0, 1.0, 1.0, 1.5, 0.0, 0.5, 2.0, False, False, 0.0, False,
     [(0.929688, 0.789062, 0.175619), (0.054688, -0.070312, 0.083195), (0.695312, 0.710938, 0.221304), (0.695312, 0.710938, 0.221304)]),
    ('3D_DISTANCE_TO_EDGE_EUCLIDEAN_Distance_det2.0_ran0.5', '3D', 'DISTANCE_TO_EDGE', 'EUCLIDEAN', 4.0, 0.5, 1.0, 1.5, 2.0, 0.6, 2.2, False, False, 0.0, False,
     [(0.632812, 0.601562, 0.095115), (0.445312, -0.742188, 0.050521), (0.773438, -0.882812, 0.058745), (0.335938, 0.539062, 0.089342)]),
    ('3D_DISTANCE_TO_EDGE_EUCLIDEAN_Distance_det2.5_norTrue', '3D', 'DISTANCE_TO_EDGE', 'EUCLIDEAN', 4.0, 1.0, 1.0, 1.5, 2.5, 0.6, 2.2, True, False, 0.0, False,
     [(0.960938, -0.601562, 0.036382), (0.492188, -0.789062, 0.126333), (-0.132812, -0.679688, 0.107803), (0.179688, -0.039062, 0.165196)]),
    ('3D_N_SPHERE_RADIUS_EUCLIDEAN_Radius_det0.0', '3D', 'N_SPHERE_RADIUS', 'EUCLIDEAN', 4.0, 1.0, 1.0, 1.5, 0.0, 0.5, 2.0, False, False, 0.0, False,
     [(-0.414062, -0.289062, 0.329075), (-0.132812, 0.429688, 0.420952), (0.617188, 0.164062, 0.308576), (0.898438, 0.742188, 0.221101)]),
    ('3D_N_SPHERE_RADIUS_EUCLIDEAN_Radius_det2.0', '3D', 'N_SPHERE_RADIUS', 'EUCLIDEAN', 4.0, 1.0, 1.0, 1.5, 2.0, 0.6, 2.2, False, False, 0.0, False,
     [(0.242188, 0.257812, 0.339053), (0.351562, 0.039062, 0.343943), (0.382812, 0.382812, 0.222636), (0.492188, 0.757812, 0.247249)]),
    ('3D_F1_EUCLIDEAN_Color_det0.0', '3D', 'F1', 'EUCLIDEAN', 4.0, 1.0, 1.0, 1.5, 0.0, 0.5, 2.0, False, True, 0.0, False,
     [(0.617188, -0.679688, 0.740863, 0.533086, 0.2475), (-0.085938, 0.742188, 0.634423, 0.561823, 0.661703), (0.398438, 0.164062, 0.266916, 0.723095, 0.593809), (0.789062, -0.570312, 0.050669, 0.093553, 0.840932)]),
    ('3D_F2_EUCLIDEAN_Color_det2.0', '3D', 'F2', 'EUCLIDEAN', 4.0, 1.0, 1.0, 1.5, 2.0, 0.6, 2.2, False, True, 0.0, False,
     [(0.851562, 0.570312, 0.802785, 1.153578, 0.536263), (0.273438, -0.523438, 0.422931, 0.864544, 0.76078), (0.226562, 0.710938, 0.383662, 0.598811, 0.408773), (0.679688, -0.039062, 1.544854, 1.047496, 0.791574)]),
    ('3D_SMOOTH_F1_EUCLIDEAN_Color_det0.0', '3D', 'SMOOTH_F1', 'EUCLIDEAN', 4.0, 1.0, 1.0, 1.5, 0.0, 0.5, 2.0, False, True, 0.0, False,
     [(-0.460938, 0.289062, 0.339891, 0.476846, 0.381827), (-0.757812, 0.304688, 0.718067, 0.438997, 0.329953), (0.460938, 0.835938, 0.18743, 0.296745, 0.325154), (0.476562, -0.335938, 0.561541, 0.251441, 0.36785)]),
    ('3D_F2_CHEBYCHEV_Distance_det2.0_mapT', '3D', 'F2', 'CHEBYCHEV', 4.0, 1.0, 1.0, 1.5, 2.0, 0.6, 2.2, False, False, 0.0, True,
     [(-0.039062, -0.570312, 1.270039), (-0.820312, -0.882812, 1.21384), (-0.382812, -0.820312, 1.119098), (0.773438, -0.117188, 1.208356)]),
    ('3D_N_SPHERE_RADIUS_EUCLIDEAN_Radius_det0.0_mapT', '3D', 'N_SPHERE_RADIUS', 'EUCLIDEAN', 4.0, 1.0, 1.0, 1.5, 0.0, 0.5, 2.0, False, False, 0.0, True,
     [(0.945312, 0.429688, 0.307173), (0.414062, 0.851562, 0.334281), (-0.039062, -0.710938, 0.35176), (-0.648438, -0.273438, 0.271857)]),
    ('3D_DISTANCE_TO_EDGE_EUCLIDEAN_Distance_det2.0_mapT', '3D', 'DISTANCE_TO_EDGE', 'EUCLIDEAN', 4.0, 1.0, 1.0, 1.5, 2.0, 0.6, 2.2, False, False, 0.0, True,
     [(0.117188, 0.914062, 0.038027), (-0.226562, 0.757812, 0.10435), (0.570312, -0.476562, 0.065865), (0.585938, 0.242188, 0.130434)]),
]
W_CASES = [  # (name, feature, scale, detail, normalize, color, [(w, value...), ...])
    ('1DX_F1', 'F1', 4.0, 0.0, False, False, [(-0.929688, 0.011798), (-0.757812, 0.06425), (-0.585938, 0.419493), (-0.414062, 0.268007), (-0.242188, 0.132637), (-0.070312, 0.554863), (0.101562, 0.176176), (0.273438, 0.054611), (0.445312, 0.632889), (0.617188, 0.416137), (0.789062, 0.271363)]),
    ('1DX_SMOOTH_F1', 'SMOOTH_F1', 4.0, 0.0, False, False, [(-0.929688, 0.011798), (-0.757812, 0.06425), (-0.585938, 0.379222), (-0.414062, 0.268007), (-0.242188, 0.132637), (-0.070312, 0.541147), (0.101562, 0.176176), (0.273438, 0.05439), (0.445312, 0.632819), (0.617188, 0.416137), (0.789062, 0.266005)]),
    ('1DX_F2', 'F2', 4.0, 0.0, False, False, [(-0.929688, 0.732419), (-0.757812, 0.675702), (-0.585938, 0.62325), (-0.414062, 0.820137), (-0.242188, 0.955507), (-0.070312, 0.863676), (0.101562, 0.742111), (0.273438, 0.511324), (0.445312, 1.103637), (0.617188, 1.320389), (0.789062, 0.637483)]),
    ('1DX_DISTANCE_TO_EDGE', 'DISTANCE_TO_EDGE', 4.0, 0.0, False, False, [(-0.929688, 0.360311), (-0.757812, 0.305726), (-0.585938, 0.101879), (-0.414062, 0.276065), (-0.242188, 0.411435), (-0.070312, 0.154407), (0.101562, 0.459144), (0.273438, 0.228356), (0.445312, 0.235374), (0.617188, 0.452126), (0.789062, 0.18306)]),
    ('1DX_N_SPHERE_RADIUS', 'N_SPHERE_RADIUS', 4.0, 0.0, False, False, [(-0.929688, 0.369976), (-0.757812, 0.369976), (-0.585938, 0.521371), (-0.414062, 0.521371), (-0.242188, 0.544072), (-0.070312, 0.544072), (0.101562, 0.282967), (0.273438, 0.282967), (0.445312, 0.282967), (0.617188, 0.454423), (0.789062, 0.454423)]),
    ('1DX_F1_Color', 'F1', 4.0, 0.0, False, True, [(-0.929688, 0.293048, 0.61106, 0.654128), (-0.585938, 0.075743, 0.30711, 0.034659), (-0.242188, 0.163887, 0.294934, 0.905046), (0.101562, 0.582426, 0.14956, 0.544475), (0.445312, 0.14836, 0.622926, 0.540482), (0.789062, 0.884887, 0.573694, 0.990881)]),
    ('1DX_F1_det', 'F1', 4.0, 2.5, True, False, [(-0.929688, 0.248278), (-0.585938, 0.418382), (-0.242188, 0.167222), (0.101562, 0.318219), (0.445312, 0.381416), (0.789062, 0.280965)]),
]


def _params(scale, rand, smooth, expo, det, rough, lac, norm, color, dm, feat, dims, w):
    return [scale, rand, float(dm), float(feat), smooth, 0, 0, 0, 1, 1, 1, det, rough, lac, expo,
            1.0 if norm else 0.0, 1.0 if color else 0.0, float(dims), w]


def _renderer():
    return astroray_real.Renderer()


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_voronoi_nd_matches_cycles(case):
    (name, dims, feat, metric, scale, rand, smooth, expo, det, rough, lac, norm, color, w,
     tilt, pts) = case
    r = _renderer()
    r.create_procedural_texture("v", "voronoi", _params(
        scale, rand, smooth, expo, det, rough, lac, norm, color, DM[metric], FE[feat],
        DIMS[dims], w))
    fn = r.sample_named_texture
    if tilt:
        c, s = math.cos(TILT[0]), math.sin(TILT[0])
        t = TILT[1]
        r.set_texture_mapping_matrix("v", [1, 0, 0, t[0], 0, c, -s, t[1], 0, s, c, t[2]])
        fn = r.sample_named_texture_mapped
    for p in pts:
        got = np.array(fn("v", p[0], p[1]))
        want = np.array(p[2:]) if len(p) == 5 else np.full(3, p[2])
        assert np.allclose(got, want, atol=ATOL), (name, p, got, want)


@pytest.mark.parametrize("case", W_CASES, ids=[c[0] for c in W_CASES])
def test_voronoi_1d_w_matches_cycles(case):
    name, feat, scale, det, norm, color, pts = case
    r = _renderer()
    for i, p in enumerate(pts):
        r.create_procedural_texture(f"w{i}", "voronoi", _params(
            scale, 1.0, 1.0, 0.5, det, 0.6 if det else 0.5, 2.2 if det else 2.0, norm, color, 0,
            FE[feat], 1, p[0]))
        got = np.array(r.sample_named_texture(f"w{i}", 0.0, 0.0))
        want = np.array(p[1:]) if color else np.full(3, p[1])
        assert np.allclose(got, want, atol=ATOL), (name, p, got, want)


def test_voronoi_dimensions_differ():
    """The same node settings give different fields per dimension (not 3-D in disguise)."""
    r = _renderer()
    pts = [(0.31, 0.77), (-0.52, 0.18), (0.9, -0.4), (-0.7, -0.66)]
    out = {}
    for d in (1, 2, 3, 4):
        r.create_procedural_texture(f"d{d}", "voronoi", _params(
            4.0, 1.0, 1.0, 0.5, 0.0, 0.5, 2.0, False, False, 0, 0, d, 0.37))
        out[d] = np.array([r.sample_named_texture(f"d{d}", u, v)[0] for u, v in pts])
    for a in (1, 2, 3, 4):
        for b in range(a + 1, 5):
            assert not np.allclose(out[a], out[b], atol=1e-3), (a, b)


def test_voronoi_nd_distance_is_not_clamped():
    """Cycles' F2 / Manhattan distance exceeds 1 and Smooth F1 dips below 0; every dimension
    keeps the value (3D since #1108; only the engine-only F1+F2 / F2-F1 features clamp)."""
    r = _renderer()
    r.create_procedural_texture("f2", "voronoi", _params(
        4.0, 1.0, 1.0, 0.5, 0.0, 0.5, 2.0, False, False, 1, 2, 2, 0.0))
    vals = [r.sample_named_texture("f2", x * 0.0173, 0.31)[0] for x in range(-60, 60)]
    assert max(vals) > 1.0


# --- addon export: dimension + W reach the engine, no DEGRADED report ---------------------- #
class _Recorder:
    def __init__(self):
        self.calls = []

    def create_procedural_texture(self, name, kind, params, *a):
        self.calls.append((name, kind, list(params)))

    def __getattr__(self, _name):
        return lambda *a, **k: 1


def _addon_engine(monkeypatch):
    addon = _load_addon_stub(monkeypatch)
    eng = addon.CustomRaytracerRenderEngine.__new__(addon.CustomRaytracerRenderEngine)
    eng._current_material_name = "M"
    eng._generated_textures_by_material = {}
    return eng


def _voronoi_node(dims, w=0.25, w_link=None, feature='F1'):
    return Node('TEX_VORONOI', name='Voronoi', feature=feature, distance='EUCLIDEAN',
                normalize=False, voronoi_dimensions=dims,
                inputs=[Sock('Vector'), Sock('W', w, w_link), Sock('Scale', 4.0),
                        Sock('Detail', 0.0), Sock('Roughness', 0.5), Sock('Lacunarity', 2.0),
                        Sock('Smoothness', 1.0), Sock('Exponent', 0.5), Sock('Randomness', 1.0)])


def _export(monkeypatch, vnode, out='Distance'):
    eng = _addon_engine(monkeypatch)
    rec = _Recorder()
    bsdf = Node('BSDF_DIFFUSE', inputs=[Sock('Color', [0.8, 0.8, 0.8], Link(vnode, out))])
    _, tex = eng.get_base_color_texture(bsdf, 'Color', rec)
    assert tex is not None
    (_, _, params), = [c for c in rec.calls if c[1] == 'voronoi']
    return eng, params


@pytest.mark.parametrize("dims,code", [('1D', 1.0), ('2D', 2.0), ('3D', 3.0), ('4D', 4.0)])
def test_975_dimension_and_w_exported_without_degraded_report(monkeypatch, dims, code):
    eng, params = _export(monkeypatch, _voronoi_node(dims))
    assert params[17] == code and params[18] == 0.25, params
    assert not [m for m in eng._degradation_report().messages() if "voronoi" in str(m).lower()]


def test_975_linked_w_still_reported(monkeypatch):
    eng, _ = _export(monkeypatch, _voronoi_node('4D', w_link=Link(Node('VALUE'), 'Value')))
    assert any("linked W input" in str(m) for m in eng._degradation_report().messages())


def test_975_engine_samples_the_exported_dimension(monkeypatch):
    """The 2-D node the addon exports is the 2-D field."""
    _, params = _export(monkeypatch, _voronoi_node('2D'))
    r = _renderer()
    r.create_procedural_texture("a", "voronoi", params)
    r.create_procedural_texture("b", "voronoi", _params(
        4.0, 1.0, 1.0, 0.5, 0.0, 0.5, 2.0, False, False, 0, 0, 2, 0.25))
    assert np.allclose(r.sample_named_texture("a", 0.3, 0.6), r.sample_named_texture("b", 0.3, 0.6))
