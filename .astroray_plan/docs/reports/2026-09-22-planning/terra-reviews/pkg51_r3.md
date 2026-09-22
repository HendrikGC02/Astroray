- Lines 149–153: The PSF-cube contract specifies wavelength coordinates but not spatial WCS/units, PSF centre, or the detector plate scale derived from `Ω_pix`; unit-sum normalization can therefore preserve total flux while applying chromatic blur at the wrong angular scale. Fix: require spatial FITS metadata (units, scale, reference pixel/orientation), explicitly map it onto the detector angular grid, reject missing/incompatible metadata, and test angular FWHM/centroid after resampling.

NO — without an angular-coordinate contract, the design cannot guarantee preservation of chromatic spatial information in physically normalized per-pixel statistics.

VERDICT: REVISE - Specify and validate the PSF spatial-WCS-to-detector mapping before dispatch.
