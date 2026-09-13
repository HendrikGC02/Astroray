/* SPDX-FileCopyrightText: 2026 Astroray Authors
 *
 * SPDX-License-Identifier: Apache-2.0 */

/** \file
 * Clean-room declarations for the vendored Blender sky precompute entry points.
 *
 * Blender's own intern/sky/include/sky_nishita.h is GPL-2.0-or-later, so it was
 * NOT copied. These are plain C-style function declarations (an interface, not
 * a creative expression) matching the names/signatures the vendored
 * sky_single_scattering.cpp (Apache-2.0) and sky_multiple_scattering.cpp (MIT)
 * define, so those translation units compile against this header unmodified.
 * The SKY_single_scattering_spectrum() declaration is an Astroray addition (not
 * upstream) exposing the 21-wavelength intermediate for a future spectral path.
 */

#pragma once

/* Classic Nishita single-scattering model (21 wavelengths, 380-780 nm). Fills
 * `pixels` (width*height*stride floats, XYZ in the first three lanes) in the
 * Cycles sky-texture layout. */
void SKY_single_scattering_precompute_texture(float *pixels,
                                              int stride,
                                              int width,
                                              int height,
                                              float sun_elevation,
                                              float altitude,
                                              float air_density,
                                              float aerosol_density,
                                              float ozone_density);

void SKY_single_scattering_precompute_sun(float sun_elevation,
                                          float angular_diameter,
                                          float altitude,
                                          float air_density,
                                          float aerosol_density,
                                          float r_pixel_bottom[3],
                                          float r_pixel_top[3]);

/* Astroray addition (not upstream): single-scattering spectrum for a Z-up view
 * direction, 21 samples 380-780 nm. */
void SKY_single_scattering_spectrum(const float ray_dir[3],
                                    float sun_elevation,
                                    float altitude,
                                    float air_density,
                                    float aerosol_density,
                                    float ozone_density,
                                    float r_spectrum[21]);

/* Astroray addition (not upstream): single-scattering sky radiance as CIE XYZ
 * for a Z-up view direction (sun at azimuth 0). */
void SKY_single_scattering_eval_xyz(const float ray_dir[3],
                                    float sun_elevation,
                                    float altitude,
                                    float air_density,
                                    float aerosol_density,
                                    float ozone_density,
                                    float r_xyz[3]);

/* Astroray addition (not upstream): multiple-scattering per-direction eval via
 * a context that precomputes the transmittance LUT once (sun at azimuth 0). */
void *SKY_multiple_scattering_create(float sun_elevation,
                                     float altitude,
                                     float air_density,
                                     float aerosol_density,
                                     float ozone_density);
void SKY_multiple_scattering_eval_xyz(void *context, const float ray_dir[3], float r_xyz[3]);
void SKY_multiple_scattering_destroy(void *context);

/* Spectral multiple-scattering model (4 wavelengths, Frostbite/Hillaire fit;
 * Blender 5.x default). Same XYZ layout as above. */
void SKY_multiple_scattering_precompute_texture(float *pixels,
                                                int stride,
                                                int width,
                                                int height,
                                                float sun_elevation,
                                                float altitude,
                                                float air_density,
                                                float aerosol_density,
                                                float ozone_density);

void SKY_multiple_scattering_precompute_sun(float sun_elevation,
                                            float angular_diameter,
                                            float altitude,
                                            float air_density,
                                            float aerosol_density,
                                            float ozone_density,
                                            float r_pixel_bottom[3],
                                            float r_pixel_top[3]);

float SKY_earth_intersection_angle(float altitude);
