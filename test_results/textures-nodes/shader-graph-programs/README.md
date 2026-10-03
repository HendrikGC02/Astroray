# Shader-graph programs (pkg314, #993 / #992)
`curves_card_crop.png`: textures_mapping CurvesCard (Float / RGB / Vector Curves), Cycles | Astroray CPU | Astroray GPU.
- Production corpus: 16 pass / 22 xfail / 0 XPASS; corpus v2 604 pass / 94 xfail. prod_wood CPU 4->7/16, GPU 3->7/16; curves GPU 2->3/16.
- sd->N probe (Layer Weight/Fresnel read the pre-bump normal): Cycles and CPU/GPU op-VM/graph all flat 0.
- Stress, 64 materials: op-VM 0.539 s vs graph 0.511 s, images max|d| 2.4e-7; graph kernel 3.5 % of frame.
- `ASTRORAY_GRAPH_PROGRAMS=force`: CPU bit-identical to op-VM, GPU <= 1e-6.
- Production-corpus sheets in ../production-corpus were rendered on fac9c7ef (pre-rebase onto #1041; no shading change).
