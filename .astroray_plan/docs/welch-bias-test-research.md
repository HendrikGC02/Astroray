# Welch tile test for Monte Carlo render comparison - research note (pkg317)

- **Paper:** A. Jung, J. Hanika, C. Dachsbacher, "Detecting Bias in Monte Carlo Renderers using Welch's t-test",
  JCGT 9(2), 2020, https://cg.ivd.kit.edu/welch.php (read Sec. 3-4 from the PDF). Code (welch.c, pvalhist.py) has no
  stated licence: **not vendored**; the test is textbook and implemented with `scipy.stats.t`.
- **Method used from the paper:** two-tailed Welch t per image tile and colour channel; t = (m1 - m2)/sqrt(s1^2/N1 + s2^2/N2);
  Welch-Satterthwaite degrees of freedom; H0 = equal mean, p is uniform under H0; read the result as a per-tile p-value map
  and a histogram (non-uniform = bias). Inputs must be roughly normal: the paper sums one MC sample per pixel of a 32x32
  tile ("Welch sample"); it warns CLT must be checked per scene (Sec. 4.1, 5.1).
- **Adaptation:** we have independent-seed *renders*, not per-sample statistics, so one Welch sample = the tile mean of one
  render (8x8 px x 128-256 spp = 8k-16k MC samples, normal by the same argument). N = 8 renders per backend (df ~ 14).
- **Added (not in the paper):** Holm-Bonferroni (FWER) and Benjamini-Hochberg (FDR) over tiles x channels; a KS test of the
  p-histogram against U(0,1); an optional practical-equivalence margin (reject only if |bias| exceeds delta*mean).
- **Caveat the paper states:** a high p proves nothing; a uniform histogram does not prove unbiasedness. Power scales with
  noise: very low tile noise makes the test sensitive to sub-percent real differences (a feature for bias detection, a
  hazard for a CPU/GPU parity gate).
- **Precedent:** Mitsuba 3 `src/render/tests/test_renders.py` (BSD-3) z-test against a reference with a variance image.
