# Observer colour tiles (before | after)
Colour tiles before / after switching the engine spectral table to the CIE 1931 2 deg observer.
Verdict: the observer mismatch (1964 10 deg CMF vs 1931 sRGB matrix) caused the grey and
low-chroma skew; the fix removes it (residual up to ~9% on saturated albedo is physical).
Provenance: issue #767, Batch T, PR #837 (fix), follow-up #848, 2026-09-20.
