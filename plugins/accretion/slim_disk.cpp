#include "astroray/slim_disk.h"
#include "astroray/register.h"

// pkg43 slim disk accretion plugin.
// Physics model:
// - Vertical structure: Sadowski 2009 eq. 5 (H ~ c_s / Omega_K, slim regime).
// - Temperature: Page & Thorne 1974 eq. 11n (Novikov-Thorne baseline) with
//   advective correction from Sadowski 2009 §3 (exponential fit per research
//   note accretion-emission-research.md §4.3).
// - Spectral emission: multi-color blackbody (Planck B_nu at local T).
//
// References:
// - Sadowski, A. 2009, "Slim accretion disks around Kerr black holes revisited,"
//   ApJS 183, 171. DOI 10.1088/0067-0049/183/2/171. arXiv:0906.0355.
//   Primary source for slim-disk physics (6 coupled ODEs solved numerically;
//   we use an analytic fitting-function skeleton per research note).
// - Page, D.N., Thorne, K.S. 1974, "Disk-Accretion onto a Black Hole. I,"
//   ApJ 191, 499. Novikov-Thorne T_NT(r) baseline.
// - Abramowicz, M.A., Fragile, P.C. 2013, "Foundations of Black Hole Accretion
//   Disk Theory," Living Reviews in Relativity 16, 1. arXiv:1104.5499. Review.
// - Abramowicz et al. 1988, ApJ 332, 646 — original slim-disk formulation.
//
// License fence:
// - GYOTO (CeCILL, GPL-incompatible) has PolishDoughnut.C (a thick-disk model
//   similar to slim disks). Cross-validation only; no code mirrored.
// - ipole (BSD-3) has GRMHD snapshot loaders but no slim-disk analytic file.
// - RAPTOR (GPLv3) — cross-validation only per pkg40/pkg42 fence.
//
// The formulae are from peer-reviewed papers (math is public-domain); the C++
// expressions are original or derived from the research note.

using SlimDiskPlugin = astroray::slimdisk::SlimDisk;

ASTRORAY_REGISTER_EMISSION("slim_disk", SlimDiskPlugin)
