/* SPDX-FileCopyrightText: 2026 Astroray Authors
 *
 * SPDX-License-Identifier: Apache-2.0 */

/** \file
 * Clean-room math support for the vendored Blender sky translation units
 * (sky_single_scattering.cpp, Apache-2.0; sky_multiple_scattering.cpp, MIT).
 *
 * Blender's own intern/sky/source/sky_math.h is GPL-2.0-or-later, so it was
 * NOT copied. This header is an independent reimplementation of the small
 * float2/float3/float4 vector helpers those two source files need: trivial
 * component-wise arithmetic, dot/length, clamp/saturate/mix, a textbook
 * ray-sphere intersection, and a serial parallel_for stub. Only the public
 * symbol names (which are an interface, not an expression of authorship) match
 * upstream so the vendored .cpp compile unmodified. See
 * external/blender_sky/README.md for the licence record.
 */

#ifndef ASTRORAY_BLENDER_SKY_MATH_H
#define ASTRORAY_BLENDER_SKY_MATH_H

#include <algorithm>
#include <cmath>
#include <cstddef>

#ifndef M_PI_F
#  define M_PI_F 3.14159265358979323846f
#endif
#ifndef M_PI_2_F
#  define M_PI_2_F 1.57079632679489661923f
#endif
#ifndef M_2PI_F
#  define M_2PI_F 6.28318530717958647692f
#endif
#ifndef M_1_PI_F
#  define M_1_PI_F 0.31830988618379067154f
#endif
#ifndef M_1_4PI_F
#  define M_1_4PI_F 0.07957747154594766788f
#endif

/* --- float2 ------------------------------------------------------------- */
struct float2 {
  float x = 0.0f;
  float y = 0.0f;
  float2() = default;
  float2(float x_, float y_) : x(x_), y(y_) {}
};

inline float2 make_float2(float x, float y)
{
  return float2(x, y);
}

/* --- float3 ------------------------------------------------------------- */
struct float3 {
  float x = 0.0f;
  float y = 0.0f;
  float z = 0.0f;
  float3() = default;
  float3(float x_, float y_, float z_) : x(x_), y(y_), z(z_) {}

  float length_squared() const { return x * x + y * y + z * z; }
  float length() const { return std::sqrt(length_squared()); }

  void operator+=(const float3 &o)
  {
    x += o.x;
    y += o.y;
    z += o.z;
  }
};

inline float3 make_float3(float x, float y, float z)
{
  return float3(x, y, z);
}
inline float3 operator+(const float3 &a, const float3 &b)
{
  return float3(a.x + b.x, a.y + b.y, a.z + b.z);
}
inline float3 operator-(const float3 &a, const float3 &b)
{
  return float3(a.x - b.x, a.y - b.y, a.z - b.z);
}
inline float3 operator-(const float3 &a)
{
  return float3(-a.x, -a.y, -a.z);
}
inline float3 operator*(const float3 &a, float s)
{
  return float3(a.x * s, a.y * s, a.z * s);
}
inline float3 operator*(float s, const float3 &a)
{
  return a * s;
}
inline float3 operator*(const float3 &a, const float3 &b)
{
  return float3(a.x * b.x, a.y * b.y, a.z * b.z);
}
inline float3 operator/(const float3 &a, float s)
{
  return float3(a.x / s, a.y / s, a.z / s);
}
inline float dot(const float3 &a, const float3 &b)
{
  return a.x * b.x + a.y * b.y + a.z * b.z;
}
inline float len(const float3 &a)
{
  return a.length();
}
inline float len_squared(const float3 &a)
{
  return a.length_squared();
}
inline float distance(const float3 &a, const float3 &b)
{
  return (a - b).length();
}
inline float reduce_add(const float3 &a)
{
  return a.x + a.y + a.z;
}

/* --- float4 ------------------------------------------------------------- */
struct float4 {
  float x = 0.0f;
  float y = 0.0f;
  float z = 0.0f;
  float w = 0.0f;
  float4() = default;
  float4(float x_, float y_, float z_, float w_) : x(x_), y(y_), z(z_), w(w_) {}

  float &operator[](int i) { return (&x)[i]; }
  float operator[](int i) const { return (&x)[i]; }

  void operator+=(const float4 &o)
  {
    x += o.x;
    y += o.y;
    z += o.z;
    w += o.w;
  }
  void operator*=(const float4 &o)
  {
    x *= o.x;
    y *= o.y;
    z *= o.z;
    w *= o.w;
  }
};

inline float4 make_float4(float x, float y, float z, float w)
{
  return float4(x, y, z, w);
}
inline float4 operator+(const float4 &a, const float4 &b)
{
  return float4(a.x + b.x, a.y + b.y, a.z + b.z, a.w + b.w);
}
inline float4 operator-(const float4 &a, const float4 &b)
{
  return float4(a.x - b.x, a.y - b.y, a.z - b.z, a.w - b.w);
}
inline float4 operator-(const float4 &a)
{
  return float4(-a.x, -a.y, -a.z, -a.w);
}
inline float4 operator*(const float4 &a, float s)
{
  return float4(a.x * s, a.y * s, a.z * s, a.w * s);
}
inline float4 operator*(float s, const float4 &a)
{
  return a * s;
}
inline float4 operator*(const float4 &a, const float4 &b)
{
  return float4(a.x * b.x, a.y * b.y, a.z * b.z, a.w * b.w);
}
inline float4 operator/(const float4 &a, float s)
{
  return float4(a.x / s, a.y / s, a.z / s, a.w / s);
}
inline float4 operator/(const float4 &a, const float4 &b)
{
  return float4(a.x / b.x, a.y / b.y, a.z / b.z, a.w / b.w);
}
inline float4 exp(const float4 &a)
{
  return float4(std::exp(a.x), std::exp(a.y), std::exp(a.z), std::exp(a.w));
}
inline float4 max(const float4 &a, float b)
{
  return float4(std::fmax(a.x, b), std::fmax(a.y, b), std::fmax(a.z, b), std::fmax(a.w, b));
}

/* --- scalar / mixed helpers --------------------------------------------- */
inline float sqr(float a)
{
  return a * a;
}
inline float safe_sqrtf(float a)
{
  return std::sqrt(std::fmax(a, 0.0f));
}
inline float clamp(float x, float lo, float hi)
{
  return x < lo ? lo : (x > hi ? hi : x);
}
inline float saturate(float x)
{
  return clamp(x, 0.0f, 1.0f);
}
template<typename T> inline T mix(const T &a, const T &b, float t)
{
  return a + (b - a) * t;
}

/* Z-up sun direction from the cosine of its zenith angle. */
inline float3 sun_direction(float sun_cos_theta)
{
  return float3(-std::sqrt(std::fmax(1.0f - sun_cos_theta * sun_cos_theta, 0.0f)),
                0.0f,
                sun_cos_theta);
}

/* Textbook ray-sphere intersection for a sphere centred at the origin with a
 * unit-length direction; returns the nearest non-negative hit distance or -1.
 * (Standard analytic geometric solution, e.g. PBRT/Shirley; no novel method.)
 */
inline float ray_sphere_intersection(const float3 &origin, const float3 &dir, float radius)
{
  const float b = dot(origin, dir);
  const float c = dot(origin, origin) - radius * radius;
  if (c > 0.0f && b > 0.0f) {
    return -1.0f;
  }
  const float disc = b * b - c;
  if (disc < 0.0f) {
    return -1.0f;
  }
  const float sqrt_disc = std::sqrt(disc);
  /* Entry root if the origin is outside, exit root if inside (disc >= b*b). */
  return (disc >= b * b) ? (-b + sqrt_disc) : (-b - sqrt_disc);
}

/* Serial stand-in for Blender's TBB/OpenMP parallel_for. The sky bake is a
 * one-shot precompute at modest resolution, so a plain loop is sufficient and
 * avoids pulling an OpenMP/TBB dependency into the vendored TUs. */
template<typename Function>
inline void SKY_parallel_for(size_t begin, size_t end, size_t grainsize, const Function &function)
{
  if (grainsize == 0) {
    grainsize = 1;
  }
  for (size_t i = begin; i < end; i += grainsize) {
    function(i, std::min(i + grainsize, end));
  }
}

#endif /* ASTRORAY_BLENDER_SKY_MATH_H */
