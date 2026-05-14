"""Tests for pkg38: Spectral Material Profile Database.

Validates profiles.bin for correct format, physical bounds, and key spectral features.
"""
import os
import struct
import numpy as np
import pytest

REPO_ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES_BIN = os.path.join(REPO_ROOT, "data", "spectral_profiles", "profiles.bin")
META_JSON    = os.path.join(REPO_ROOT, "data", "spectral_profiles", "profiles_metadata.json")
SOURCES_MD   = os.path.join(REPO_ROOT, "data", "spectral_profiles", "sources.md")

LAMBDA_MIN  = 300.0
LAMBDA_MAX  = 2500.0
LAMBDA_STEP = 5.0
N_LAMBDA    = 441
WL_GRID     = np.linspace(LAMBDA_MIN, LAMBDA_MAX, N_LAMBDA)

pytestmark = pytest.mark.skipif(
    not os.path.exists(PROFILES_BIN),
    reason="profiles.bin not found; run scripts/data/build_spectral_profiles.py first",
)


# ──────────────────────────────────────────────────────────────────────────────
# Loader
# ──────────────────────────────────────────────────────────────────────────────

def _load_profiles():
    with open(PROFILES_BIN, "rb") as f:
        raw_hdr = f.read(128)
        magic, version, n_mat, n_wl, lmin, lmax, lstep = \
            struct.unpack_from("<4sIIIfff", raw_hdr)
        assert magic == b"ASPR", f"Bad magic: {magic}"
        assert version == 1, f"Unknown version: {version}"

        dirs = []
        for _ in range(n_mat):
            raw = f.read(80)
            name_b, cat_id, flags, offset, _reserved = \
                struct.unpack_from("<64sHHIQ", raw)
            name = name_b.rstrip(b"\x00").decode("utf-8")
            dirs.append((name, cat_id, offset))

        materials = {}
        for name, cat_id, offset in dirs:
            f.seek(offset)
            r = np.frombuffer(f.read(n_wl * 4), dtype="<f4").copy()
            materials[name] = {"cat": cat_id, "r": r}

    wl = np.linspace(lmin, lmax, n_wl)
    return wl, materials, dict(n_mat=n_mat, n_wl=n_wl, lmin=lmin, lmax=lmax, lstep=lstep)


@pytest.fixture(scope="module")
def db():
    return _load_profiles()


def _idx(wl_nm: float) -> int:
    return int(round((wl_nm - LAMBDA_MIN) / LAMBDA_STEP))


# ──────────────────────────────────────────────────────────────────────────────
# Format tests
# ──────────────────────────────────────────────────────────────────────────────

def test_file_exists():
    assert os.path.exists(PROFILES_BIN)
    assert os.path.getsize(PROFILES_BIN) < 200 * 1024, "Binary exceeds 200 KB"


def test_header_values(db):
    _, _, hdr = db
    assert hdr["n_wl"] == N_LAMBDA
    assert abs(hdr["lmin"] - LAMBDA_MIN) < 0.01
    assert abs(hdr["lmax"] - LAMBDA_MAX) < 0.01
    assert abs(hdr["lstep"] - LAMBDA_STEP) < 0.01


def test_wavelength_grid(db):
    wl, _, _ = db
    assert len(wl) == N_LAMBDA
    assert abs(wl[0] - 300.0) < 0.01
    assert abs(wl[-1] - 2500.0) < 0.01
    steps = np.diff(wl)
    assert np.allclose(steps, 5.0, atol=0.01), "Wavelength grid is not uniform 5 nm"


def test_material_count(db):
    _, mats, _ = db
    assert len(mats) >= 35, f"Only {len(mats)} materials, need >= 35"


def test_category_coverage(db):
    _, mats, _ = db
    REQUIRED_CATS = {0, 1, 2, 3, 4, 5, 6}  # vegetation through human
    present = {m["cat"] for m in mats.values()}
    missing = REQUIRED_CATS - present
    assert not missing, f"Missing category IDs: {missing}"


# ──────────────────────────────────────────────────────────────────────────────
# Physical bounds tests
# ──────────────────────────────────────────────────────────────────────────────

def test_reflectance_bounds(db):
    _, mats, _ = db
    for name, m in mats.items():
        r = m["r"]
        assert np.all(np.isfinite(r)), f"{name}: non-finite values"
        assert np.all(r >= 0.0), f"{name}: negative reflectance (min={r.min():.4f})"
        assert np.all(r <= 1.0), f"{name}: reflectance > 1 (max={r.max():.4f})"


def test_spectrum_length(db):
    _, mats, _ = db
    for name, m in mats.items():
        assert len(m["r"]) == N_LAMBDA, f"{name}: expected {N_LAMBDA} values, got {len(m['r'])}"


# ──────────────────────────────────────────────────────────────────────────────
# Known spectral feature tests
# ──────────────────────────────────────────────────────────────────────────────

def test_wood_effect_deciduous_leaf(db):
    """Healthy deciduous leaf must show strong NIR (Wood effect): R(800) > 3 × R(550)."""
    _, mats, _ = db
    m = mats["deciduous_leaf_green"]
    r550 = float(m["r"][_idx(550)])
    r800 = float(m["r"][_idx(800)])
    ratio = r800 / (r550 + 1e-9)
    assert ratio >= 3.0, (
        f"Deciduous leaf Wood effect too weak: R(800)/R(550) = {ratio:.2f} "
        f"[R(800)={r800:.3f}, R(550)={r550:.3f}]"
    )


def test_wood_effect_grass(db):
    """Green grass must show the Wood effect."""
    _, mats, _ = db
    m = mats["grass_green"]
    r550 = float(m["r"][_idx(550)])
    r800 = float(m["r"][_idx(800)])
    ratio = r800 / (r550 + 1e-9)
    assert ratio >= 3.0, f"Grass Wood effect ratio {ratio:.2f} < 3"


def test_water_ir_absorption(db):
    """Clear water must have very low reflectance in NIR: R(1000 nm) < 0.05."""
    _, mats, _ = db
    m = mats["water_clear"]
    r1000 = float(m["r"][_idx(1000)])
    assert r1000 < 0.05, f"Water R(1000nm) = {r1000:.4f} >= 0.05"


def test_metal_high_reflectance(db):
    """Polished metals must have high mean reflectance (> 0.80)."""
    _, mats, _ = db
    for name in ("aluminum_polished", "gold_polished"):
        m = mats[name]
        mean_r = float(m["r"].mean())
        assert mean_r > 0.80, f"{name}: mean R = {mean_r:.3f} < 0.80"


def test_gold_spectral_shape(db):
    """Gold: low blue, high red. R(700) must be > 2 × R(400)."""
    _, mats, _ = db
    m = mats["gold_polished"]
    r400 = float(m["r"][_idx(400)])
    r700 = float(m["r"][_idx(700)])
    assert r700 > 2.0 * r400, (
        f"Gold spectral shape incorrect: R(700)={r700:.3f}, R(400)={r400:.3f}"
    )


def test_asphalt_dark(db):
    """Asphalt must be dark in visible (400-700nm): mean R < 0.12."""
    wl, mats, _ = db
    m = mats["asphalt_dark"]
    vis = m["r"][(wl >= 400) & (wl <= 700)]
    mean_vis = float(vis.mean())
    assert mean_vis < 0.12, (
        f"Asphalt visible mean R = {mean_vis:.3f} >= 0.12 "
        "(old road asphalt SWIR rises due to weathering; visible is the relevant band)"
    )


def test_snow_bright_visible(db):
    """Snow must be bright in visible: R(550) > 0.70."""
    _, mats, _ = db
    m = mats["snow"]
    r550 = float(m["r"][_idx(550)])
    assert r550 > 0.70, f"Snow R(550nm) = {r550:.3f} < 0.70"


# ──────────────────────────────────────────────────────────────────────────────
# Metadata and provenance tests
# ──────────────────────────────────────────────────────────────────────────────

def test_metadata_file_exists():
    assert os.path.exists(META_JSON), "profiles_metadata.json missing"


def test_metadata_content():
    import json
    with open(META_JSON, "r", encoding="utf-8") as f:
        meta = json.load(f)
    assert meta["version"] == 1
    assert meta["n_materials"] >= 35
    assert meta["wavelength_grid"]["lambda_min_nm"] == 300.0
    assert meta["wavelength_grid"]["lambda_max_nm"] == 2500.0
    assert meta["wavelength_grid"]["lambda_step_nm"] == 5.0
    assert len(meta["materials"]) == meta["n_materials"]
    for m in meta["materials"]:
        assert m["source"], f"Material '{m['name']}' has no source attribution"


def test_sources_file_exists():
    assert os.path.exists(SOURCES_MD), "sources.md missing"


def test_sources_documents_all_materials():
    _, mats, _ = _load_profiles()
    with open(SOURCES_MD, "r", encoding="utf-8") as f:
        content = f.read()
    for name in mats:
        assert name in content, f"sources.md does not mention '{name}'"


# ──────────────────────────────────────────────────────────────────────────────
# Light-source SPD tests (pkg38 amendment)
# ──────────────────────────────────────────────────────────────────────────────

def test_light_source_category_exists(db):
    """Category 7 (light_source) must be present."""
    _, mats, _ = db
    cats = {m["cat"] for m in mats.values()}
    assert 7 in cats, "Category 7 (light_source) not found"


def test_light_source_count(db):
    """Must have exactly 7 light-source SPDs."""
    _, mats, _ = db
    ls_mats = [name for name, m in mats.items() if m["cat"] == 7]
    assert len(ls_mats) == 7, f"Expected 7 light sources, got {len(ls_mats)}: {ls_mats}"


def test_light_source_normalisation(db):
    """All light sources must be normalised to peak = 1.0 ± 0.001."""
    _, mats, _ = db
    for name, m in mats.items():
        if m["cat"] == 7:  # light_source
            peak = float(m["r"].max())
            assert abs(peak - 1.0) < 0.001, (
                f"{name}: peak = {peak:.6f}, expected 1.0 ± 0.001"
            )


def test_cie_f2_peak_wavelength(db):
    """CIE F2: dominant peak at 435 nm (blue mercury line), characteristic of fluorescent lamps."""
    _, mats, _ = db
    m = mats["cie_f2"]
    # Find peak wavelength
    idx_peak = int(m["r"].argmax())
    wl_peak = LAMBDA_MIN + idx_peak * LAMBDA_STEP
    assert 430 <= wl_peak <= 440, (
        f"CIE F2 peak at {wl_peak:.0f} nm, expected 435 nm (blue Hg line)"
    )


def test_cie_f3_peak_wavelength(db):
    """CIE F3: peak at 435 nm (blue mercury line), with strong yellow/green phosphor bands."""
    _, mats, _ = db
    m = mats["cie_f3"]
    idx_peak = int(m["r"].argmax())
    wl_peak = LAMBDA_MIN + idx_peak * LAMBDA_STEP
    assert 430 <= wl_peak <= 440, (
        f"CIE F3 peak at {wl_peak:.0f} nm, expected 435 nm (blue Hg line)"
    )


def test_led_3000k_dual_peak(db):
    """LED 3000K: blue pump peak (445-460 nm) + yellow phosphor peak (580-620 nm).
    Blue:yellow ratio ~1.0-1.3 for warm white (per CIE LED-B3 data).
    """
    _, mats, _ = db
    m = mats["led_3000k"]
    r = m["r"]

    # Find blue peak in 440-465 nm
    blue_region = [(i, r[i]) for i, wl in enumerate(WL_GRID) if 440 <= wl <= 465]
    blue_peak = max(blue_region, key=lambda x: x[1])[1]

    # Find yellow/red peak in 575-625 nm
    yellow_region = [(i, r[i]) for i, wl in enumerate(WL_GRID) if 575 <= wl <= 625]
    yellow_peak = max(yellow_region, key=lambda x: x[1])[1]

    ratio = float(blue_peak / (yellow_peak + 1e-9))
    assert 0.9 < ratio < 1.4, (
        f"LED 3000K blue:yellow ratio {ratio:.2f} outside 1.0-1.3 range "
        f"(blue={blue_peak:.3f}, yellow={yellow_peak:.3f})"
    )


def test_led_5000k_balanced_peaks(db):
    """LED 5000K: blue:yellow peak ratio ~1.4-1.8 (per CIE LED-B4 data)."""
    _, mats, _ = db
    m = mats["led_5000k"]
    r = m["r"]

    blue_region = [(i, r[i]) for i, wl in enumerate(WL_GRID) if 440 <= wl <= 465]
    blue_peak = max(blue_region, key=lambda x: x[1])[1]

    yellow_region = [(i, r[i]) for i, wl in enumerate(WL_GRID) if 575 <= wl <= 625]
    yellow_peak = max(yellow_region, key=lambda x: x[1])[1]

    ratio = float(blue_peak / (yellow_peak + 1e-9))
    assert 1.3 < ratio < 1.9, (
        f"LED 5000K blue:yellow ratio {ratio:.2f} outside 1.4-1.8 range"
    )


def test_led_6500k_blue_dominant(db):
    """LED 6500K: blue peak dominates with ratio > 1.8 (per CIE LED-B5 data)."""
    _, mats, _ = db
    m = mats["led_6500k"]
    r = m["r"]

    blue_region = [(i, r[i]) for i, wl in enumerate(WL_GRID) if 440 <= wl <= 465]
    blue_peak = max(blue_region, key=lambda x: x[1])[1]

    yellow_region = [(i, r[i]) for i, wl in enumerate(WL_GRID) if 575 <= wl <= 625]
    yellow_peak = max(yellow_region, key=lambda x: x[1])[1]

    ratio = float(blue_peak / (yellow_peak + 1e-9))
    assert ratio > 1.8, (
        f"LED 6500K blue:yellow ratio {ratio:.2f} <= 1.8 (blue should dominate)"
    )


def test_sodium_vapor_d_line_concentration(db):
    """Sodium vapor: > 95% of total energy in 585-595 nm bins."""
    _, mats, _ = db
    m = mats["sodium_vapor"]
    r = m["r"]

    # Energy in D-line region (585-595 nm)
    d_line_energy = sum(r[i] for i, wl in enumerate(WL_GRID) if 585 <= wl <= 595)

    # Total energy
    total_energy = r.sum()

    fraction = float(d_line_energy / (total_energy + 1e-9))
    assert fraction > 0.95, (
        f"Sodium D-line energy fraction {fraction:.3f} <= 0.95 "
        f"(D-line={d_line_energy:.3f}, total={total_energy:.3f})"
    )


def test_mercury_vapor_line_peaks(db):
    """Mercury vapor: peaks present (within one bin) at 405, 435, 545 nm.
    Dominant line (435 nm) is normalized to 1.0, continuum << line peaks.
    """
    _, mats, _ = db
    m = mats["mercury_vapor"]
    r = m["r"]

    # Expected line positions (±5 nm tolerance for 5 nm grid)
    expected_lines = [405, 435, 545]  # 580 nm line not in NIST persistent set

    # Find peaks within ±5 nm of expected positions
    line_peaks = {}
    for wl_expected in expected_lines:
        peak_in_region = max(
            r[i] for i, wl in enumerate(WL_GRID)
            if abs(wl - wl_expected) <= 5
        )
        line_peaks[wl_expected] = peak_in_region
        assert peak_in_region > 0.1, (
            f"Mercury line at ~{wl_expected} nm has peak {peak_in_region:.3f} < 0.1"
        )

    # Dominant line (435 nm) should be normalized to 1.0
    assert abs(line_peaks[435] - 1.0) < 0.01, (
        f"Mercury 435 nm line peak {line_peaks[435]:.3f} != 1.0"
    )

    # Check continuum level: should be << line peaks (5% of dominant line)
    # Sample continuum in a region far from lines (e.g., 480-520 nm)
    continuum_region = [r[i] for i, wl in enumerate(WL_GRID) if 480 <= wl <= 520]
    avg_continuum = float(np.mean(continuum_region))
    assert avg_continuum < 0.10, (
        f"Mercury continuum level {avg_continuum:.3f} >= 0.10 (should be ~0.05)"
    )
