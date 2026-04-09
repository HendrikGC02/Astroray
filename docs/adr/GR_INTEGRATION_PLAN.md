# Astroray Phase 3: General Relativistic Geodesic Integration

## Goal

Merge the standalone GR black hole renderer into Astroray as a unified rendering mode. Users can place black hole objects in a Blender scene alongside normal geometry, and the renderer handles geodesic ray tracing near the black hole while using standard Euclidean path tracing everywhere else. The spectral rendering pipeline (Novikov-Thorne disk, hero wavelength sampling, CIE XYZ → sRGB) becomes part of the C++ engine.

## What exists now (Python standalone — proven working)

The standalone GR addon (built in our previous sessions) implements:
- `Metric` abstract base class with `SchwarzschildMetric` (Hamiltonian geodesics in Boyer-Lindquist coords)
- Dormand-Prince RK45 adaptive integrator, vectorized with NumPy
- `NovikovThorneDisk` with Page-Thorne flux profile, temperature, redshift factor
- Hero wavelength spectral sampling (4 wavelengths per ray, 200–2000nm range)
- Planck blackbody B(λ,T), CIE 1931 color matching, XYZ→sRGB with auto-exposure
- Blender addon with `GRBlackHoleProperties` on objects, render settings panels
- Capture threshold at r < 2.5M (relaxed from 2.02M to avoid BL coordinate stalling)

**Key validated results:** D-shaped shadow at 75° inclination, Doppler beaming, gravitational lensing of far-side disk, 160×120 in 1.6s CPU.

## Architecture: hybrid propagation via influence spheres

```
Standard path tracing
    │
    ▼ ray misses all geometry
    ├─► environment map lookup (Phase 1)
    │
    ▼ ray enters black hole influence sphere
    ├─► convert to Boyer-Lindquist coords
    ├─► RK45 geodesic integration (double precision)
    │     ├─► disk intersection → spectral emission → convert to RGB
    │     ├─► captured (r < 2.5M) → black pixel
    │     └─► escaped (r > r_influence) → convert back to Euclidean
    │           └─► exit direction samples environment map / continues path tracing
    └─► normal path tracing continues with remapped direction + frequency shift
```

The black hole acts as a **direction remapper with frequency shift**. A ray enters the GR zone, follows a curved geodesic, and exits with a new direction. That new direction either hits the environment map or re-enters the Euclidean BVH. Accretion disk emission is added during the geodesic integration.

## New files

```
include/
  astroray/
    gr_types.h          ← GR-specific types (GeodesicState, DiskCrossing, etc.)
    metric.h            ← Abstract Metric interface + SchwarzschildMetric
    accretion_disk.h    ← NovikovThorneDisk with Page-Thorne flux
    spectral.h          ← Planck, CIE matching functions, XYZ→sRGB
    gr_integrator.h     ← RK45 Dormand-Prince integrator
    black_hole.h        ← BlackHole Hittable object (influence sphere + GR core)
```

## Modified files

```
include/raytracer.h       ← Add BlackHole as a Hittable, modify pathTrace for GR bounces
module/blender_module.cpp ← Add add_black_hole() binding
blender_addon/__init__.py ← Add black hole object creation, GR property panels
```

---

## Task 1: GR types (`include/astroray/gr_types.h`)

Core data structures for the GR subsystem. All use `double` precision for the integrator.

```cpp
#pragma once
#include "raytracer.h"  // for Vec3
#include <cmath>

// 8-component geodesic state: (t, r, θ, φ, p_t, p_r, p_θ, p_φ)
struct GeodesicState {
    double t, r, theta, phi;
    double p_t, p_r, p_theta, p_phi;
};

struct DiskCrossing {
    double r;           // radius of crossing
    double phi;         // azimuthal angle
    double g;           // redshift factor ν_obs/ν_emit
    bool valid;
};

// Constants
constexpr double GR_PI = 3.14159265358979323846;
constexpr double h_PLANCK = 6.62607015e-34;   // J·s
constexpr double c_LIGHT  = 2.99792458e8;     // m/s
constexpr double k_BOLTZ  = 1.380649e-23;     // J/K
constexpr double SIGMA_SB = 5.670374419e-8;   // W/(m²·K⁴)
constexpr double M_SUN_KG = 1.989e30;         // kg
constexpr double G_NEWTON  = 6.674e-11;       // m³/(kg·s²)
```

---

## Task 2: Metric abstraction (`include/astroray/metric.h`)

Port the Python `Metric` → `SchwarzschildMetric`. This is the physics core.

```cpp
#pragma once
#include "gr_types.h"
#include <array>

class Metric {
public:
    double M;  // mass in geometrized units

    virtual ~Metric() = default;

    // Hamiltonian equations of motion: returns d(state)/dλ
    virtual GeodesicState geodesic_rhs(const GeodesicState& s) const = 0;

    // Event horizon radius
    virtual double event_horizon_radius() const = 0;

    // ISCO radius
    virtual double isco_radius() const = 0;

    // Check if ray is captured
    virtual bool is_captured(const GeodesicState& s) const = 0;

    // Keplerian orbital velocity at radius r (for disk model)
    virtual double disk_omega(double r) const = 0;
};

class SchwarzschildMetric : public Metric {
public:
    SchwarzschildMetric(double mass = 1.0) { M = mass; }

    GeodesicState geodesic_rhs(const GeodesicState& s) const override {
        // Hamiltonian formulation in Boyer-Lindquist coordinates
        // H = -p_t²/(2f) + f·p_r²/2 + (p_θ² + p_φ²/sin²θ)/(2r²) = 0
        // where f = 1 - 2M/r

        double r = s.r;
        double theta = s.theta;
        double f = 1.0 - 2.0 * M / r;
        double r2 = r * r;
        double sin_th = std::sin(theta);
        double cos_th = std::cos(theta);
        double sin2_th = sin_th * sin_th;

        // Prevent division by zero at poles
        if (sin2_th < 1e-12) sin2_th = 1e-12;

        GeodesicState dstate;

        // dx^μ/dλ = ∂H/∂p_μ
        dstate.t     = -s.p_t / f;                              // dt/dλ
        dstate.r     = f * s.p_r;                                // dr/dλ
        dstate.theta = s.p_theta / r2;                           // dθ/dλ
        dstate.phi   = s.p_phi / (r2 * sin2_th);                // dφ/dλ

        // dp_μ/dλ = -∂H/∂x^μ
        double df_dr = 2.0 * M / (r * r);
        double L2 = s.p_theta * s.p_theta + s.p_phi * s.p_phi / sin2_th;

        dstate.p_t     = 0.0;  // t is cyclic → E = -p_t is conserved
        dstate.p_r     = -(s.p_t * s.p_t * df_dr / (2.0 * f * f)
                           + df_dr * s.p_r * s.p_r / 2.0
                           - L2 / (r * r2));
        dstate.p_theta = s.p_phi * s.p_phi * cos_th / (r2 * sin2_th * sin_th);
        dstate.p_phi   = 0.0;  // φ is cyclic → L = p_φ is conserved

        return dstate;
    }

    double event_horizon_radius() const override { return 2.0 * M; }
    double isco_radius() const override { return 6.0 * M; }

    bool is_captured(const GeodesicState& s) const override {
        // Relaxed threshold to avoid BL coordinate stalling
        return s.r < 2.5 * M;
    }

    double disk_omega(double r) const override {
        // Keplerian angular velocity: Ω = √(M/r³)
        return std::sqrt(M / (r * r * r));
    }
};
```

**CRITICAL: This is a direct port of the working Python code.** The Hamiltonian formulation, the f = 1-2M/r factor, and the capture threshold at 2.5M have all been validated. Do not "improve" the physics — port it exactly.

---

## Task 3: Novikov-Thorne accretion disk (`include/astroray/accretion_disk.h`)

Port the disk model. Precompute the flux profile table at construction time.

Key physics:
- Page-Thorne flux profile F(r) with numerical integration from ISCO outward
- Temperature from Stefan-Boltzmann: T(r) = (F(r)/σ)^(1/4)
- Redshift factor: g = 1 / [(1 + Ωr sinθ sinφ) / √(1 - 3M/r)]

```cpp
class NovikovThorneDisk {
    const Metric* metric;
    double r_isco, r_outer, mdot;

    // Precomputed tables
    static constexpr int TABLE_SIZE = 1000;
    std::array<double, TABLE_SIZE> r_table, flux_table, temp_table;

    void buildFluxTable();  // Numerical integration of Page-Thorne formula

public:
    NovikovThorneDisk(const Metric* m, double outer = 30.0, double accretion = 1.0);

    bool inDisk(double r) const { return r >= r_isco && r <= r_outer; }
    double fluxAt(double r) const;       // interpolate flux table
    double temperatureAt(double r) const; // interpolate temp table

    // g = ν_obs/ν_emit including gravitational + Doppler shift
    double redshiftFactor(double r, double phi, double inclination) const;
};
```

The Page-Thorne flux integral is:
```
F(r) = (3M·ṁ)/(8π r³) × (1/√(1-3M/r)) × ∫[r_isco to r] (E-ΩL)·(dL/dr')/(E-ΩL)² dr'
```
where E, L, Ω are the specific energy, angular momentum, and angular velocity of circular orbits. For Schwarzschild:
```
E(r) = (1-2M/r) / √(1-3M/r)
L(r) = r√(M/r) / √(1-3M/r)  [= r²Ω / √(1-3M/r)]
Ω(r) = √(M/r³)
```

Use the same numerical integration approach as the Python code (trapezoidal rule over the table).

---

## Task 4: Spectral rendering pipeline (`include/astroray/spectral.h`)

Port the spectral pipeline. This is pure computation — no rendering-specific logic.

```cpp
// Planck blackbody B(λ,T) in W/(m²·sr·nm)
double planck(double wavelength_nm, double temperature_K);

// Hero wavelength sampling: generate 4 stratified wavelengths per ray
struct SpectralSample {
    double wavelengths[4];  // nm
    double radiance[4];     // accumulated
};

SpectralSample sampleHeroWavelengths(std::mt19937& gen,
                                      double lam_min = 200.0,
                                      double lam_max = 2000.0);

// CIE 1931 color matching (81 entries, 380-780nm, 5nm spacing)
// Stored as static arrays
Vec3 spectralToXYZ(const SpectralSample& sample);
Vec3 xyzToLinearSRGB(const Vec3& xyz);
Vec3 spectralToRGB(const SpectralSample& sample, float exposure = 0.0f);
```

The CIE tables are the same 81-entry arrays from the Python code. Store them as `static constexpr double[]` in the header.

For auto-exposure: the caller (the renderer) collects all Y values, computes the 99th percentile, and scales by `0.8 / p99`.

---

## Task 5: RK45 Dormand-Prince integrator (`include/astroray/gr_integrator.h`)

Port the adaptive integrator. This operates on single rays (not vectorized — the C++ version uses OpenMP parallelism at the pixel level instead of NumPy vectorization).

```cpp
struct IntegrationResult {
    GeodesicState finalState;
    std::vector<DiskCrossing> crossings;  // max 3 typically
    bool escaped;
    bool captured;
    Vec3 exitDirection;    // Euclidean direction after exiting influence sphere
    double frequencyShift; // cumulative g factor for exit ray
};

IntegrationResult integrateGeodesic(
    const Metric& metric,
    const NovikovThorneDisk* disk,  // nullptr if no disk
    GeodesicState initial,
    double inclination,
    int maxSteps = 5000,
    double h_init = -0.5,
    double atol = 1e-8,
    double rtol = 1e-6,
    double r_max = 200.0   // influence sphere radius
);
```

**Implementation:** Direct port of the Python `integrate_geodesics()` function, but for a single ray. The Dormand-Prince Butcher tableau coefficients are:

```cpp
// Already validated in the Python code — copy exactly
static constexpr double DP_C5[7] = {35.0/384, 0, 500.0/1113, 125.0/192, -2187.0/6784, 11.0/84, 0};
static constexpr double DP_C4[7] = {5179.0/57600, 0, 7571.0/16695, 393.0/640, -92097.0/339200, 187.0/2100, 1.0/40};
// DP_ERR[i] = DP_C5[i] - DP_C4[i]
```

The step size adaptation logic:
```cpp
double err_norm = maxAbsError / (atol + rtol * maxAbsState);
double factor = 0.9 * std::pow(err_norm, -0.2);
factor = std::clamp(factor, 0.2, 5.0);
h *= factor;
h = std::clamp(h, -50.0, -0.001);  // negative = backward integration
```

**Disk crossing detection:** After each accepted step, check if θ crossed π/2 (sign change in `theta - π/2`). If so, interpolate the crossing radius using the pre- and post-step theta values, then compute the redshift factor.

---

## Task 6: BlackHole as a Hittable object (`include/astroray/black_hole.h`)

The key integration class. A `BlackHole` is a `Hittable` that represents the influence sphere. When hit by a ray, it doesn't scatter — it runs the geodesic integrator and returns a remapped ray.

```cpp
#include "raytracer.h"
#include "astroray/metric.h"
#include "astroray/accretion_disk.h"
#include "astroray/gr_integrator.h"
#include "astroray/spectral.h"

class BlackHole : public Hittable {
    Vec3 position;          // world-space center
    double mass;            // in solar masses
    double influenceRadius; // world-space radius of the influence sphere
    double r_obs_M;         // influence radius in units of M (= r_influence / r_s * 2)

    std::unique_ptr<SchwarzschildMetric> metric;
    std::unique_ptr<NovikovThorneDisk> disk;

    // Disk parameters
    double diskOuterRadius;   // in units of M
    double accretionRate;
    double temperatureScale;  // converts code units to Kelvin
    double inclination;       // observer inclination (from spin axis)

    // Coordinate conversion
    double worldToGR;  // scale factor: world units → geometrized units (M)

public:
    BlackHole(Vec3 pos, double mass_solar, double influence_r,
              double disk_outer = 30.0, double mdot = 1.0,
              double incl_deg = 75.0);

    bool hit(const Ray& r, float tMin, float tMax, HitRecord& rec) const override;
    bool boundingBox(AABB& box) const override;

    // The GR rendering happens here — called by pathTrace when a BlackHole is hit
    struct GRResult {
        Vec3 color;           // accumulated spectral emission (linear RGB)
        Vec3 exitDirection;   // remapped direction (or zero if captured)
        bool captured;        // ray fell into event horizon
        bool hasEmission;     // disk was hit → color is nonzero
    };

    GRResult traceGeodesic(const Ray& incomingRay, std::mt19937& gen) const;
};
```

**`hit()`:** Standard ray-sphere intersection against the influence sphere. Sets `rec.material` to a special marker (or sets a flag) so `pathTrace` knows this is a GR object.

**`traceGeodesic()`:**
1. Convert the incoming ray's hit point and direction from world coordinates to Boyer-Lindquist coordinates relative to the black hole center
2. Construct the initial `GeodesicState` (compute p_t, p_r, p_θ, p_φ from the 3D direction — same math as `initialize_rays()` in the Python code)
3. Call `integrateGeodesic()` with the metric and disk
4. If disk crossings occurred: evaluate spectral emission (hero wavelengths, Planck, redshift, XYZ→RGB)
5. If ray escaped: convert the exit direction back to world coordinates
6. Return the result

---

## Task 7: Integrate into pathTrace()

Modify the main `pathTrace()` loop in `include/raytracer.h` to handle BlackHole hits.

The key insight: when `pathTrace` hits a `BlackHole`, it doesn't do normal material evaluation. Instead it calls `traceGeodesic()` and either:
- Adds disk emission to the accumulated color
- Continues path tracing with the remapped exit ray (if the ray escaped)
- Terminates (if captured by the event horizon)

```cpp
// Inside the bounce loop, after the hit test succeeds:
if (auto* bh = dynamic_cast<BlackHole*>(rec.material_owner_or_hittable)) {
    // GR rendering
    auto grResult = bh->traceGeodesic(ray, gen);

    if (grResult.hasEmission) {
        color += throughput * grResult.color;
    }

    if (grResult.captured) {
        break;  // absorbed by black hole
    }

    // Continue with remapped direction
    ray = Ray(rec.point, Vec3(grResult.exitDirection.x,
                               grResult.exitDirection.y,
                               grResult.exitDirection.z));
    wasSpecular = true;  // treat GR deflection as specular (no NEE needed)
    continue;
}
```

**Design choice for identifying BlackHole hits:**

Option A: Give BlackHole a special material type that pathTrace checks via dynamic_cast.
Option B: Add a `isGRObject()` virtual method to Hittable.
Option C: Store a pointer to the BlackHole in the HitRecord.

**Recommended: Option B** — add `virtual bool isGRObject() const { return false; }` to `Hittable`, override in `BlackHole`. Then store a pointer: add `const Hittable* hitObject` to `HitRecord` (set during `hit()`). pathTrace checks `rec.hitObject->isGRObject()` and calls `static_cast<const BlackHole*>(rec.hitObject)->traceGeodesic(ray, gen)`.

This avoids RTTI/dynamic_cast overhead in the inner loop.

---

## Task 8: Python bindings

Add `add_black_hole()` to the pybind11 module:

```cpp
void addBlackHole(const std::vector<float>& position, float mass_solar,
                  float influence_radius, py::dict params) {
    double disk_outer = params.contains("disk_outer") ?
        params["disk_outer"].cast<double>() : 30.0;
    double mdot = params.contains("accretion_rate") ?
        params["accretion_rate"].cast<double>() : 1.0;
    double incl = params.contains("inclination") ?
        params["inclination"].cast<double>() : 75.0;

    auto bh = std::make_shared<BlackHole>(
        Vec3(position[0], position[1], position[2]),
        mass_solar, influence_radius,
        disk_outer, mdot, incl);
    renderer.addObject(bh);
}
```

Pybind11 binding:
```cpp
.def("add_black_hole", &PyRenderer::addBlackHole,
     "position"_a, "mass"_a, "influence_radius"_a, "params"_a = py::dict())
```

---

## Task 9: Blender addon — black hole objects and UI

Add to `blender_addon/__init__.py`:

**Property group for black hole objects:**
```python
class AstrorayBlackHoleProperties(PropertyGroup):
    mass: FloatProperty(name="Mass (M☉)", min=0.1, max=1e10, default=10.0)
    influence_radius: FloatProperty(name="Influence Radius", min=1.0, max=10000.0, default=100.0)
    disk_outer: FloatProperty(name="Disk Outer Radius (M)", min=6.0, max=1000.0, default=30.0)
    accretion_rate: FloatProperty(name="Accretion Rate", min=0.01, max=100.0, default=1.0)
    inclination: FloatProperty(name="Inclination (°)", min=0.0, max=90.0, default=75.0)
    show_disk: BoolProperty(name="Show Accretion Disk", default=True)
```

**Operator to add a black hole empty:**
```python
class ASTRORAY_OT_add_black_hole(Operator):
    bl_idname = "astroray.add_black_hole"
    bl_label = "Add Black Hole"

    def execute(self, context):
        bpy.ops.object.empty_add(type='SPHERE')
        obj = context.active_object
        obj.name = "BlackHole"
        obj.empty_display_size = 5.0
        # Properties auto-attached via PointerProperty
        return {'FINISHED'}
```

**In convert_objects(), detect black hole empties:**
```python
if obj.type == 'EMPTY' and hasattr(obj, 'astroray_black_hole'):
    bh = obj.astroray_black_hole
    if bh.mass > 0:
        renderer.add_black_hole(
            list(obj.location), bh.mass, bh.influence_radius,
            {'disk_outer': bh.disk_outer,
             'accretion_rate': bh.accretion_rate,
             'inclination': bh.inclination})
```

Add a panel under Object Properties that shows when a black hole empty is selected.

---

## Task 10: Tests

```python
def test_black_hole_creation():
    """Test that a black hole can be added to the scene."""
    r = create_renderer()
    r.add_black_hole([0, 0, 0], 10.0, 100.0, {
        'disk_outer': 30.0,
        'accretion_rate': 1.0,
        'inclination': 75.0
    })
    setup_camera(r, look_from=[0, 0, 200], look_at=[0, 0, 0],
                 vfov=12, width=160, height=120)
    pixels = render_image(r, samples=4)
    assert_valid_image(pixels, 120, 160, min_mean=0.0, label='black_hole')
    save_image(pixels, os.path.join(OUTPUT_DIR, 'test_black_hole.png'))


def test_black_hole_shadow_is_dark():
    """The center of the black hole shadow should be very dark."""
    r = create_renderer()
    r.add_black_hole([0, 0, 0], 10.0, 100.0, {
        'disk_outer': 30.0, 'inclination': 75.0})
    # Load an HDRI so background is bright
    test_hdr = os.path.join(os.path.dirname(__file__), '..', 'samples', 'test_env.hdr')
    if os.path.exists(test_hdr):
        r.load_environment_map(test_hdr)
    setup_camera(r, look_from=[0, 0, 200], look_at=[0, 0, 0],
                 vfov=6, width=200, height=200)
    pixels = render_image(r, samples=8)

    # Center pixels should be dark (shadow)
    center_region = pixels[80:120, 80:120, :]
    center_mean = float(np.mean(center_region))
    edge_mean = float(np.mean(pixels[:20, :, :]))

    assert center_mean < edge_mean, \
        f"Shadow center ({center_mean:.3f}) should be darker than edges ({edge_mean:.3f})"
    save_image(pixels, os.path.join(OUTPUT_DIR, 'test_bh_shadow.png'))


def test_black_hole_with_geometry():
    """Black hole should coexist with normal geometry."""
    r = create_renderer()
    create_cornell_box(r)
    r.add_black_hole([0, 0, 0], 1.0, 20.0, {'disk_outer': 15.0, 'inclination': 60.0})
    setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0],
                 vfov=38, width=200, height=150)
    pixels = render_image(r, samples=16)
    assert_valid_image(pixels, 150, 200, min_mean=0.01, label='bh_with_geometry')
    save_image(pixels, os.path.join(OUTPUT_DIR, 'test_bh_cornell.png'))
```

---

## Critical implementation notes

### Double precision for the integrator, float for everything else
The GeodesicState and all RK45 math use `double`. The output colors and directions convert to `float` (Vec3) at the boundary. This is essential — the Python version originally had issues with coordinate stiffness near the horizon that get worse with single precision.

### Coordinate conversion: world → Boyer-Lindquist
The black hole is at a position in world space. To enter GR coordinates:
1. Translate: `p_local = hit_point - bh.position`
2. Scale: `p_gr = p_local / worldToGR` where `worldToGR = influence_radius / r_obs_M`
3. Convert Cartesian to spherical: `r = |p_gr|`, `θ = acos(y/r)`, `φ = atan2(z, x)` (Y-up convention!)
4. Direction → 4-momentum: project the 3D direction onto the BL basis vectors, compute p_r, p_θ, p_φ from the impact parameters α, β (same as `initialize_rays()`)

### Exit direction conversion: Boyer-Lindquist → world
When the ray escapes (r > r_influence in GR units):
1. Get (r, θ, φ) from the final state
2. Get direction from (dr/dλ, dθ/dλ, dφ/dλ) via the Hamiltonian → 3D direction
3. Convert from spherical to Cartesian
4. Scale and translate back to world space
5. The frequency shift g = -p_t_initial / p_t_final (for Schwarzschild, p_t is conserved so g=1 for escaped rays, but disk emission has its own g factor)

### Inclination vs camera angle
In the standalone addon, inclination was a render setting. In the merged version, the inclination is determined by the camera's position relative to the black hole's spin axis. The spin axis is the black hole's local Y axis (up). Compute: `inclination = acos(dot(cam_to_bh_normalized, bh_up_axis))`.

### NEE and black holes
Do NOT attempt NEE through a black hole. When `pathTrace` hits a BlackHole, it handles everything internally (geodesic integration + disk emission) and returns. The `wasSpecular = true` flag after GR processing ensures NEE is disabled for the next bounce.

### Performance expectation
Single-ray RK45 takes ~0.1–1ms depending on how close to the photon sphere. At 1080p with 4 samples, expect ~5-30 seconds for the GR component alone on a modern CPU with OpenMP. The standard path tracing for the rest of the scene runs at its normal speed.

### What NOT to do
- Do NOT use float for geodesic integration — will fail near the horizon
- Do NOT try to importance-sample the accretion disk via NEE — the geometry is in curved spacetime and standard light sampling doesn't apply
- Do NOT attempt to BVH-accelerate the geodesic integration — it's an ODE solve, not a ray-primitive intersection
- Do NOT convert the entire renderer to double precision — only the GR integrator needs it
- Do NOT port the Python NumPy vectorization strategy — C++ uses per-ray integration with OpenMP parallelism over pixels instead
