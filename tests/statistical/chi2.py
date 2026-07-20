"""
Chi-squared goodness-of-fit test for Monte Carlo sampling distributions.

Ported from Mitsuba 3's src/python/python/chi2.py (BSD-3-Clause).
Original implementation © Wenzel Jakob and contributors.
Licensed under the BSD 3-Clause License (see below).

Modifications for Astroray:
- Replace Dr.Jit vectorization with NumPy batching.
- Adopt pbrt-v4 battle-tested constants (Apache-2.0, Matt Pharr):
  10^6 samples, 80×160 (θ,φ) bins, α=0.01, min expected frequency 5, 5 runs.
- Remove Mitsuba-specific RNG (use NumPy random).

--- BEGIN BSD-3-CLAUSE LICENSE (Mitsuba 3) ---
Copyright (c) 2017 Wenzel Jakob <wenzel.jakob@epfl.ch>, All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its contributors
   may be used to endorse or promote products derived from this software
   without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
--- END BSD-3-CLAUSE LICENSE ---
"""

import numpy as np
import time
from scipy import special


class ChiSquareTest:
    """
    Pearson's chi-square test for goodness of fit of a Monte Carlo sampling
    strategy against a reference probability density function.

    Compares a Monte Carlo sampling strategy on a 2D (or lower dimensional)
    space against a reference distribution obtained by numerically integrating
    a probability density function over grid cells in the parameter domain.

    Parameters
    ----------
    domain : object
        Domain interface (SphericalDomain, PlanarDomain, LineDomain) that
        transforms between the parameter and target domain.
    sample_func : callable
        Importance sampling function mapping uniform variates
        [sample_dim, sample_count] to sample_count samples on the target domain.
        May return (samples, weights) tuple for weighted sampling.
    pdf_func : callable
        Probability density function expected to match the samples produced
        by sample_func.
    sample_dim : int, default=2
        Number of random dimensions consumed per sample.
    sample_count : int, default=1000000
        Total samples to generate (pbrt-v4 constant).
    res : int, default=80
        Vertical resolution of histograms. Horizontal resolution is
        res * domain.aspect(). pbrt-v4 uses 80×160 for spherical distributions.
    ires : int, default=4
        Subintervals for trapezoid-rule numerical integration per cell.
    seed : int, default=42
        NumPy random seed (non-zero; seed 0 is random_device sentinel in Astroray).

    Attributes
    ----------
    messages : str
        Log of test execution.
    histogram : ndarray
        Sample distribution histogram.
    pdf : ndarray
        Integrated PDF array.
    p_value : float
        Test p-value from chi-square statistic.
    """
    def __init__(self, domain, sample_func, pdf_func, sample_dim=2,
                 sample_count=1000000, res=80, ires=4, seed=42):
        assert res > 0
        assert ires >= 2, "The 'ires' parameter must be >= 2!"
        assert seed != 0, "seed=0 is reserved for random_device in Astroray; use non-zero seed"

        self.domain = domain
        self.sample_func = sample_func
        self.pdf_func = pdf_func
        self.sample_dim = sample_dim
        self.sample_count = sample_count

        # Compute resolution
        aspect = domain.aspect()
        if aspect is None:
            self.res = np.array([res, 1], dtype=int)
        else:
            self.res = np.maximum(np.array([int(res / aspect), res], dtype=int), 1)

        self.ires = ires
        self.seed = seed
        self.bounds = domain.bounds()
        self.pdf = None
        self.histogram = None
        self.p_value = None
        self.messages = ''
        self.fail = False

    def tabulate_histogram(self):
        """
        Invoke the sampling strategy and generate a histogram in the parameter domain.
        If sample_func returns (positions, weights), samples are weighted.
        """
        self.pdf_start = time.time()

        # Generate uniform variates
        rng = np.random.default_rng(self.seed)
        samples_in = rng.random((self.sample_dim, self.sample_count), dtype=np.float32)

        # Invoke sampling strategy
        samples_out = self.sample_func(samples_in)

        # Handle weighted samples
        if isinstance(samples_out, tuple):
            weights_out = samples_out[1]
            samples_out = samples_out[0]
        else:
            weights_out = np.ones(self.sample_count, dtype=np.float32)

        # Map samples into the parameter domain
        xy = self.domain.map_backward(samples_out)

        # Sanity check: samples in bounds
        eps = (self.bounds[1] - self.bounds[0]) * 1e-4
        in_domain = np.all((xy >= (self.bounds[0] - eps)[:, None]) & (xy <= (self.bounds[1] + eps)[:, None]), axis=0)
        if not np.all(in_domain):
            self._log(f'Encountered {np.sum(~in_domain)} samples outside of the specified domain!')
            self.fail = True

        # Normalize to grid coordinates
        xy = (xy - self.bounds[0][:, None]) / (self.bounds[1] - self.bounds[0])[:, None]
        xy = np.clip(xy * self.res[:, None], 0, self.res[:, None] - 1).astype(int)

        # Build histogram via bincount
        self.histogram = np.zeros(self.res[0] * self.res[1], dtype=np.float32)
        flat_indices = xy[0] + xy[1] * self.res[0]
        np.add.at(self.histogram, flat_indices, weights_out)

        histogram_min = np.min(self.histogram)
        if histogram_min < 0:
            self._log(f'Encountered a cell with negative sample weights: {histogram_min}')
            self.fail = True

        self.histogram_sum = np.sum(self.histogram) / self.sample_count
        if self.histogram_sum > 1.1:
            self._log(f'Sample weights add up to a value greater than 1.0: {self.histogram_sum}')
            self.fail = True

        self.pdf_end = time.time()

    def tabulate_pdf(self):
        """
        Numerically integrate the PDF over each cell using the trapezoid rule
        with ires^2 function evaluations per cell.
        """
        self.histogram_start = time.time()

        # Grid setup
        sample_count = self.ires ** 2
        cell_count = self.res[0] * self.res[1]
        extents = self.bounds[1] - self.bounds[0]
        cell_size = extents / self.res
        sample_spacing = cell_size / (self.ires - 1)

        # Build cell and sample indices
        indices = np.arange(cell_count * sample_count, dtype=np.int32)
        cell_index = indices // sample_count
        sample_index = indices % sample_count

        cell_y = cell_index // self.res[0]
        cell_x = cell_index % self.res[0]
        sample_y = sample_index // self.ires
        sample_x = sample_index % self.ires

        # Compute sample positions in parameter space
        p = self.bounds[0][:, None] + np.stack([cell_x, cell_y], axis=0) * cell_size[:, None]
        p += np.stack([sample_x, sample_y], axis=0) * sample_spacing[:, None] * (1 - 2e-4) + 1e-4 * sample_spacing[:, None]

        # Trapezoid rule integration weights
        edge_mask = (sample_x == 0) | (sample_x == self.ires - 1)
        weights_x = np.where(edge_mask, 0.5, 1.0)
        edge_mask_y = (sample_y == 0) | (sample_y == self.ires - 1)
        weights_y = np.where(edge_mask_y, 0.5, 1.0)
        weights = weights_x * weights_y * np.prod(sample_spacing) * self.sample_count

        # Remap onto target domain and evaluate PDF
        p_target = self.domain.map_forward(p)
        pdf_vals = self.pdf_func(p_target)

        # Sum over each cell (block sum)
        self.pdf = np.add.reduceat(
            pdf_vals * weights,
            np.arange(0, len(pdf_vals), sample_count)
        )

        # Sanity checks
        pdf_min = np.min(self.pdf) / self.sample_count
        if pdf_min < 0:
            self._log(f'Failure: Encountered a cell with negative PDF value: {pdf_min}')
            self.fail = True

        self.pdf_sum = np.sum(self.pdf) / self.sample_count
        if self.pdf_sum > 1.1:
            self._log(f'Failure: PDF integrates to a value greater than 1.0: {self.pdf_sum}')
            self.fail = True

        self.histogram_end = time.time()

    def run(self, significance_level=0.01, test_count=1, quiet=False):
        """
        Run the chi-square test.

        Parameters
        ----------
        significance_level : float, default=0.01
            Desired significance level (pbrt-v4 uses 0.01).
        test_count : int, default=1
            Number of independent tests for Šidák correction.
        quiet : bool, default=False
            Suppress output if True.

        Returns
        -------
        bool
            True if null hypothesis is accepted, False if rejected.
        """
        if self.histogram is None:
            self.tabulate_histogram()

        if self.pdf is None:
            self.tabulate_pdf()

        # Sort by expected frequency (increasing)
        index = np.argsort(self.pdf)
        pdf_sorted = self.pdf[index]
        histogram_sorted = self.histogram[index]

        # Chi-square with cell pooling (min expected frequency = 5, pbrt-v4)
        chi2val, dof, pooled_in, pooled_out = self._chi2_pooled(
            histogram_sorted, pdf_sorted, min_expected_freq=5
        )

        if dof < 1:
            self._log('Failure: The number of degrees of freedom is too low!')
            self.fail = True

        if np.any((pdf_sorted == 0) & (histogram_sorted != 0)):
            self._log('Failure: Found samples in a cell with expected frequency 0. '
                      'Rejecting the null hypothesis!')
            self.fail = True

        if pooled_in > 0:
            self._log(f'Pooled {pooled_in} low-valued cells into {pooled_out} cells to '
                      f'ensure sufficiently high expected cell frequencies')

        pdf_time = (self.pdf_end - self.pdf_start) * 1000
        histogram_time = (self.histogram_end - self.histogram_start) * 1000

        self._log(f'Histogram sum = {self.histogram_sum:.6f} ({histogram_time:.2f} ms), '
                  f'PDF sum = {self.pdf_sum:.6f} ({pdf_time:.2f} ms)')
        self._log(f'Chi^2 statistic = {chi2val:.6f} (d.o.f = {dof})')

        # Compute p-value via regularized incomplete gamma
        self.p_value = 1.0 - special.gammainc(dof / 2, chi2val / 2)

        # Apply Šidák correction (Šidák 1967)
        significance_level_corrected = 1.0 - (1.0 - significance_level) ** (1.0 / test_count)

        if self.fail:
            self._log('Not running the test for reasons listed above. Target '
                      'density and histogram were written to "chi2_data.py"')
            result = False
        elif self.p_value < significance_level_corrected or not np.isfinite(self.p_value):
            self._log(f'***** Rejected ***** the null hypothesis (p-value = {self.p_value:.6f}, '
                      f'significance level = {significance_level_corrected:.6f}). Target density '
                      f'and histogram were written to "chi2_data.py".')
            result = False
        else:
            self._log(f'Accepted the null hypothesis (p-value = {self.p_value:.6f}, '
                      f'significance level = {significance_level_corrected:.6f})')
            result = True

        if not quiet:
            print(self.messages)
            if not result:
                self._dump_tables()

        return result

    def _chi2_pooled(self, histogram, pdf, min_expected_freq):
        """
        Compute chi-square statistic with cell pooling.

        Pools adjacent low-frequency cells until expected frequency >= min_expected_freq.
        Returns (chi2_statistic, degrees_of_freedom, cells_pooled_in, cells_pooled_out).
        """
        pooled_histogram = []
        pooled_pdf = []

        h_accum = 0.0
        p_accum = 0.0

        for h, p in zip(histogram, pdf):
            h_accum += h
            p_accum += p

            if p_accum >= min_expected_freq:
                pooled_histogram.append(h_accum)
                pooled_pdf.append(p_accum)
                h_accum = 0.0
                p_accum = 0.0

        # Include any remainder
        if p_accum > 0:
            if len(pooled_pdf) > 0:
                pooled_histogram[-1] += h_accum
                pooled_pdf[-1] += p_accum
            else:
                pooled_histogram.append(h_accum)
                pooled_pdf.append(p_accum)

        pooled_histogram = np.array(pooled_histogram)
        pooled_pdf = np.array(pooled_pdf)

        # Compute chi-square
        chi2 = np.sum((pooled_histogram - pooled_pdf) ** 2 / (pooled_pdf + 1e-10))
        dof = len(pooled_pdf) - 1

        pooled_in = len(histogram) - len(pooled_histogram)
        pooled_out = len(pooled_histogram)

        return chi2, dof, pooled_in, pooled_out

    def _dump_tables(self):
        """Write histogram and PDF to chi2_data.py for visualization."""
        with open("chi2_data.py", "w") as f:
            pdf_2d = [[float(self.pdf[x + y * self.res[0]])
                       for x in range(self.res[0])]
                      for y in range(self.res[1])]
            histogram_2d = [[float(self.histogram[x + y * self.res[0]])
                             for x in range(self.res[0])]
                            for y in range(self.res[1])]
            # Compute per-cell standardized residuals: (O - E) / sqrt(E)
            residual_2d = [[(float(self.histogram[x + y * self.res[0]]) -
                             float(self.pdf[x + y * self.res[0]])) /
                            (np.sqrt(max(float(self.pdf[x + y * self.res[0]]), 1e-10)))
                            for x in range(self.res[0])]
                           for y in range(self.res[1])]

            f.write(f"pdf={pdf_2d}\n")
            f.write(f"histogram={histogram_2d}\n")
            f.write(f"residual={residual_2d}\n\n")
            f.write('if __name__ == "__main__":\n')
            f.write('    import matplotlib.pyplot as plt\n')
            f.write('    import numpy as np\n\n')
            f.write('    fig, axs = plt.subplots(2, 2, figsize=(12, 10))\n')
            f.write('    pdf = np.array(pdf)\n')
            f.write('    histogram = np.array(histogram)\n')
            f.write('    residual = np.array(residual)\n')
            f.write('    diff = histogram - pdf\n')
            f.write('    absdiff = np.abs(diff).max()\n')
            f.write('    absres = np.abs(residual).max()\n')
            f.write('    a = pdf.shape[1] / pdf.shape[0]\n')
            f.write('    pdf_plot = axs[0, 0].imshow(pdf, vmin=0, aspect=a, interpolation="nearest")\n')
            f.write('    hist_plot = axs[0, 1].imshow(histogram, vmin=0, aspect=a, interpolation="nearest")\n')
            f.write('    diff_plot = axs[1, 0].imshow(diff, aspect=a, vmin=-absdiff, vmax=absdiff, interpolation="nearest", cmap="coolwarm")\n')
            f.write('    res_plot = axs[1, 1].imshow(residual, aspect=a, vmin=-absres, vmax=absres, interpolation="nearest", cmap="coolwarm")\n')
            f.write('    axs[0, 0].set_title("PDF (Expected)")\n')
            f.write('    axs[0, 1].set_title("Histogram (Observed)")\n')
            f.write('    axs[1, 0].set_title("Difference (O - E)")\n')
            f.write('    axs[1, 1].set_title("Standardized Residual (O-E)/sqrt(E)")\n')
            f.write('    props = dict(fraction=0.046, pad=0.04)\n')
            f.write('    fig.colorbar(pdf_plot, ax=axs[0, 0], **props)\n')
            f.write('    fig.colorbar(hist_plot, ax=axs[0, 1], **props)\n')
            f.write('    fig.colorbar(diff_plot, ax=axs[1, 0], **props)\n')
            f.write('    fig.colorbar(res_plot, ax=axs[1, 1], **props)\n')
            f.write('    plt.tight_layout()\n')
            f.write('    plt.show()\n')

    def _log(self, msg):
        self.messages += msg + '\n'


class SphericalDomain:
    """
    Maps between the unit sphere and [phi, cos(theta)] parameterization.

    Domain bounds: phi ∈ [-π, π], cos(theta) ∈ [-1, 1].
    Aspect ratio: 2:1 (matching Mitsuba convention).
    """
    def bounds(self):
        return np.array([[-np.pi, -1.0], [np.pi, 1.0]], dtype=np.float32)

    def aspect(self):
        return 2.0

    def map_forward(self, p):
        """
        Map from [phi, cos(theta)] to unit sphere direction (x, y, z).

        Parameters
        ----------
        p : ndarray, shape (2, N)
            Parameter space coordinates [phi, cos_theta].

        Returns
        -------
        ndarray, shape (3, N)
            Unit sphere directions.
        """
        phi = p[0]
        cos_theta = -p[1]
        sin_theta = np.sqrt(np.maximum(0.0, 1.0 - cos_theta ** 2))
        sin_phi = np.sin(phi)
        cos_phi = np.cos(phi)

        return np.stack([
            cos_phi * sin_theta,
            sin_phi * sin_theta,
            cos_theta
        ], axis=0)

    def map_backward(self, p):
        """
        Map from unit sphere direction (x, y, z) to [phi, cos(theta)].

        Parameters
        ----------
        p : ndarray, shape (3, N)
            Unit sphere directions.

        Returns
        -------
        ndarray, shape (2, N)
            Parameter space coordinates [phi, cos_theta].
        """
        phi = np.arctan2(p[1], p[0])
        cos_theta = -p[2]
        return np.stack([phi, cos_theta], axis=0)


class HemisphericalDomain:
    """
    Maps between the unit HEMISPHERE (upper half-sphere) and [phi, cos(theta)] parameterization.

    Domain bounds: phi ∈ [-π, π], cos(theta) ∈ [0, 1] (UPPER hemisphere only).
    Aspect ratio: 2:1.

    IMPORTANT: This uses Y-up normal (Astroray's makeMaterialTestRecord default).
    Samples must have y >= 0 to be in the upper hemisphere.

    Use this for reflection-only BSDFs (Lambertian, rough conductor, etc.).
    Use SphericalDomain for transmission/refraction BSDFs that sample the full sphere.
    """
    def bounds(self):
        return np.array([[-np.pi, 0.0], [np.pi, 1.0]], dtype=np.float32)

    def aspect(self):
        return 2.0

    def map_forward(self, p):
        """
        Map from [phi, cos(theta)] to unit hemisphere direction (x, y, z).

        Uses Y-up normal: y = cos(theta), x-z plane = tangent plane.
        """
        phi = p[0]
        cos_theta = p[1]
        sin_theta = np.sqrt(np.maximum(0.0, 1.0 - cos_theta ** 2))
        sin_phi = np.sin(phi)
        cos_phi = np.cos(phi)

        return np.stack([
            cos_phi * sin_theta,  # x
            cos_theta,  # y (along normal)
            sin_phi * sin_theta  # z
        ], axis=0)

    def map_backward(self, p):
        """
        Map from unit hemisphere direction (x, y, z) to [phi, cos(theta)].

        Uses Y-up normal: cos(theta) = y component.
        """
        phi = np.arctan2(p[2], p[0])  # atan2(z, x) for azimuth in x-z plane
        cos_theta = p[1]  # y component is cos(theta) for Y-up normal
        return np.stack([phi, cos_theta], axis=0)


class PlanarDomain:
    """Identity map on the plane."""
    def __init__(self, bounds=None):
        if bounds is None:
            self._bounds = np.array([[-1.0, -1.0], [1.0, 1.0]], dtype=np.float32)
        else:
            self._bounds = bounds

    def bounds(self):
        return self._bounds

    def aspect(self):
        extents = self._bounds[1] - self._bounds[0]
        return extents[0] / extents[1]

    def map_forward(self, p):
        return p

    def map_backward(self, p):
        return p


class LineDomain:
    """Identity map on the line."""
    def __init__(self, bounds=[-1.0, 1.0]):
        self._bounds = np.array([[bounds[0], -0.5], [bounds[1], 0.5]], dtype=np.float32)

    def bounds(self):
        return self._bounds

    def aspect(self):
        return None

    def map_forward(self, p):
        return p[0]

    def map_backward(self, p):
        return np.stack([p, np.zeros_like(p)], axis=0)
