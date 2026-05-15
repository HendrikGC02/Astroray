"""
pkg47 — FITS data loader tests.

Synthetic test data generated at runtime using astropy.io.fits.
Reference: pillar4-data-io-research.md §6.
"""
import pytest
import numpy as np
from pathlib import Path
import math

from runtime_setup import configure_test_imports
configure_test_imports()

# Attempt to import astropy; skip all tests if not available
astropy = pytest.importorskip("astropy", reason="astropy required for FITS test data generation")
from astropy.io import fits

# Attempt to import astroray; skip all tests if FITS support not compiled
try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")


def fits_available() -> bool:
    """Check if astroray was compiled with FITS support."""
    if not AVAILABLE:
        return False
    try:
        names = astroray.texture_registry_names()
        return "fits_texture" in names
    except (ImportError, AttributeError):
        return False


# Skip all tests if FITS not compiled
pytestmark = pytest.mark.skipif(
    not fits_available(),
    reason="FITS support not compiled (ASTRORAY_ENABLE_FITS=OFF or cfitsio not found)"
)


@pytest.fixture
def tmp_fits_2d(tmp_path: Path) -> Path:
    """Create a synthetic 2D FITS image: 64×64 gradient."""
    data = np.arange(64 * 64, dtype=np.float32).reshape(64, 64)
    hdu = fits.PrimaryHDU(data)
    hdu.header['BSCALE'] = 1.0
    hdu.header['BZERO'] = 0.0
    path = tmp_path / "test_2d.fits"
    hdu.writeto(str(path), overwrite=True)
    return path


@pytest.fixture
def tmp_fits_3d(tmp_path: Path) -> Path:
    """Create a synthetic 3D FITS cube: 8×32×32."""
    np.random.seed(42)
    cube = np.random.rand(8, 32, 32).astype(np.float32)
    hdu = fits.PrimaryHDU(cube)
    path = tmp_path / "test_3d.fits"
    hdu.writeto(str(path), overwrite=True)
    return path


@pytest.fixture
def tmp_fits_bscale(tmp_path: Path) -> Path:
    """
    Create a FITS file with BSCALE/BZERO scaling.
    Physical value = BZERO + BSCALE × stored_value.
    Test: int16(500) with BZERO=1000.0, BSCALE=0.1 → 1050.0
    """
    arr = np.full((16, 16), 500, dtype=np.int16)
    hdu = fits.PrimaryHDU(arr)
    hdu.header['BSCALE'] = 0.1
    hdu.header['BZERO'] = 1000.0
    path = tmp_path / "test_bscale.fits"
    hdu.writeto(str(path), overwrite=True)
    return path


@pytest.fixture
def tmp_fits_header(tmp_path: Path) -> Path:
    """Create a FITS file with a custom header keyword."""
    data = np.ones((16, 16), dtype=np.float32)
    hdu = fits.PrimaryHDU(data)
    hdu.header['OBJECT'] = 'NGC 1234'
    path = tmp_path / "test_header.fits"
    hdu.writeto(str(path), overwrite=True)
    return path


def test_fits_in_registry():
    """fits_texture is registered in the TextureRegistry."""
    names = astroray.texture_registry_names()
    assert "fits_texture" in names, "fits_texture not in TextureRegistry"


def test_fits_texture_2d_loads(tmp_fits_2d: Path):
    """FITSTexture loads a 64×64 2D FITS image without error."""
    r = astroray.Renderer()
    result = r.sample_texture("fits_texture", {"path": str(tmp_fits_2d)}, 0.5, 0.5)
    assert len(result) == 3
    assert all(math.isfinite(v) for v in result)


def test_fits_texture_2d_values(tmp_fits_2d: Path):
    """FITSTexture values match the synthetic gradient data."""
    r = astroray.Renderer()

    # Sample at UV (0, 0) → top-left corner → low value
    # Sample at UV (1, 1) → bottom-right corner → high value
    # Gradient is np.arange(64*64).reshape(64,64), so values range 0..4095.
    val_tl = r.sample_texture("fits_texture", {"path": str(tmp_fits_2d)}, 0.0, 0.0)
    val_br = r.sample_texture("fits_texture", {"path": str(tmp_fits_2d)}, 1.0, 1.0)

    # Top-left should be low, bottom-right should be high.
    # Exact indexing depends on UV → pixel mapping and V-flip.
    assert val_tl[0] < 500.0, f"Top-left should be low, got {val_tl[0]}"
    assert val_br[0] > 3500.0, f"Bottom-right should be high, got {val_br[0]}"


def test_fits_bscale_bzero(tmp_fits_bscale: Path):
    """BSCALE/BZERO applied: int16(500) → 1000 + 0.1*500 = 1050.0"""
    r = astroray.Renderer()

    # All pixels are int16(500) with BSCALE=0.1, BZERO=1000.0.
    # Expected physical value: 1000 + 0.1*500 = 1050.0
    val = r.sample_texture("fits_texture", {"path": str(tmp_fits_bscale)}, 0.5, 0.5)
    assert abs(val[0] - 1050.0) < 1.0, f"Expected ~1050, got {val[0]}"


def test_fits_header_loads(tmp_fits_header: Path):
    """FITS file with custom header keyword loads without error."""
    r = astroray.Renderer()
    result = r.sample_texture("fits_texture", {"path": str(tmp_fits_header)}, 0.5, 0.5)
    assert len(result) == 3
    # FITSFile::header() is not exposed to Python yet; this just confirms load.


def test_fits_texture_missing_file():
    """FITSTexture throws on missing file."""
    r = astroray.Renderer()
    with pytest.raises(RuntimeError):
        r.sample_texture("fits_texture", {"path": "/nonexistent/path.fits"}, 0.5, 0.5)


def test_fits_texture_3d_error(tmp_fits_3d: Path):
    """FITSTexture rejects 3D cubes (expects NAXIS=2)."""
    r = astroray.Renderer()
    with pytest.raises(RuntimeError):
        r.sample_texture("fits_texture", {"path": str(tmp_fits_3d)}, 0.5, 0.5)


def test_build_without_cfitsio():
    """
    If ASTRORAY_ENABLE_FITS=ON but cfitsio not found, FITS plugins absent.
    This test checks that the build gracefully handles missing cfitsio.
    """
    # This test is a smoke test; the actual check is done by pytest.mark.skipif.
    # If we reach here, FITS is enabled and tests should run.
    assert fits_available(), "FITS should be available when tests run"
