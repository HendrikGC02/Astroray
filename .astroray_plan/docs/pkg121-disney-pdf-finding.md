# pkg121 Disney BSDF Chi² Finding

**Status:** Under investigation (pkg123 to resolve)

**Date:** 2026-07-19

## Summary

Disney BSDF fails chi-squared sampler validation tests with histogram=1.0 (samples correctly distributed) but pdf_sum<1.0 (PDF integrates incorrectly). This indicates a `Material::sample()` vs `Material::pdf()` mismatch, but contradictions exist that must be resolved before confirming as an engine bug.

## Evidence Table

Per-case chi² results (all FAIL):

| Config          | metallic | roughness | transmission | histogram | pdf_sum | p-value  | Status |
|-----------------|----------|-----------|--------------|-----------|---------|----------|--------|
| diffuse_rough   | 0.0      | 1.0       | 0.0          | 1.000     | 0.750   | <0.001   | FAIL   |
| metal_low_rough | 1.0      | 0.1       | 0.0          | 1.000     | 0.008   | <0.001   | FAIL   |
| metal_mid_rough | 1.0      | 0.4       | 0.0          | 1.000     | 0.823   | <0.001   | FAIL   |
| metal_high_rough| 1.0      | 0.8       | 0.0          | 1.000     | 0.654   | <0.001   | FAIL   |
| glass_rough0.0  | 0.0      | 0.0       | 1.0          | 1.000     | 0.003   | <0.001   | FAIL   |
| glass_rough0.3  | 0.0      | 0.3       | 1.0          | 1.000     | 0.527   | <0.001   | FAIL   |

**Validation anchor (Lambertian):** histogram=1.000, pdf_sum=1.000, p-value=0.230 → PASS ✓

**Key observation:** ALL histograms = 1.000 (samples distributed correctly), but PDF integrals vary widely. This is the signature of a `pdf()` normalization issue.

## Contradictions to Resolve

### 1. Lobe-Selection Hypothesis REFUTED

Initial hypothesis: pdf() scales by lobe-selection weights (diffWeight/total, specWeight/total) but sample() doesn't.

**Prediction vs measurement:**

| Config          | diffWeight/total | Measured pdf_sum | Match? |
|-----------------|------------------|------------------|--------|
| diffuse_rough   | 0.500            | 0.750            | NO     |
| metal_low_rough | 0.000            | 0.008            | YES*   |
| metal_mid_rough | 0.000            | 0.823            | NO     |

*metal_low at roughness=0.1 is near-delta (grid resolution artifact, expected)

The lobe-selection weights do NOT explain the measured integrals.

### 2. Histogram vs Below-Horizon Mismatch

`test_disney_debug.py` sample probe (N=100):
- Above horizon (Y>0): 77
- Below horizon (Y<0): 23

**Expected:** histogram sum ≈ 0.77 (only above-horizon samples contribute)

**Actual:** histogram sum = 0.104

**Gap:** ~70% of mass missing even from the VALID samples. Something else is wrong in the histogram path.

### 3. Furnace Test Contradiction

pkg118 furnace tests pass at [0.92, 1.03] for Disney BSDF at roughness=1.0. If 23% of samples are below-horizon and killed, the integrator should show a massive energy deficit (~0.77). But it passes near 1.0.

**Hypothesis:** Either the below-horizon samples don't occur in production (HitRecord construction difference), or the integrator compensates somehow.

## Code Analysis

### pdf() Implementation (disney.cpp:517-546)

```cpp
float pdf(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
    // ... transmission check ...
    
    Vec3 H = (wo + wi).normalized();
    float diffWeight = (1 - metallic_) * (1 - transmission_);
    float specWeight = 1;
    float total = diffWeight + specWeight;
    float p = 0;
    
    // Diffuse lobe
    if (diffWeight > 0) 
        p += (rec.normal.dot(wi) / float(M_PI)) * (diffWeight / total);
    
    // Specular lobe
    if (specWeight > 0) {
        float D = D_GTR2(NdotH, a);
        p += (D * NdotH / (4 * HdotV + 0.001f)) * (specWeight / total);
    }
    
    return p;  // Returns MIXTURE pdf
}
```

### sample() Implementation (disney.cpp:486-494)

```cpp
float diffWeight = (1 - metallic_) * (1 - transmission_);
float specWeight = 1;
float total = diffWeight + specWeight;

if (dist(gen) * total < diffWeight) {
    // Sample diffuse lobe
    Vec3 localWi = Vec3::randomCosineDirection(gen);
    s.wi = rec.tangent * localWi.x + rec.bitangent * localWi.y + rec.normal * localWi.z;
    s.f = eval(rec, wo, s.wi);
    s.pdf = pdf(rec, wo, s.wi);  // Returns MIXTURE pdf
} else {
    // Sample specular lobe
    // ... GGX sampling ...
}
```

**Observations:**
1. Both sample() and pdf() use the same lobe-selection weights (diffWeight/total, specWeight/total)
2. sample() returns s.pdf from the MIXTURE pdf() function (line 494)
3. The mixture formula LOOKS correct

**Possible issues:**
- HitRecord construction: makeMaterialTestRecord() builds a SYNTHETIC tangent basis. Disney reads rec.tangent/bitangent for local→world transforms. If the synthetic basis is degenerate or inconsistent, sampled directions could be garbled.
- Grid integration artifacts: Near-delta lobes (roughness<0.2) integrate to near-zero on an 80×160 grid (expected limitation, not a bug)
- Missing normalization factor somewhere in the mixture

## Production Impact

**MIS weights:** `Material::pdf()` feeds the NEE-side BSDF PDF in the power heuristic:

```cpp
// spectral_path_tracer.cpp (approximate)
float bsdfPdf = material->pdf(rec, wo, wi);
float weight = powerHeuristic(lightPdf, bsdfPdf);
L += weight * bsdf * Le / lightPdf;
```

**Impact if pdf() is under-normalized:**
- ONE-SIDED integrator (pkg120 C2): BSDF-hits-light term dropped → no compensation
- bsdfPdf under-reported → NEE over-weighted → BIAS (not just variance)
- 25% under-normalization → measurable in image comparisons if this is the real bug

**Why furnace tests might pass anyway:**
- Furnace tests measure ∫eval(ω)cosθ dω (BRDF albedo), NOT ∫pdf(ω) dω
- If sample() generates correct samples (histogram=1.0) and eval() returns correct BRDF, the integral is right
- pdf() normalization only affects MIS weights, not path throughput directly

## Next Steps (pkg123)

1. **HitRecord construction test:**
   - Build HitRecord from REAL geometry hit (Sphere or Triangle)
   - Mirror how production integrator constructs it (check spectral_path_tracer.cpp intersection handling)
   - Re-run 100-sample probe, check below-horizon rate

2. **Histogram reconciliation:**
   - If real HitRecord → 0% below-horizon, histogram should = 1.0
   - If synthetic HitRecord is the issue, fix makeMaterialTestRecord()
   - If histogram still ≠ valid fraction, debug binning logic

3. **Furnace cross-check:**
   - Run pkg118 furnace test WITHIN chi² test harness
   - Check if ∫eval(ω)cosθ dω ≈ ∫sample() weighted ≈ 1.0
   - If furnace integral correct but pdf integral wrong → confirms pdf() normalization issue

4. **Near-delta handling:**
   - Document that roughness<0.2 requires higher resolution or is out-of-scope
   - Add roughness floor to Disney tests or mark slow high-res variants

## References

- Chi² harness: Mitsuba 3 (BSD-3-Clause, Wenzel Jakob)
- pbrt-v4 constants: Apache-2.0, Matt Pharr
- Disney BSDF: `plugins/materials/disney.cpp`
- Furnace tests: pkg118
- MIS weights: pkg120 C2 audit (one-sided integrator)
