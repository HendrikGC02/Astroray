"""Build the Astroray spectral material reflectance database (pkg38).

Produces:
  data/spectral_profiles/profiles.bin          ASPR binary database
  data/spectral_profiles/profiles_metadata.json  Material metadata
  data/spectral_profiles/sources.md              Attribution

Sources:
  USGS Spectral Library v7  (public domain, DOI 10.5066/F7RR1WDJ)
  ECOSTRESS Spectral Library (public domain, NASA/JPL)
  Rakić et al. 1998 Lorentz-Drude model for polished metals
  Bashkatov et al. 2005 in-vivo skin NIR measurements
"""
import json
import os
import struct
import urllib.request
import zipfile
from typing import Optional
import numpy as np

# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT   = os.path.dirname(os.path.dirname(SCRIPT_DIR))
OUT_DIR     = os.path.join(REPO_ROOT, "data", "spectral_profiles")
CACHE_DIR   = os.path.join(OUT_DIR, "_cache")

LAMBDA_MIN  = 300.0   # nm
LAMBDA_MAX  = 2500.0  # nm
LAMBDA_STEP = 5.0     # nm
N_LAMBDA    = 441     # (2500-300)/5 + 1

USGS_ZIP_URL = (
    "https://www.sciencebase.gov/catalog/file/get/"
    "586e8c88e4b0f5ce109fccae"
    "?f=__disk__a7%2F4f%2F91%2Fa74f913e0b7d1b8123ad059e52506a02b75a2832"
)
USGS_ZIP_NAME = "ASCIIdata_splib07a.zip"
ECOSTRESS_BASE = "https://speclib.jpl.nasa.gov/ecospeclibdata/"

# Category IDs
CAT = dict(vegetation=0, earth=1, building=2, metal=3, fabric=4, paint=5, human=6, light_source=7)

# Wavelength grid
WL_GRID = np.linspace(LAMBDA_MIN, LAMBDA_MAX, N_LAMBDA)  # nm

# ──────────────────────────────────────────────────────────────────────────────
# Download helpers
# ──────────────────────────────────────────────────────────────────────────────

def _fetch(url: str, dest: str, label: str) -> None:
    if os.path.exists(dest):
        return
    print(f"  Downloading {label}...")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()
    with open(dest, "wb") as fh:
        fh.write(data)
    print(f"  Saved {len(data)//1024} KB -> {os.path.basename(dest)}")


def _ecostress_file(filename: str) -> str:
    dest = os.path.join(CACHE_DIR, filename)
    _fetch(ECOSTRESS_BASE + filename, dest, filename)
    return dest


def _usgs_zip() -> str:
    dest = os.path.join(CACHE_DIR, USGS_ZIP_NAME)
    _fetch(USGS_ZIP_URL, dest, USGS_ZIP_NAME)
    return dest


# ──────────────────────────────────────────────────────────────────────────────
# USGS parsing
# ──────────────────────────────────────────────────────────────────────────────

# Loaded once and shared
_usgs_wavelengths: Optional[np.ndarray] = None
_usgs_zip_obj: Optional[zipfile.ZipFile] = None

def _get_usgs_zip() -> zipfile.ZipFile:
    global _usgs_zip_obj
    if _usgs_zip_obj is None:
        _usgs_zip_obj = zipfile.ZipFile(_usgs_zip())
    return _usgs_zip_obj


def _get_usgs_wavelengths() -> np.ndarray:
    global _usgs_wavelengths
    if _usgs_wavelengths is None:
        zf = _get_usgs_zip()
        with zf.open("ASCIIdata_splib07a/splib07a_Wavelengths_ASD_0.35-2.5_microns_2151_ch.txt") as fh:
            lines = fh.read().decode("utf-8", errors="replace").split("\n")
        wls = []
        for line in lines[1:]:
            line = line.strip()
            if line:
                try:
                    wls.append(float(line) * 1000.0)  # μm -> nm
                except ValueError:
                    pass
        _usgs_wavelengths = np.array(wls)
    return _usgs_wavelengths


def read_usgs(internal_path: str) -> tuple[np.ndarray, np.ndarray]:
    """Return (wavelengths_nm, reflectance_fraction) from a USGS ASDFRa file."""
    NAN_SENTINEL = -1.0e+33  # values below this are no-data

    zf = _get_usgs_zip()
    wavelengths = _get_usgs_wavelengths()

    with zf.open(internal_path) as fh:
        lines = fh.read().decode("utf-8", errors="replace").split("\n")

    values = []
    for line in lines[1:]:
        line = line.strip()
        if line:
            try:
                values.append(float(line))
            except ValueError:
                pass

    if len(values) != len(wavelengths):
        raise ValueError(
            f"USGS: expected {len(wavelengths)} values, got {len(values)} in {internal_path}"
        )

    arr = np.array(values)
    valid = arr > NAN_SENTINEL
    wl_valid = wavelengths[valid]
    r_valid  = arr[valid]
    return wl_valid, r_valid


# ──────────────────────────────────────────────────────────────────────────────
# ECOSTRESS parsing
# ──────────────────────────────────────────────────────────────────────────────

def read_ecostress(filename: str) -> tuple[np.ndarray, np.ndarray]:
    """Return (wavelengths_nm, reflectance_fraction) from an ECOSTRESS file."""
    path = _ecostress_file(filename)
    wavelengths, reflectances = [], []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            try:
                wl   = float(parts[0]) * 1000.0  # μm -> nm
                refl = float(parts[1])
                if 200 < wl < 3000 and -1.0 < refl < 200.0:
                    wavelengths.append(wl)
                    reflectances.append(refl)
            except ValueError:
                continue

    wl_arr = np.array(wavelengths)
    r_arr  = np.array(reflectances)

    # ECOSTRESS Y units are "Reflectance (percentage)" for UCSB ASD files
    # JHU Beckman files also use percentage (0-100 range)
    # Normalise to 0-1 if values exceed 1.5
    if r_arr.size > 0 and np.nanmax(r_arr) > 1.5:
        r_arr = r_arr / 100.0

    return wl_arr, r_arr


# ──────────────────────────────────────────────────────────────────────────────
# Rakić 1998 Lorentz-Drude model for polished metals
# ──────────────────────────────────────────────────────────────────────────────
# Parameters from Table 1 of: Rakić et al., Appl. Opt. 37(22), 5271-5283 (1998).
# ε(ω) = 1 - f0·ωp²/(ω·(ω+i·Γ0)) + Σ fj·ωp²/(ωj²-ω²-i·ω·Γj)
# All frequencies in eV; λ_nm = 1240/E_eV.

_LD_PARAMS = {
    "Al": dict(
        wp=14.98,
        f0=0.523, G0=0.047,
        f =[0.227, 0.050, 0.166, 0.030],
        G =[0.333, 0.312, 1.351, 3.382],
        w =[0.162, 1.544, 1.808, 3.473],
    ),
    "Au": dict(
        wp=9.03,
        f0=0.760, G0=0.053,
        f =[0.024, 0.010, 0.071, 0.601, 4.384],
        G =[0.241, 0.345, 0.870, 2.494, 2.214],
        w =[0.415, 0.830, 2.969, 4.304, 13.32],
    ),
    "Cu": dict(
        wp=10.83,
        f0=0.575, G0=0.030,
        f =[0.061, 0.104, 0.723, 0.638],
        G =[0.378, 1.056, 3.213, 4.305],
        w =[0.291, 2.957, 5.300, 11.18],
    ),
    "Ag": dict(
        wp=9.01,
        f0=0.845, G0=0.048,
        f =[0.065, 0.124, 0.011, 0.840, 5.646],
        G =[3.886, 0.452, 0.065, 0.916, 2.419],
        w =[0.816, 4.481, 8.185, 9.083, 20.29],
    ),
}


def rakic_reflectance(symbol: str, wl_nm: np.ndarray) -> np.ndarray:
    """Compute normal-incidence Fresnel reflectance from Rakić 1998 parameters."""
    p = _LD_PARAMS[symbol]
    wp = p["wp"]
    E = 1240.0 / wl_nm  # eV

    # Drude free-electron term
    eps = 1.0 - (p["f0"] * wp**2) / (E * (E + 1j * p["G0"]))

    # Lorentz oscillator terms
    for fj, Gj, wj in zip(p["f"], p["G"], p["w"]):
        eps += (fj * wp**2) / (wj**2 - E**2 - 1j * E * Gj)

    nk = np.sqrt(eps)
    n, k = nk.real, nk.imag
    # Ensure k >= 0 (absorbing medium)
    k = np.abs(k)
    R = ((n - 1.0)**2 + k**2) / ((n + 1.0)**2 + k**2)
    return np.clip(R, 0.0, 1.0)


# ──────────────────────────────────────────────────────────────────────────────
# Resampling and QC pipeline
# ──────────────────────────────────────────────────────────────────────────────

def resample_to_grid(wl_src: np.ndarray, r_src: np.ndarray) -> np.ndarray:
    """Resample spectrum to the standard 5 nm grid via linear interpolation.

    Regions outside the source range are filled with flat extrapolation
    (first/last valid value held constant).
    """
    if len(wl_src) < 2:
        raise ValueError("Need at least 2 source points")

    # Sort by wavelength
    order = np.argsort(wl_src)
    wl_src = wl_src[order]
    r_src  = r_src[order]

    r_out = np.interp(WL_GRID, wl_src, r_src,
                      left=r_src[0], right=r_src[-1])
    return r_out


def quality_control(r: np.ndarray, name: str) -> np.ndarray:
    """Apply QC: replace NaN/Inf, clamp to [0,1], 3-pt moving average."""
    r = np.array(r, dtype=np.float32)
    r = np.where(np.isfinite(r), r, 0.0)
    r = np.clip(r, 0.0, 1.0)
    # 3-point moving average smoothing
    kernel = np.ones(3) / 3.0
    r_smooth = np.convolve(r, kernel, mode="same")
    # Preserve endpoints (convolve 'same' handles edges but let's be explicit)
    r_smooth[0]  = (r[0] + r[1]) / 2.0
    r_smooth[-1] = (r[-2] + r[-1]) / 2.0
    return np.clip(r_smooth.astype(np.float32), 0.0, 1.0)


def make_spectrum(wl: np.ndarray, r: np.ndarray, name: str) -> np.ndarray:
    r_grid = resample_to_grid(wl, r)
    return quality_control(r_grid, name)


# ──────────────────────────────────────────────────────────────────────────────
# Skin spectra  (Bashkatov et al. 2005, digitised key points)
# ──────────────────────────────────────────────────────────────────────────────
# Reference: A.N. Bashkatov, E.A. Genina, V.I. Kochubey, V.V. Tuchin,
#   "Optical properties of human skin, subcutaneous and mucous tissues
#    in the wavelength range from 400 to 2000 nm",
#   J. Phys. D 38 (2005) 2543-2555.  Figure 3 / Table data.
# Values represent diffuse reflectance (%) measured in-vivo on forearm skin.

_SKIN_LIGHT_KP = np.array([
    [400,  12.0], [420,  15.0], [450,  20.0], [480,  23.0], [500,  27.0],
    [520,  32.0], [540,  35.0], [550,  38.0], [570,  42.0], [590,  47.0],
    [600,  50.0], [620,  54.0], [650,  55.0], [670,  53.0], [700,  52.0],
    [720,  55.0], [750,  57.0], [780,  59.0], [800,  60.0], [850,  61.0],
    [900,  60.0], [950,  59.0],[1000,  58.0],[1050,  56.0],[1100,  54.0],
   [1150,  52.0],[1200,  50.0],[1250,  47.0],[1300,  46.0],[1350,  40.0],
   [1400,  35.0],[1450,  32.0],[1500,  37.0],[1550,  40.0],[1600,  42.0],
   [1650,  43.0],[1700,  41.0],[1750,  37.0],[1800,  33.0],[1850,  30.0],
   [1900,  29.0],[1950,  28.0],[2000,  27.0],[2100,  26.0],[2200,  25.0],
   [2300,  24.0],[2400,  23.0],[2500,  22.0],
])

def _skin_spectrum(scale_vis: float) -> np.ndarray:
    """Build skin reflectance (0-1). scale_vis adjusts 300-700nm (darker skin)."""
    wl = _SKIN_LIGHT_KP[:, 0]
    r  = _SKIN_LIGHT_KP[:, 1] / 100.0  # -> fraction

    # Extrapolate below 400nm by holding first value
    wl = np.concatenate([[300], wl])
    r  = np.concatenate([[r[0] * 0.7], r])  # UV drops from visible level

    # Apply visible scale factor
    blend = np.clip((wl - 650.0) / 100.0, 0.0, 1.0)  # 0 at 650nm, 1 at 750nm
    r_scaled = r * (scale_vis + (1.0 - scale_vis) * blend)

    return make_spectrum(wl, r_scaled, "skin")


# ──────────────────────────────────────────────────────────────────────────────
# Clear glass (Fresnel, n=1.52 soda-lime)
# ──────────────────────────────────────────────────────────────────────────────

def glass_spectrum() -> np.ndarray:
    """Normal-incidence reflectance of soda-lime window glass.

    Refractive index from Rubin 1985 (soda-lime glass), no absorption in
    visible; slight absorption increase in SWIR.  R = ((n-1)/(n+1))².
    Reference: M. Rubin, Solar Energy Materials 12 (1985) 275-288.
    """
    # n varies ~1.525 at 380nm to ~1.507 at 2500nm (small Cauchy dispersion)
    n = 1.525 - 0.008 * ((WL_GRID - 380.0) / (2500.0 - 380.0))
    R = ((n - 1.0) / (n + 1.0))**2  # two surfaces sum is ~8% but we show single
    return quality_control(R.astype(np.float32), "glass")


# ──────────────────────────────────────────────────────────────────────────────
# Material definitions
# ──────────────────────────────────────────────────────────────────────────────

def _usgs(path: str) -> tuple[np.ndarray, np.ndarray]:
    return read_usgs(f"ASCIIdata_splib07a/{path}")


def _eco(filename: str) -> tuple[np.ndarray, np.ndarray]:
    return read_ecostress(filename)


def build_all_materials() -> list[dict]:
    """Return list of material dicts with keys: name, category, flags, data."""

    def mat(name: str, category: str, wl: np.ndarray, r: np.ndarray,
            source: str, notes: str = "") -> dict:
        return dict(
            name=name, category=category, flags=0,
            data=make_spectrum(wl, r, name),
            source=source, notes=notes,
        )

    def mat_raw(name: str, category: str, data: np.ndarray,
                source: str, notes: str = "") -> dict:
        return dict(name=name, category=category, flags=0,
                    data=quality_control(data, name),
                    source=source, notes=notes)

    mats = []
    print("Building vegetation spectra...")

    # ── Vegetation ──────────────────────────────────────────────────────────
    wl, r = _usgs("ChapterV_Vegetation/splib07a_Aspen_Aspen-1_green-top_ASDFRa_AREF.txt")
    mats.append(mat("deciduous_leaf_green", "vegetation", wl, r,
        "USGS splib07a: Aspen green-top leaf (ASD 350-2500nm)"))

    wl, r = _usgs("ChapterV_Vegetation/splib07a_Aspen_Aspen-4_yellow-top_ASDFRa_AREF.txt")
    mats.append(mat("deciduous_leaf_autumn", "vegetation", wl, r,
        "USGS splib07a: Aspen yellow/autumn top leaf (ASD)"))

    wl, r = _usgs("ChapterV_Vegetation/splib07a_J.roemer._DWV1-0511a_gr.a_ASDFRa_AREF.txt")
    mats.append(mat("grass_green", "vegetation", wl, r,
        "USGS splib07a: Juncus roemerianus green rush (ASD)",
        notes="Green rush/grass measured in Delacroix Marsh, LA"))

    wl, r = _usgs("ChapterV_Vegetation/splib07a_Grass_Golden_Dry_GDS480_ASDFRa_AREF.txt")
    mats.append(mat("grass_dry", "vegetation", wl, r,
        "USGS splib07a: Golden dry grass GDS480 (ASD)"))

    wl, r = _usgs("ChapterV_Vegetation/splib07a_Lodgepole-Pine_LP-Needles-1_ASDFRa_AREF.txt")
    mats.append(mat("conifer_needle", "vegetation", wl, r,
        "USGS splib07a: Lodgepole pine needles (ASD)"))

    wl, r = _eco("nonphotosyntheticvegetation.bark.pinus.ponderosa.vswir.vh313.ucsb.asd.spectrum.txt")
    mats.append(mat("tree_bark_dark", "vegetation", wl, r,
        "ECOSTRESS: Pinus ponderosa bark VSWIR ASD (UCSB HyspIRI)"))

    wl, r = _eco("nonphotosyntheticvegetation.bark.calocedrus.decurrens.vswir.vh312.ucsb.asd.spectrum.txt")
    mats.append(mat("tree_bark_light", "vegetation", wl, r,
        "ECOSTRESS: Calocedrus decurrens (incense cedar) bark VSWIR ASD (UCSB)"))

    wl, r = _eco("nonphotosyntheticvegetation.lichen.lichen.species.vswir.vh296.ucsb.asd.spectrum.txt")
    mats.append(mat("lichen_moss", "vegetation", wl, r,
        "ECOSTRESS: Lichen species VSWIR ASD (UCSB HyspIRI)"))

    print("Building earth/ground spectra...")

    # ── Earth / Ground ───────────────────────────────────────────────────────
    wl, r = _usgs("ChapterS_SoilsAndMixtures/splib07a_Stonewall_Playa_Dry_Mud_2001_ASDFRa_AREF.txt")
    mats.append(mat("soil_dark", "earth", wl, r,
        "USGS splib07a: Stonewall Playa dry mud (ASD)"))

    wl, r = _usgs("ChapterS_SoilsAndMixtures/splib07a_Illite_CU00-5B_Hi-Al+Quartz_ASDFRa_AREF.txt")
    mats.append(mat("soil_sandy", "earth", wl, r,
        "USGS splib07a: Illite+Quartz (ASD, bright sandy clay mineral)",
        notes="Proxy for light sandy soil; actual mineral composition typical of sandy soils"))

    wl, r = _usgs("ChapterS_SoilsAndMixtures/splib07a_Sand_GrndIsle1_no_oil_ASDFRa_AREF.txt")
    mats.append(mat("sand_beach", "earth", wl, r,
        "USGS splib07a: Grand Isle beach sand, no oil (ASD)"))

    wl, r = _usgs("ChapterS_SoilsAndMixtures/splib07a_Pyroxene_Basalt_CU01-20A_ASDFRa_AREF.txt")
    mats.append(mat("gravel_basalt", "earth", wl, r,
        "USGS splib07a: Pyroxene basalt CU01-20A (ASD)"))

    wl, r = _usgs("ChapterL_Liquids/splib07a_Melting_snow_mSnw01a_ASDFRa_AREF.txt")
    mats.append(mat("snow", "earth", wl, r,
        "USGS splib07a: Melting snow mSnw01a (ASD)"))

    wl, r = _usgs("ChapterL_Liquids/splib07a_Water+Montmor_SWy-2+0.50g-l_ASDFRa_AREF.txt")
    mats.append(mat("water_clear", "earth", wl, r,
        "USGS splib07a: Water + 0.5 g/L montmorillonite (ASD; essentially clear water)",
        notes="Very dilute clay suspension; spectrally equivalent to clear water in 300-2500nm range"))

    print("Building building material spectra...")

    # ── Building materials ───────────────────────────────────────────────────
    wl, r = _usgs("ChapterA_ArtificialMaterials/splib07a_Concrete_GDS375_Lt_Gry_Road_ASDFRa_AREF.txt")
    mats.append(mat("concrete_grey", "building", wl, r,
        "USGS splib07a: Concrete GDS375 light grey road (ASD)"))

    wl, r = _usgs("ChapterA_ArtificialMaterials/splib07a_Asphalt_GDS376_Blck_Road_old_ASDFRa_AREF.txt")
    mats.append(mat("asphalt_dark", "building", wl, r,
        "USGS splib07a: Asphalt GDS376 black road (old, ASD)"))

    wl, r = _usgs("ChapterA_ArtificialMaterials/splib07a_Brick_GDS349_Paving_Red_ASDFRa_AREF.txt")
    mats.append(mat("brick_red", "building", wl, r,
        "USGS splib07a: Brick GDS349 paving red (ASD)"))

    wl, r = _usgs("ChapterA_ArtificialMaterials/splib07a_Titanium_dioxide_GDS798_TiO2_ASDFRa_AREF.txt")
    mats.append(mat("ceramic_tile_white", "building", wl, r,
        "USGS splib07a: TiO2 pigment GDS798 (ASD) — white ceramic tile proxy",
        notes="TiO2 is the primary pigment in white ceramic tiles and white paint"))

    mats.append(mat_raw("clear_glass", "building",
        glass_spectrum(),
        "Computed: Fresnel R from soda-lime glass n(λ) dispersion (Rubin 1985)",
        notes="n≈1.52 from Rubin 1985 Solar Energy Materials 12:275-288; single-surface reflectance"))

    wl, r = _usgs("ChapterA_ArtificialMaterials/splib07a_Concrete_WTC01-37A_ASDFRa_AREF.txt")
    mats.append(mat("plaster_stucco", "building", wl, r,
        "USGS splib07a: WTC01-37A concrete/plaster (ASD)"))

    wl, r = _usgs("ChapterA_ArtificialMaterials/splib07a_Brick_GDS350_Dk_Red_Building_ASDFRa_AREF.txt")
    mats.append(mat("roof_tile_terracotta", "building", wl, r,
        "USGS splib07a: Brick GDS350 dark red building brick (ASD)"))

    wl, r = _usgs("ChapterS_SoilsAndMixtures/splib07a_Limestone_CU02-11A_ASDFRa_AREF.txt")
    mats.append(mat("limestone_marble", "building", wl, r,
        "USGS splib07a: Limestone CU02-11A (ASD)"))

    print("Building metal spectra...")

    # ── Metals ───────────────────────────────────────────────────────────────
    mats.append(mat_raw("aluminum_polished", "metal",
        rakic_reflectance("Al", WL_GRID),
        "Computed: Rakić et al. 1998 Lorentz-Drude model for Al, Appl. Opt. 37(22):5271"))

    wl, r = _usgs("ChapterA_ArtificialMaterials/splib07a_GalvanizedSheetMetal_GDS334_ASDFRa_AREF.txt")
    mats.append(mat("steel_brushed", "metal", wl, r,
        "USGS splib07a: Galvanized sheet metal GDS334 (ASD)"))

    wl, r = _usgs("ChapterA_ArtificialMaterials/splib07a_Malachite_GDS801_synthetic_ASDFRa_AREF.txt")
    mats.append(mat("copper_oxidized", "metal", wl, r,
        "USGS splib07a: Synthetic malachite GDS801 (ASD) — oxidised copper patina",
        notes="CuCO3·Cu(OH)2; the green patina on oxidised copper surfaces"))

    mats.append(mat_raw("gold_polished", "metal",
        rakic_reflectance("Au", WL_GRID),
        "Computed: Rakić et al. 1998 Lorentz-Drude model for Au, Appl. Opt. 37(22):5271"))

    wl, r = _usgs("ChapterA_ArtificialMaterials/splib07a_Rusted_Tin_Can_GDS378_MV99-6_ASDFRa_AREF.txt")
    mats.append(mat("rust_iron_oxide", "metal", wl, r,
        "USGS splib07a: Rusted tin can GDS378 (ASD)"))

    print("Building fabric spectra...")

    # ── Fabrics & Organics ───────────────────────────────────────────────────
    wl, r = _usgs("ChapterA_ArtificialMaterials/splib07a_Cotton_Fabric_GDS437_White_ASDFRa_AREF.txt")
    mats.append(mat("cotton_white", "fabric", wl, r,
        "USGS splib07a: Cotton fabric GDS437 white (ASD)"))

    wl, r = _usgs("ChapterA_ArtificialMaterials/splib07a_Nylon_Fabric_GDS436_BlkCoatd_ASDFRa_AREF.txt")
    mats.append(mat("cotton_dark", "fabric", wl, r,
        "USGS splib07a: Nylon fabric GDS436 black coated (ASD)",
        notes="Black synthetic fabric; representative of dark/dyed cotton"))

    wl, r = _usgs("ChapterA_ArtificialMaterials/splib07a_Burlap_Fabric_GDS430_Brown_ASDFRa_AREF.txt")
    mats.append(mat("wool_burlap", "fabric", wl, r,
        "USGS splib07a: Burlap fabric GDS430 brown (ASD)",
        notes="Coarse natural fiber fabric; representative of wool/jute"))

    wl, r = _usgs("ChapterA_ArtificialMaterials/splib07a_Wood_Beam_GDS363_Nw_Pine_2X4_ASDFRa_AREF.txt")
    mats.append(mat("wood_pine", "fabric", wl, r,
        "USGS splib07a: Wood beam GDS363 new pine 2x4 (ASD)",
        notes="Fresh pine; representative of light natural wood"))

    wl, r = _usgs("ChapterA_ArtificialMaterials/splib07a_Paper_Cotton_Bond_PAPR1_100%_ASDFRa_AREF.txt")
    mats.append(mat("paper_white", "fabric", wl, r,
        "USGS splib07a: Paper cotton bond PAPR1 100% (ASD)"))

    wl, r = _eco("manmade.roofingmaterial.rubber.solid.all.0833uuurbr.jhu.becknic.spectrum.txt")
    mats.append(mat("rubber_black", "fabric", wl, r,
        "ECOSTRESS/JHU: Black rubber roofing material 0833UUURBR (Beckman-Nicolet 0.3-14μm)"))

    print("Building paint spectra...")

    # ── Paints ───────────────────────────────────────────────────────────────
    wl, r = _usgs("ChapterA_ArtificialMaterials/splib07a_Plastic_PVC_GDS338_White_ASDFRa_AREF.txt")
    mats.append(mat("paint_white", "paint", wl, r,
        "USGS splib07a: White PVC plastic GDS338 (ASD) — white paint proxy"))

    wl, r = _usgs("ChapterA_ArtificialMaterials/splib07a_Nylon_Fabric_GDS431_Red_RpSt_ASDFRa_AREF.txt")
    mats.append(mat("paint_red", "paint", wl, r,
        "USGS splib07a: Red nylon ripstop fabric GDS431 (ASD) — red pigment proxy"))

    wl, r = _usgs("ChapterA_ArtificialMaterials/splib07a_Nylon_Fabric_GDS433_Blu_RpSt_ASDFRa_AREF.txt")
    mats.append(mat("paint_blue", "paint", wl, r,
        "USGS splib07a: Blue nylon ripstop fabric GDS433 (ASD) — blue pigment proxy"))

    wl, r = _usgs("ChapterA_ArtificialMaterials/splib07a_Fiberglass_GDS336_Grn_Roofng_ASDFRa_AREF.txt")
    mats.append(mat("paint_green", "paint", wl, r,
        "USGS splib07a: Green fiberglass roofing GDS336 (ASD) — green paint proxy"))

    print("Building human skin/hair spectra...")

    # ── Human ────────────────────────────────────────────────────────────────
    mats.append(mat_raw("skin_light", "human",
        _skin_spectrum(scale_vis=1.0),
        "Digitised from Bashkatov et al. 2005, J. Phys. D 38:2543, Fig. 3",
        notes="Fair skin in-vivo forearm; 400-2000nm measured, extrapolated outside"))

    mats.append(mat_raw("skin_dark", "human",
        _skin_spectrum(scale_vis=0.45),
        "Bashkatov et al. 2005 with increased melanin absorption (visible scaled x0.45)",
        notes="Dark skin approximation: higher melanin reduces visible reflectance by ~55%"))

    # Dark hair: keratin with melanin granules -> low, nearly flat reflectance ~3-8%
    # Reference: Bashkatov et al. 2002, Proc. SPIE 4623 (dark hair optical constants)
    hair_r = np.full(N_LAMBDA, 0.05, dtype=np.float32)
    # Slight rise with wavelength (reduced scattering in NIR)
    hair_r += 0.03 * (WL_GRID - LAMBDA_MIN) / (LAMBDA_MAX - LAMBDA_MIN)
    mats.append(mat_raw("hair_dark", "human",
        hair_r,
        "Bashkatov et al. 2002, Proc. SPIE 4623: dark hair diffuse reflectance ~3-8%",
        notes="Dark brown/black hair; melanin gives low, slowly rising spectral reflectance"))

    return mats


# ──────────────────────────────────────────────────────────────────────────────
# Light-source SPDs (pkg38 amendment)
# ──────────────────────────────────────────────────────────────────────────────
# References:
#   CIE 15:2018 F-series fluorescent illuminants (via colour-science BSD-3-Clause)
#   CIE 15:2018 LED-B series phosphor LEDs (via colour-science BSD-3-Clause)
#   NIST Atomic Spectra Database (public domain, US Gov)

def _build_light_sources() -> list[dict]:
    """Build the seven light-source SPD profiles (pkg38 amendment).

    Returns list of material dicts with keys: name, category, flags, data, source, notes.
    All SPDs normalised to peak = 1.0 (relative emission), 5 nm grid, 300-2500 nm.
    """
    import colour  # BSD-3-Clause licensed

    def mat_ls(name: str, data: np.ndarray, source: str, notes: str = "") -> dict:
        """Helper to create a light_source category material."""
        # Quality control: handle NaN/Inf, ensure non-negative
        data_qc = np.array(data, dtype=np.float32)
        data_qc = np.where(np.isfinite(data_qc), data_qc, 0.0)
        data_qc = np.maximum(data_qc, 0.0)  # Ensure non-negative

        # Normalise to peak = 1.0 BEFORE clipping (preserve relative intensities)
        peak = data_qc.max()
        if peak > 0:
            data_qc = data_qc / peak

        # Final safety: clip to [0,1] (should be no-op after normalization)
        data_qc = np.clip(data_qc, 0.0, 1.0)

        return dict(
            name=name, category="light_source", flags=0,
            data=data_qc,
            source=source, notes=notes,
        )

    def _resample_cie(illuminant_key: str) -> np.ndarray:
        """Extract CIE illuminant from colour-science, resample to pkg38 grid."""
        spd = colour.SDS_ILLUMINANTS[illuminant_key]
        wl_src = np.array(spd.wavelengths, dtype=np.float64)
        val_src = np.array(spd.values, dtype=np.float64)

        # Sort by wavelength
        order = np.argsort(wl_src)
        wl_src = wl_src[order]
        val_src = val_src[order]

        # Resample: linear interpolation within range, zero outside
        r_grid = np.interp(WL_GRID, wl_src, val_src, left=0.0, right=0.0)

        return r_grid.astype(np.float32)

    def _atomic_lines(lines: list[tuple[float, float]]) -> np.ndarray:
        """Build SPD from discrete atomic lines (wavelength_nm, relative_intensity).

        Each line is broadened to an energy-normalised Gaussian so a sub-bin-width
        line is representable on the 5 nm grid and catchable by the multiwavelength
        sampler's hero/stratified wavelengths (a single-bin deposit aliases the Na
        D-doublet to one ~590 nm spike that the {380,480,580,680} hero wavelengths
        all miss — pkg214).

        Line shape (Gaussian / Doppler limit of the Voigt profile):
          Armstrong 1967, "Spectrum line profiles: The Voigt function",
          JQSRT 7(1) 61-88, DOI:10.1016/0022-4073(67)90057-X. Reference impl:
          scipy.special.voigt_profile(x, σ, γ=0) = exp(-x²/(2σ²))/(σ√(2π)),
          BSD-3-Clause. See .astroray_plan/docs/atomic-line-broadening-research.md.

        FWHM = 15 nm (3 × the 5 nm grid step; σ ≈ 6.37 nm) is DELIBERATELY wider
        than the ~0.1 nm physical linewidth: a sub-bin feature is unrepresentable
        on this grid, so we match the line to the renderer's spectral sampling
        resolution rather than claim a physics linewidth. Each line's relative
        intensity is preserved as the AREA under its Gaussian (D2:D1 = 2:1 and
        total energy conserved); the Na D-doublet (0.6 nm apart ≪ σ) merges into
        one unresolved ~589 nm amber feature. Normalisation done in mat_ls.
        """
        fwhm_nm = 15.0
        sigma = fwhm_nm / (2.0 * np.sqrt(2.0 * np.log(2.0)))
        r = np.zeros(N_LAMBDA, dtype=np.float32)
        for wl_nm, intensity in lines:
            # Energy-normalised Gaussian (unit integral): the area under each
            # line's profile equals its relative intensity, so Σ_j r_j·Δλ ≈ I.
            r += (intensity / (sigma * np.sqrt(2.0 * np.pi))) * np.exp(
                -0.5 * ((WL_GRID - wl_nm) / sigma) ** 2
            )

        return r

    lamps = []
    print("Building light-source SPDs...")

    # ── CIE F2 (cool white fluorescent) ──────────────────────────────────────
    lamps.append(mat_ls(
        "cie_f2",
        _resample_cie("FL2"),
        "CIE 15:2018 F2 fluorescent illuminant (via colour-science v0.4.7, BSD-3-Clause)",
        notes="Cool white fluorescent, CCT ~4230 K, halophosphate phosphor, 380-780nm"
    ))

    # ── CIE F3 (white fluorescent) ───────────────────────────────────────────
    lamps.append(mat_ls(
        "cie_f3",
        _resample_cie("FL3"),
        "CIE 15:2018 F3 fluorescent illuminant (via colour-science v0.4.7, BSD-3-Clause)",
        notes="White fluorescent, CCT ~3450 K, halophosphate phosphor, 380-780nm"
    ))

    # ── LED 3000K (warm white) ───────────────────────────────────────────────
    lamps.append(mat_ls(
        "led_3000k",
        _resample_cie("LED-B3"),
        "CIE 15:2018 LED-B3 (via colour-science v0.4.7, BSD-3-Clause)",
        notes="Warm white LED ~3000K, blue pump + YAG:Ce phosphor, 380-780nm"
    ))

    # ── LED 5000K (neutral white) ────────────────────────────────────────────
    lamps.append(mat_ls(
        "led_5000k",
        _resample_cie("LED-B4"),
        "CIE 15:2018 LED-B4 (via colour-science v0.4.7, BSD-3-Clause)",
        notes="Neutral white LED ~5000K, blue pump + YAG:Ce phosphor, 380-780nm"
    ))

    # ── LED 6500K (cool daylight) ────────────────────────────────────────────
    lamps.append(mat_ls(
        "led_6500k",
        _resample_cie("LED-B5"),
        "CIE 15:2018 LED-B5 (via colour-science v0.4.7, BSD-3-Clause)",
        notes="Cool daylight LED ~6598K, blue pump + YAG:Ce phosphor, 380-780nm"
    ))

    # ── Sodium vapor (D-line doublet) ────────────────────────────────────────
    # NIST ASD Na I D-lines: D2 at 588.995 nm (intensity 2), D1 at 589.592 nm (intensity 1)
    # Ratio D2:D1 ≈ 2:1 from statistical weights
    lamps.append(mat_ls(
        "sodium_vapor",
        _atomic_lines([(588.995, 2.0), (589.592, 1.0)]),
        "NIST Atomic Spectra Database: Na I D-lines (public domain, US Gov)",
        notes="Low-pressure sodium: D2 (588.995 nm, intensity 2), D1 (589.592 nm, intensity 1)"
    ))

    # ── Mercury vapor (multi-line + continuum) ───────────────────────────────
    # NIST ASD Hg I persistent lines: 404.66 nm (400), 435.83 nm (1000), 546.07 nm (500)
    # High-pressure mercury includes phosphor continuum: add flat 5% baseline in 400-700nm
    hg_lines = _atomic_lines([(404.66, 400.0), (435.83, 1000.0), (546.07, 500.0)])

    # Add phosphor continuum: flat 5% of the 435.83 nm line peak (~50 units) in 400-700 nm
    # This is 5% of the dominant line's intensity before normalization
    for i, wl in enumerate(WL_GRID):
        if 400 <= wl <= 700:
            hg_lines[i] += 50.0  # 5% of 1000 (the 435.83 nm line intensity)

    # Normalization done in mat_ls
    lamps.append(mat_ls(
        "mercury_vapor",
        hg_lines,
        "NIST Atomic Spectra Database: Hg I persistent lines (public domain, US Gov)",
        notes="High-pressure mercury: 404.66nm (400), 435.83nm (1000), 546.07nm (500) + 5% phosphor continuum 400-700nm"
    ))

    return lamps


# ──────────────────────────────────────────────────────────────────────���───────
# ASPR binary format writer
# ──────────────────────────────────────────────────────────────────────────────
# Header  : 128 bytes
#   "ASPR" magic (4 bytes) + version uint32 + n_materials uint32 +
#   n_wavelengths uint32 + lambda_min float32 + lambda_max float32 +
#   lambda_step float32 + 100 bytes padding
# Directory: n_materials x 80 bytes
#   name[64] + category_id uint16 + flags uint16 + data_offset uint32
# Data     : n_materials x n_wavelengths x float32

def write_aspr(materials: list[dict], path: str) -> None:
    n_mat = len(materials)
    n_wl  = N_LAMBDA
    data_section_start = 128 + n_mat * 80

    with open(path, "wb") as fh:
        # Header
        hdr = struct.pack("<4sIIIfff",
            b"ASPR", 1, n_mat, n_wl,
            LAMBDA_MIN, LAMBDA_MAX, LAMBDA_STEP)
        hdr += b"\x00" * (128 - len(hdr))
        fh.write(hdr)

        # Directory
        for i, m in enumerate(materials):
            name_bytes = m["name"].encode("utf-8")[:63].ljust(64, b"\x00")
            cat_id  = CAT.get(m["category"], 7)
            offset  = data_section_start + i * n_wl * 4
            entry   = name_bytes + struct.pack("<HHIQ", cat_id, m["flags"], offset, 0)
            assert len(entry) == 80, len(entry)
            fh.write(entry)

        # Data
        for m in materials:
            data = m["data"].astype(np.float32)
            assert len(data) == n_wl
            fh.write(data.tobytes())

    size = os.path.getsize(path)
    print(f"  Wrote {n_mat} materials, {size} bytes -> {path}")


# ──────────────────────────────────────────────────────────────────────────────
# Metadata JSON and sources.md
# ──────────────────────────────────────────────────────────────────────────────

def write_metadata(materials: list[dict], path: str) -> None:
    meta = {
        "version": 1,
        "n_materials": len(materials),
        "wavelength_grid": {
            "lambda_min_nm": LAMBDA_MIN,
            "lambda_max_nm": LAMBDA_MAX,
            "lambda_step_nm": LAMBDA_STEP,
            "n_points": N_LAMBDA,
        },
        "categories": {v: k for k, v in CAT.items()},
        "materials": [
            {
                "index": i,
                "name": m["name"],
                "category": m["category"],
                "source": m["source"],
                "notes": m.get("notes", ""),
            }
            for i, m in enumerate(materials)
        ],
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    print(f"  Wrote metadata -> {path}")


def write_sources(materials: list[dict], path: str) -> None:
    lines = [
        "# Spectral Profile Sources",
        "",
        "This file documents the provenance of every spectrum in `profiles.bin`.",
        "All sources are public-domain or published open-access measurements.",
        "",
        "## Primary databases",
        "",
        "- **USGS Spectral Library v7** — Kokaly et al. 2017, USGS Data Series 1035.",
        "  DOI: 10.5066/F7RR1WDJ.  US Government work, public domain.",
        "",
        "- **ECOSTRESS Spectral Library v1.0** — Meerdink et al. 2019,",
        "  Remote Sensing of Environment 230:111196.",
        "  NASA/JPL public domain data, speclib.jpl.nasa.gov",
        "",
        "- **Rakić 1998** — A.D. Rakić, A.B. Djurišić, J.M. Elazar, M.L. Majewski,",
        '  "Optical properties of metallic films for vertical-cavity',
        '  optoelectronic devices", Appl. Opt. 37(22), 5271-5283 (1998).',
        "  Lorentz-Drude model parameters used to compute n,k; Fresnel R at normal incidence.",
        "",
        "- **Bashkatov 2005** — A.N. Bashkatov, E.A. Genina, V.I. Kochubey, V.V. Tuchin,",
        '  "Optical properties of human skin, subcutaneous and mucous tissues',
        '  in the wavelength range from 400 to 2000 nm",',
        "  J. Phys. D 38 (2005) 2543-2555.",
        "  Key reflectance values digitised from Figure 3.",
        "",
        "- **Rubin 1985** — M. Rubin,",
        '  "Optical constants and bulk optical properties of soda lime silica glasses',
        '  for windows", Solar Energy Materials 12 (1985) 275-288.',
        "  Used to compute window glass Fresnel reflectance.",
        "",
        "## Light sources (pkg38 amendment)",
        "",
        "- **colour-science library** — BSD-3-Clause licensed Python library",
        "  (https://github.com/colour-science/colour, v0.4.7).",
        "  Provides CIE 15:2018 standard illuminant data (F-series fluorescent,",
        "  LED-B series phosphor LEDs) in a permissively-licensed format.",
        "",
        "- **CIE 15:2018** — *Colorimetry, 4th edition*.",
        "  Tables 10 (F-series fluorescent) and 12.1/12.2 (LED-B series).",
        "  Public domain scientific standard data, routinely reproduced in open-source",
        "  rendering codebases (Mitsuba, PBRT-v4, Cycles, colour-science).",
        "",
        "- **NIST Atomic Spectra Database** — Standard Reference Database #78.",
        "  https://www.nist.gov/pml/atomic-spectra-database",
        "  Public domain (US Government work). Provides authoritative wavelength and",
        "  intensity data for atomic emission lines (Na I, Hg I).",
        "",
        "All light-source SPDs are normalised to peak = 1.0 (relative emission),",
        "resampled to 5 nm resolution, and zero-padded outside the measured range",
        "(300-2500 nm). Consumers (e.g., pkg89 `EmissionSpectrum::MeasuredSPD`) multiply",
        "by a user-supplied radiometric scale (W/m²/sr or lumens).",
        "",
        "## Per-material attribution",
        "",
    ]
    for i, m in enumerate(materials):
        lines.append(f"### {i:02d}. `{m['name']}`  ({m['category']})")
        lines.append(f"**Source:** {m['source']}")
        if m.get("notes"):
            lines.append(f"**Notes:** {m['notes']}")
        lines.append("")

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(f"  Wrote sources -> {path}")


# ──────────────────────────────────────────────────────────────────────────────
# Validation
# ──────────────────────────────────────────────────────────────────────────────

def validate(materials: list[dict]) -> None:
    print("\nValidating database...")
    errors = []

    def find(name: str) -> Optional[dict]:
        for m in materials:
            if m["name"] == name:
                return m
        return None

    for m in materials:
        d = m["data"]
        if len(d) != N_LAMBDA:
            errors.append(f"{m['name']}: length {len(d)} != {N_LAMBDA}")
        if not np.all(np.isfinite(d)):
            errors.append(f"{m['name']}: non-finite values")
        if np.any(d < 0) or np.any(d > 1):
            errors.append(f"{m['name']}: values outside [0,1]: min={d.min():.4f} max={d.max():.4f}")

    # Wood effect: spec requires deciduous leaves/grass only (conifers have smaller ratio)
    for name in ("deciduous_leaf_green", "grass_green"):
        m = find(name)
        if m is not None:
            i550 = int((550 - LAMBDA_MIN) / LAMBDA_STEP)
            i800 = int((800 - LAMBDA_MIN) / LAMBDA_STEP)
            r550 = float(m["data"][i550])
            r800 = float(m["data"][i800])
            ratio = r800 / (r550 + 1e-9)
            if ratio < 3.0:
                errors.append(f"{name}: Wood effect ratio {ratio:.2f} < 3 (R(800)={r800:.3f}, R(550)={r550:.3f})")
            else:
                print(f"  OK {name}: Wood effect ratio = {ratio:.1f}x")

    # Water: R(1000nm) < 0.05
    w = find("water_clear")
    if w is not None:
        i1000 = int((1000 - LAMBDA_MIN) / LAMBDA_STEP)
        r1000 = float(w["data"][i1000])
        if r1000 >= 0.05:
            errors.append(f"water_clear: R(1000nm) = {r1000:.4f} >= 0.05")
        else:
            print(f"  OK water_clear: R(1000nm) = {r1000:.4f}")

    # Polished metals: mean R > 0.8
    for name in ("aluminum_polished", "gold_polished"):
        m = find(name)
        if m is not None:
            mean_r = float(m["data"].mean())
            if mean_r < 0.8:
                errors.append(f"{name}: mean reflectance {mean_r:.3f} < 0.8")
            else:
                print(f"  OK {name}: mean R = {mean_r:.3f}")

    # Category coverage
    cats = set(m["category"] for m in materials)
    required_cats = set(CAT.keys()) - {"other"}
    missing_cats = required_cats - cats
    if missing_cats:
        errors.append(f"Missing categories: {missing_cats}")

    n = len(materials)
    if n < 35:
        errors.append(f"Only {n} materials, need >= 35")
    else:
        print(f"  OK {n} materials (>= 35)")

    # Binary size estimate
    size = 128 + n * 80 + n * N_LAMBDA * 4
    if size > 200 * 1024:
        errors.append(f"Estimated binary size {size} bytes > 200 KB")
    else:
        print(f"  OK Estimated binary size: {size//1024} KB")

    if errors:
        print("\nVALIDATION ERRORS:")
        for e in errors:
            print(f"  FAIL {e}")
        raise RuntimeError(f"{len(errors)} validation error(s)")
    else:
        print("\n  All validation checks passed.")


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)

    print("Building spectral profiles database...")
    print(f"  Grid: {LAMBDA_MIN}-{LAMBDA_MAX} nm, step {LAMBDA_STEP} nm, {N_LAMBDA} points")

    materials = build_all_materials()
    light_sources = _build_light_sources()
    materials.extend(light_sources)

    validate(materials)

    print("\nWriting output files...")
    write_aspr(materials,     os.path.join(OUT_DIR, "profiles.bin"))
    write_metadata(materials, os.path.join(OUT_DIR, "profiles_metadata.json"))
    write_sources(materials,  os.path.join(OUT_DIR, "sources.md"))

    print(f"\nDone. {len(materials)} materials written.")


if __name__ == "__main__":
    main()
