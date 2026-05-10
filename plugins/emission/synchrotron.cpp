#include "astroray/synchrotron.h"
#include "astroray/register.h"

// pkg42 synchrotron jet plugin.
// Formulae: Pandya, Zhang, Chandra & Gammie 2016, ApJ 822, 34.
// Reference implementation fence: ipole's vendored symphony files are BSD-3
// and mirrorable with attribution; RAPTOR and standalone symphony are GPLv3
// cross-validation only, with no code borrowed.

using SynchrotronJetPlugin = astroray::synchrotron::SynchrotronJet;

ASTRORAY_REGISTER_EMISSION("synchrotron_jet", SynchrotronJetPlugin)
