# IES normalization — Cycles vs Astroray (Batch A item 1)

Source: `intern/cycles/util/ies.cpp` (Blender main, Apache-2.0), `kernel/svm/ies.h`.

## Cycles
- `IESFile::parse_type_c` (and type A/B) apply, per candela value:
  `factor = candela_multiplier * ballast_factor * ballast_lamp_photometric_factor`
  then `factor *= 0.0706650768394;` where `0.0706650768394 = 4*pi / 177.83`.
  Comment: candela (lumen/sr) -> radiometric Watt. D65 luminous efficacy 177.83
  lm/W; the `4*pi` converts Watt/sr to the total Watt Cycles wants for lamp
  strength.
- `process()` does symmetry/mirroring and deg->rad on the angle arrays. It does
  **NOT** peak-normalize the intensity table.
- `svm_node_ies` (kernel/svm/ies.h): `fac = strength * kernel_ies_interp(...)`.
  i.e. the node output = light Strength * the (absolute) interpolated table value.

## Astroray (`IESProfile::loadFromFile`, include/raytracer.h)
- table[i] = candela[i] * max(candelaMultiplier, 0)
- then **peak-normalized**: `for c in table: c /= maxCandela` so max == 1.0.
- Consumed as a directional multiplier on the light radiance; the light's own
  `intensity` (= Blender light.energy) is applied separately in
  PointLight/SpotLight.

## Difference
Cycles carries absolute candela->Watt magnitude in the table (constant
0.0706650768394) and multiplies by Strength. Astroray treats IES as a pure
directional SHAPE (peak-normalized to 1) times light.energy. The relative
directional shape (ratio between any two directions) is IDENTICAL between the
two; they differ only by a per-profile global scale = maxCandela / (4pi/177.83).

## Fork (surfaced to owner)
Astroray's absolute light energy is already ~3x off Cycles (settings_map note,
pkg89/pkg115). Removing peak-normalization + applying 4pi/177.83 would tie IES
magnitude to the file's absolute candela values on top of an already-divergent
energy scale, i.e. it would NOT bring the absolute result closer to Cycles; it
would only change IES lights' brightness surprisingly relative to non-IES lights.
Peak-normalization (IES as a gobo/directional modulation of light.energy) is a
legitimate and lower-risk model. Decision taken for this batch: KEEP
peak-normalization, cite the Cycles constant in code, and document the divergence;
the unit test asserts both our peak-norm invariant and the Cycles constant value.

## Decision (Batch J item 2, owner 2026-09-13) — HONOUR ABSOLUTE CANDELA

The 2026-09-12 "keep peak-normalization" decision rested on a STALE premise:
"Astroray's absolute light energy is already ~3x off Cycles (pkg89/pkg115)".
That is no longer true. **pkg122 (PR #500, 2026-07-21)** re-derived every
dedicated light type's wattage->radiance against the Cycles kernel
(GPU==CPU 0.997-0.998); the 0.13x (AREA), 3.6x/4x (POINT), 14x (BLACKBODY)
factors were eliminated. With the light energy scale now matching Cycles, the
physically accurate IES model is unambiguous: honour the file's ABSOLUTE
candela distribution so a 1000 W luminaire file does not render like a 100 W
one.

**Implemented:**
- `IESProfile::loadFromFile` (include/raytracer.h): removed the peak-
  normalization (`table /= maxCandela`); each candela is now scaled by
  `candela_multiplier * 4*pi/177.83` (= 0.0706650768394), exactly as Cycles
  `intern/cycles/util/ies.cpp` (Apache-2.0). `0.0706650768394 = 4*pi/177.83`:
  candela (lm/sr) -> radiometric W/sr via D65 luminous efficacy 177.83 lm/W,
  x4pi to the total-Watt convention light Strength uses.
- Addon (`blender_addon/__init__.py`): the TexIES node Strength input is folded
  into the light intensity (Cycles `fac = strength * table`, kernel/svm/ies.h).
- Engine composition unchanged: `intensity * 1/(4*pi) * iesValue`. Invariant:
  a flat 1-candela IES == a no-IES light times `4*pi/177.83`; rendered
  brightness scales linearly with the candela values (regression tests in
  tests/test_batch_a_ies_export.py).

**GPU gap (explicit, not silently shipped):** IES is CPU-only. The wavefront
GPU path does not mirror the IES modulation (point_light.cpp v1 comment:
"IES modulation is not mirrored on the GPU in v1"). Absolute IES magnitude
therefore applies on the CPU backend only; on GPU an IES PointLight/SpotLight
renders as a plain light. Filed as a follow-up gap in the PR.

**Correction to earlier notes:** the prior claim that the Cycles constant and
the peak-norm differ "only by a per-profile global scale" is exactly why the
absolute model matters — that global scale IS the physical luminaire output,
which a peak-norm drops.
