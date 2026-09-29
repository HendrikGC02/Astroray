# Indirect sample clamp, volume cabinet
Fraction of ROI energy removed at clamp L = 1/3/10/30 for principled / absorb / scatter media, Cycles vs Astroray.
Verdict: Astroray removes more energy than Cycles at L<=10 (principled L10 0.049 vs 0.000-0.005; scatter 0.204 vs 0.065-0.165);
the gap is the medium-NEE site (0.183 of scatter's 0.204). The Cycles metric (sum|RGB| > 3L) removes even more.
Charts: principled_chart, absorb_chart, scatter_chart (power-sampler series in the JSON meta).
Provenance: pkg290 (issue #884), MinGW CPU build of feat/batch-ad-lamp-clamp-mis @0cf341de.
