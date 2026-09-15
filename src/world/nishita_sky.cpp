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
  // Orientation. Astroray's env lookup maps a WORLD direction D to the equirect
  // via phi_env = atan2(-D.y, D.x) (include/raytracer.h EnvironmentMap::lookup,
  // after the Blender Z-up -> env-Y-polar swap). The validated Preetham bake
  // (sky_bake.py) fills pixel (r,c) with world dir D = (sin t cos p,
  // -sin t sin p, cos t), p = ((c+0.5)/W - 0.5)*2pi, which places a sun at
  // WORLD azimuth A at column-phi -A. We MUST match that so the baked sky glow
  // coincides with the dedicated distant sun (world azimuth +A) and its
  // shadows. So for each pixel we take the same world dir D and evaluate the
  // model at D rotated about +Z by beta = (model's azimuth-0 sun) - A, i.e. the
  // model's sun lands at world azimuth A. The two models put their azimuth-0
  // sun at OPPOSITE X: single-scattering geographical_to_direction(elev,0)->+X
  // (model_sun_az 0); multiple-scattering sun_direction(sin elev)->-X
  // (model_sun_az pi). Validated by rendering (sky glow coincides with the sun
  // disc); see test_batch_j_nishita_sky.py::test_sky_glow_matches_distant_sun.
  // #814: match Cycles' Nishita sun world azimuth = 90deg - sun_rotation
  // (measured vs Blender 5.2, 814-sun-direction-convention-research.md). The
  // glow's world azimuth = model_sun_az - beta, so to land it at (pi/2 -
  // sun_rotation): SS (model_sun_az 0) -> beta = sun_rotation - pi/2; MS
  // (model_sun_az pi) -> beta = sun_rotation + pi/2. This keeps the baked sky
  // glow coincident with the dedicated distant sun (same world azimuth) while
  // matching Cycles' shadow direction.
  const float half_pi = 0.5f * pi;
  const float beta = (mode == Mode::MultipleScattering) ? (sun_rotation + half_pi)
                                                        : (sun_rotation - half_pi);
  const float cos_b = std::cos(beta);
  const float sin_b = std::sin(beta);

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
      // mdir = Rz(beta) * D  (rotate world dir azimuth by beta about +Z).
      float mdir[3];
      mdir[0] = dx * cos_b - dy * sin_b;
      mdir[1] = dx * sin_b + dy * cos_b;
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
