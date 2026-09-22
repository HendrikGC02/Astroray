- L172, L180: The detector integral mixes radiance declared per nm with an unspecified wavelength/integration unit; this can introduce a \(10^9\) count error. Fix: explicitly define \(\lambda\) and \(d\lambda\) in metres (with conversion from nm microbins), or state the equivalent nm-domain conversion factor and require it in the analytic-count test.

NO — chromatic spatial data is preserved through the PSF stage, but detector statistics are not yet unambiguously physically normalized.

VERDICT: REVISE - Specify consistent wavelength units in the electron-count integral and its analytic acceptance oracle.
