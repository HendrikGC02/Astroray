// SPDX-License-Identifier: Apache-2.0
// Batch J (#799 Phase 2): engine-side spectral Nishita sky.
//
// Thin host-C++ wrapper over the vendored Blender sky models
// (external/blender_sky/: sky_single_scattering.cpp Apache-2.0,
// sky_multiple_scattering.cpp MIT). Produces an equirectangular environment
// texture in Astroray's env-map convention (row r: polar angle from +Z;
// column c: azimuth), and the solar-disc radiance pair used to drive the
// dedicated distant sun. No GPU kernel change; both backends consume the
// result through the existing HDRI path.
#pragma once

namespace astroray {
namespace nishita {

enum class Mode {
  SingleScattering = 0,  // classic Nishita, 21 wavelengths 380-780 nm (Apache-2.0)
  MultipleScattering = 1 // Hillaire/García-Liñán 4-wavelength fit (MIT), Blender 5.x default
};

// Fill `out_rgb` (width*height*3, row-major, linear Rec.709) with the sky
// radiance in Astroray's equirect convention. The model's sun sits at azimuth
// `sun_rotation`. Angles in radians; altitude in metres; densities are the
// Blender Sky-node multipliers. No extra exposure factor is applied (the table
// is already in Cycles' radiometric units).
void sky_equirect(Mode mode,
                  int width,
                  int height,
                  float sun_elevation,
                  float sun_rotation,
                  float altitude,
                  float air_density,
                  float aerosol_density,
                  float ozone_density,
                  float *out_rgb);

// Solar-disc radiance at the bottom and top of the disc (linear Rec.709),
// from the vendored precompute_sun. Multiply by the Sky node's sun_intensity
// and (optionally) limb darkening externally.
void sun_disc(Mode mode,
              float sun_elevation,
              float angular_diameter,
              float altitude,
              float air_density,
              float aerosol_density,
              float ozone_density,
              float r_pixel_bottom[3],
              float r_pixel_top[3]);

}  // namespace nishita
}  // namespace astroray
