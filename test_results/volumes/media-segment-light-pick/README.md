# Volume NEE: one light pick per segment (#961 / #1019)
v2_media at 64 spp: Cycles CPU (1024 spp) | Astroray CPU before | CPU after | GPU after, ROIs drawn.
n_x_relvar_*: N x relVar of luminance vs spp (flat = 1/N noise), shaft ROI and whole image.
Verdict: the shaft now reaches Cycles' level (mean 0.19 vs 0.19) and the heavy tail is gone (N x relVar flat 22-26 vs 28-71 before);
Astroray is still ~17x Cycles' relVar per sample in the shaft (smoke VDB distance sampling, follow-up #1032).
Provenance: lane au-media, branch lane/au-media 5db27480, CPU seeds 11-16 (256 spp: 11-14), GPU seed 278, RTX 5070 Ti; 2026-10-03.
