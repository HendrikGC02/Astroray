// SPDX-License-Identifier: Apache-2.0
// Batch J (#799 Phase 2): engine-side spectral Nishita sky wrapper.
//
// Evaluates the vendored Blender sky models (external/blender_sky/) per output
// pixel directly (exact orientation, no layout resample), converts CIE XYZ to
// linear Rec.709, and lays the result out in Astroray's equirect convention.
//
// Equirect convention (matches blender_addon/sky_bake.py, validated by the
// pkg256 azimuth A/B and EnvironmentMap::lookup in include/raytracer.h):
//   row r   -> polar angle theta = (r+0.5)/H * pi, from +Z (zenith) to -Z
//   col c   -> azimuth  phi      = ((c+0.5)/W - 0.5) * 2*pi
//   Blender Z-up dir = (sin t cos p, -sin t sin p, cos t)
// The Sky model is evaluated with its sun fixed at azimuth 0, so the view
// direction is rotated by -sun_rotation about +Z to place the sun at azimuth
// `sun_rotation`.
//
// XYZ->RGB: standard CIE XYZ (D65) to linear sRGB / Rec.709 matrix, negatives
// clamped to 0 (Cycles svm/sky.h xyz_to_rgb_clamped, Apache-2.0).

#include "astroray/nishita_sky.h"

#include <cmath>

#include "sky_nishita.h"  // vendored declarations (external/blender_sky/)

namespace astroray {
namespace nishita {

namespace {

inline void xyz_to_linear_rgb(const float xyz[3], float rgb[3])
{
  const float X = xyz[0], Y = xyz[1], Z = xyz[2];
  float r = 3.2404542f * X - 1.5371385f * Y - 0.4985314f * Z;
  float g = -0.9692660f * X + 1.8760108f * Y + 0.0415560f * Z;
  float b = 0.0556434f * X - 0.2040259f * Y + 1.0572252f * Z;
  rgb[0] = r > 0.0f ? r : 0.0f;
  rgb[1] = g > 0.0f ? g : 0.0f;
  rgb[2] = b > 0.0f ? b : 0.0f;
}

}  // namespace

void sky_equirect(Mode mode,
                  int width,
                  int height,
                  float sun_elevation,
                  float sun_rotation,
                  float altitude,
                  float air_density,
                  float aerosol_density,
                  float ozone_density,
                  float *out_rgb)
{
  if (width <= 0 || height <= 0 || out_rgb == nullptr) {
    return;
  }
  const float two_pi = 6.28318530717958647692f;
  const float pi = 3.14159265358979323846f;
  const float cos_sr = std::cos(sun_rotation);
  const float sin_sr = std::sin(sun_rotation);

  void *ms_ctx = nullptr;
  if (mode == Mode::MultipleScattering) {
    ms_ctx = SKY_multiple_scattering_create(
        sun_elevation, altitude, air_density, aerosol_density, ozone_density);
  }

  for (int r = 0; r < height; ++r) {
    const float theta = (static_cast<float>(r) + 0.5f) / static_cast<float>(height) * pi;
    const float st = std::sin(theta);
    const float ct = std::cos(theta);
    float *row = out_rgb + static_cast<size_t>(r) * width * 3;
    for (int c = 0; c < width; ++c) {
      const float phi = ((static_cast<float>(c) + 0.5f) / static_cast<float>(width) - 0.5f) * two_pi;
      const float dx = st * std::cos(phi);
      const float dy = -st * std::sin(phi);
      const float dz = ct;
      // Rotate the view direction by -sun_rotation about +Z (sun -> azimuth 0).
      float mdir[3];
      mdir[0] = dx * cos_sr + dy * sin_sr;
      mdir[1] = -dx * sin_sr + dy * cos_sr;
      mdir[2] = dz;

      float xyz[3];
      if (mode == Mode::MultipleScattering) {
        SKY_multiple_scattering_eval_xyz(ms_ctx, mdir, xyz);
      }
      else {
        SKY_single_scattering_eval_xyz(
            mdir, sun_elevation, altitude, air_density, aerosol_density, ozone_density, xyz);
      }
      xyz_to_linear_rgb(xyz, row + static_cast<size_t>(c) * 3);
    }
  }

  if (ms_ctx != nullptr) {
    SKY_multiple_scattering_destroy(ms_ctx);
  }
}

void sun_disc(Mode mode,
              float sun_elevation,
              float angular_diameter,
              float altitude,
              float air_density,
              float aerosol_density,
              float ozone_density,
              float r_pixel_bottom[3],
              float r_pixel_top[3])
{
  float xyz_bottom[3] = {0.0f, 0.0f, 0.0f};
  float xyz_top[3] = {0.0f, 0.0f, 0.0f};
  if (mode == Mode::MultipleScattering) {
    SKY_multiple_scattering_precompute_sun(sun_elevation,
                                           angular_diameter,
                                           altitude,
                                           air_density,
                                           aerosol_density,
                                           ozone_density,
                                           xyz_bottom,
                                           xyz_top);
  }
  else {
    SKY_single_scattering_precompute_sun(
        sun_elevation, angular_diameter, altitude, air_density, aerosol_density, xyz_bottom, xyz_top);
  }
  xyz_to_linear_rgb(xyz_bottom, r_pixel_bottom);
  xyz_to_linear_rgb(xyz_top, r_pixel_top);
}

}  // namespace nishita
}  // namespace astroray
