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

pytestmark = pytest.mark.skipif(
    not os.path.exists(PROFILES_BIN),
    reason="profiles.bin not found; run scripts/build_spectral_profiles.py first",
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
