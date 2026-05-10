# Kerr validation references

These pkg41 fixtures are deterministic, license-clean reference data for
Kerr metric validation. The orbit scalars and shadow contours are generated
from Bardeen, Press & Teukolsky 1972 (ApJ 178, 347) and Chandrasekhar
1983, ch. 7. GYOTO, RAPTOR, and ipole are cited in the package spec and
research notes as independent cross-validation references only; no GPL or
CeCILL code or scene files are mirrored here.

Regenerate with `python scripts/generate_gyoto_references.py` from the
repository root. The historical `gyoto_*` filenames are kept because the
pkg41 spec names the reference image slots that way.
