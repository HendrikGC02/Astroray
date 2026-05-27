"""Public metric API for the reference bank.

Every metric takes float32 RGB images (HxWx3, linear scene-referred unless noted),
and returns a single scalar plus an optional debug artifact (heatmap, mask, etc).
Gate evaluation compares the scalar against a threshold from the scene's gates.toml.
"""

from .ssim import compute_ssim
from .delta_e_2000 import compute_delta_e_2000
from .phash import compute_phash_distance
from .hue_spread import compute_hue_spread
from .bright_coverage import compute_bright_coverage
from .dark_disk import compute_dark_disk_fraction

__all__ = [
    "compute_ssim",
    "compute_delta_e_2000",
    "compute_phash_distance",
    "compute_hue_spread",
    "compute_bright_coverage",
    "compute_dark_disk_fraction",
]
