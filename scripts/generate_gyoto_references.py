#!/usr/bin/env python
"""Generate pkg41 Kerr validation fixtures.

The PNG fixtures are deterministic image-plane shadow masks generated from
the published Kerr celestial-coordinate equations in Bardeen, Press &
Teukolsky 1972 and Chandrasekhar 1983. GYOTO (Vincent et al. 2011) and
RAPTOR (Bronzwaer et al. 2018) are cited cross-validation references only:
their GPL-compatible restrictions mean no code or scene files are mirrored
into Astroray.

Run from the repository root:

    python scripts/generate_gyoto_references.py

The script does not require GYOTO. If a future maintainer regenerates these
from an installed GYOTO binary, keep this analytic path as the license-clean
fallback and update tests/reference/kerr/README.md with provenance details.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
REF_DIR = ROOT / "tests" / "reference" / "kerr"
SPINS = (0.0, 0.5, 0.9, 0.998)
IMAGE_SIZE = 256
INCLINATION_DEG = 80.0
PIXELS_PER_M = 18.0


def isco_radius(a: float, prograde: bool = True, m: float = 1.0) -> float:
    """BPT 1972 eq. 2.21, geometric units G=c=1."""
    chi = abs(a / m)
    z1 = 1.0 + (1.0 - chi * chi) ** (1.0 / 3.0) * (
        (1.0 + chi) ** (1.0 / 3.0) + (1.0 - chi) ** (1.0 / 3.0)
    )
    z2 = math.sqrt(3.0 * chi * chi + z1 * z1)
    term = math.sqrt(max(0.0, (3.0 - z1) * (3.0 + z1 + 2.0 * z2)))
    return m * (3.0 + z2 - term if prograde else 3.0 + z2 + term)


def photon_ring_radius(a: float, prograde: bool = True, m: float = 1.0) -> float:
    """Equatorial circular photon orbit radius, BPT 1972."""
    chi = max(-1.0, min(1.0, a / m))
    arg = -chi if prograde else chi
    return 2.0 * m * (1.0 + math.cos((2.0 / 3.0) * math.acos(arg)))


def horizon_radius(a: float, m: float = 1.0) -> float:
    return m + math.sqrt(max(0.0, m * m - a * a))


def horizon_angular_velocity(a: float, m: float = 1.0) -> float:
    r_plus = horizon_radius(a, m)
    return a / (r_plus * r_plus + a * a) if a else 0.0


def orbital_frequency(a: float, r: float, prograde: bool = True, m: float = 1.0) -> float:
    sign = 1.0 if prograde else -1.0
    return sign * math.sqrt(m) / (r ** 1.5 + sign * a * math.sqrt(m))


def impact_parameter_xi(a: float, r: float, m: float = 1.0) -> float:
    if abs(a) < 1e-12:
        return math.sqrt(27.0) * m
    return (r * r * (r - 3.0 * m) + a * a * (r + m)) / (a * (m - r))


def impact_parameter_eta(a: float, r: float, m: float = 1.0) -> float:
    if abs(a) < 1e-12:
        return 0.0
    numerator = r ** 3 * (4.0 * a * a * m - r * (r - 3.0 * m) ** 2)
    denominator = a * a * (m - r) ** 2
    return numerator / denominator


def shadow_boundary(a: float, inclination: float, n: int = 1200) -> np.ndarray:
    """Bardeen celestial coordinates (alpha, beta) for the Kerr shadow."""
    if abs(a) < 1e-12:
        angle = np.linspace(0.0, 2.0 * math.pi, n, endpoint=False)
        radius = math.sqrt(27.0)
        return np.column_stack((radius * np.cos(angle), radius * np.sin(angle)))

    sin_i = math.sin(inclination)
    cos_i = math.cos(inclination)
    cot_i = cos_i / max(sin_i, 1e-12)
    r_min = photon_ring_radius(a, prograde=True)
    r_max = photon_ring_radius(a, prograde=False)
    upper: list[tuple[float, float]] = []
    lower: list[tuple[float, float]] = []
    for r in np.linspace(r_min, r_max, n):
        xi = impact_parameter_xi(a, float(r))
        eta = impact_parameter_eta(a, float(r))
        beta2 = eta + a * a * cos_i * cos_i - xi * xi * cot_i * cot_i
        if beta2 < -1e-9:
            continue
        beta = math.sqrt(max(0.0, beta2))
        alpha = -xi / sin_i
        upper.append((alpha, beta))
        lower.append((alpha, -beta))
    return np.array(upper + list(reversed(lower)), dtype=np.float64)


def rasterize_shadow(points: np.ndarray, size: int = IMAGE_SIZE) -> Image.Image:
    center = (size - 1) * 0.5
    xy = [
        (center + float(alpha) * PIXELS_PER_M, center - float(beta) * PIXELS_PER_M)
        for alpha, beta in points
    ]
    img = Image.new("L", (size, size), 230)
    draw = ImageDraw.Draw(img)
    draw.polygon(xy, fill=8)
    draw.line(xy + [xy[0]], fill=120, width=2)
    return img


def image_metrics(img: Image.Image) -> dict[str, float | list[int]]:
    arr = np.asarray(img, dtype=np.float32)
    mask = arr < 64.0
    y, x = np.nonzero(mask)
    if len(x) == 0:
        raise RuntimeError("shadow mask is empty")
    area = float(mask.sum())
    cx = float(x.mean())
    cy = float(y.mean())
    width = int(x.max() - x.min() + 1)
    height = int(y.max() - y.min() + 1)
    return {
        "area_px": area,
        "centroid_x_px": cx,
        "centroid_y_px": cy,
        "bbox_px": [int(x.min()), int(y.min()), int(x.max()), int(y.max())],
        "width_px": width,
        "height_px": height,
        "circularity_width_height_ratio": float(width / height),
    }


def analytic_records() -> dict[str, object]:
    records: dict[str, object] = {
        "meta": {
            "source": (
                "Bardeen, Press, Teukolsky 1972 ApJ 178, 347; "
                "Chandrasekhar 1983 ch. 7; GYOTO/RAPTOR/ipole cited for "
                "independent cross-validation only"
            ),
            "image_size": IMAGE_SIZE,
            "inclination_deg": INCLINATION_DEG,
            "pixels_per_M": PIXELS_PER_M,
        },
        "spins": {},
    }
    spin_records: dict[str, object] = {}
    for a in SPINS:
        pro_isco = isco_radius(a, True)
        retro_isco = isco_radius(a, False)
        pro_ph = photon_ring_radius(a, True)
        retro_ph = photon_ring_radius(a, False)
        spin_records[f"{a:g}"] = {
            "a": a,
            "isco_prograde": pro_isco,
            "isco_retrograde": retro_isco,
            "photon_ring_prograde": pro_ph,
            "photon_ring_retrograde": retro_ph,
            "orbital_frequency_isco_prograde": orbital_frequency(a, pro_isco, True),
            "orbital_period_isco_prograde": 2.0 * math.pi / orbital_frequency(a, pro_isco, True),
            "orbital_frequency_isco_retrograde": orbital_frequency(a, retro_isco, False),
            "orbital_period_isco_retrograde": abs(2.0 * math.pi / orbital_frequency(a, retro_isco, False)),
            "horizon_radius": horizon_radius(a),
            "horizon_angular_velocity": horizon_angular_velocity(a),
        }
    records["spins"] = spin_records
    return records


def main() -> int:
    REF_DIR.mkdir(parents=True, exist_ok=True)
    records = analytic_records()
    spins = records["spins"]
    assert isinstance(spins, dict)

    for a in SPINS:
        points = shadow_boundary(a, math.radians(INCLINATION_DEG))
        img = rasterize_shadow(points)
        name = f"gyoto_a{str(a).replace('.', '')}_256.png"
        if a == 0.0:
            name = "gyoto_a0_256.png"
        img.save(REF_DIR / name)
        record = spins[f"{a:g}"]
        assert isinstance(record, dict)
        record["reference_image"] = name
        record["shadow_metrics"] = image_metrics(img)

    (REF_DIR / "analytic_orbits.json").write_text(
        json.dumps(records, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (REF_DIR / "README.md").write_text(
        "# Kerr validation references\n\n"
        "These pkg41 fixtures are deterministic, license-clean reference data for\n"
        "Kerr metric validation. The orbit scalars and shadow contours are generated\n"
        "from Bardeen, Press & Teukolsky 1972 (ApJ 178, 347) and Chandrasekhar\n"
        "1983, ch. 7. GYOTO, RAPTOR, and ipole are cited in the package spec and\n"
        "research notes as independent cross-validation references only; no GPL or\n"
        "CeCILL code or scene files are mirrored here.\n\n"
        "Regenerate with `python scripts/generate_gyoto_references.py` from the\n"
        "repository root. The historical `gyoto_*` filenames are kept because the\n"
        "pkg41 spec names the reference image slots that way.\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
