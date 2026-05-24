# Next Steps — pkg76-followup-classroom-fidelity

**Current status:** Gap 1 (image texture loading) implemented and tested. Ready for GPU verification.

---

## What's been completed

1. **Fidelity audit** (`.astroray_plan/docs/pkg76-classroom-fidelity-audit.md`):
   - Analyzed Classroom .blend metadata (42 materials, 9 lights, 182 meshes)
   - Identified 4 gaps with Cycles citations + (a)/(b)/(c) classifications
   - Gap 1 (40/42 materials use image textures) classified as highest-impact

2. **Gap 1 fix** (`tools/blend_import/scene_builder.py` + `reader.py`):
   - Walk node tree links to find TEX_IMAGE nodes connected to Principled BSDF Base Color
   - Resolve Blender `//` relative paths with fallback for nested archive layouts
   - Load image with PIL, compute average RGB, use as material base color
   - **Verified via** `scripts/test_texture_import.py`: materials now produce correct colors
     (e.g., beige [0.50, 0.48, 0.34] instead of white [0.82, 0.82, 0.82])

3. **Supporting scripts**:
   - `scripts/dump_classroom_metadata.py` — extract .blend metadata via Blender Python
   - `scripts/render_classroom_comparison.py` — standalone Cycles vs Astroray render + diff
   - `scripts/test_texture_import.py` — unit test for image texture loading

---

## What's needed to close the package

### Step 1: Build and verify

```powershell
# From repository root
cd C:\Users\hgcom\OneDrive\Astroray\Astroray_repo\Astroray-pkg76-classroom

# Build (if not already built)
cmake --build build_cuda --config Release --target astroray

# Verify astroray.pyd loads
python -c "import sys; sys.path.insert(0, 'build_cuda/Release'); import astroray; print(astroray.__file__)"
```

### Step 2: Re-render Classroom

Option A (full parity harness):
```powershell
python scripts\run_parity.py --scene classroom --engine cycles-cpu,astroray-gpu --runs 1
```

Option B (standalone comparison script):
```powershell
python scripts\render_classroom_comparison.py
```

This will generate:
- `test_results/pkg76-classroom-cycles-cpu.exr`
- `test_results/pkg76-classroom-astroray-gpu.exr`
- `test_results/pkg76-classroom-diff.png`
- SSIM measurement printed to console

### Step 3: Evaluate SSIM

**If SSIM ≥0.85:** Gap 1 alone closed the gate. Append measurement to parity CSV, commit diff.png, push PR.

**If 0.70 ≤ SSIM < 0.85:** Gap 1 improved but didn't clear gate. Implement Gap 3 (spot light cone params, ~30 min):

```python
# In _emit_light(), after reading energy:
if light_type == LA_SPOT:
    spot_size = blend.read_float(light_blk, light_struct, "spot_size")[0]
    spot_blend = blend.read_float(light_blk, light_struct, "spot_blend")[0]
    # Pass to renderer (check Renderer API signature)
```

Re-render and measure again.

**If SSIM < 0.70:** Gap 1 fix didn't apply as expected. Inspect the diff.png to diagnose:
- Are walls/floors still untextured? → Check which materials failed to load textures
- Is lighting too bright/dark? → Implement Gap 3 (spot lights) or Gap 4 (area lights)

### Step 4: Check for regressions

```powershell
python scripts\run_parity.py --scene junkshop --engine astroray-gpu --runs 1
```

Verify Junkshop SSIM ≥ 0.972 (the PR #357 baseline). If it drops, bisect to find the regression.

### Step 5: Push PR

```powershell
git push origin pkg76-followup-classroom
gh pr create --title "feat(pkg76-followup): Classroom fidelity audit + image texture loading" \
  --body "$(cat .github/pr_template.md)"
```

PR body should include:
- Audit summary (4 gaps classified)
- Gap 1 fix description + Cycles citation
- SSIM before/after measurements
- Visual diff image (embedded or linked)
- Link to audit doc

---

## Known limitations (from environment setup attempts)

1. **DLL loading issue:** `ImportError: DLL load failed while importing astroray` when running Python scripts.
   - Likely missing OIDN or CUDA runtime DLLs in PATH
   - Solution: Ensure `C:\oidn\bin` is in PATH before running Python
   - Alternative: Use the build_cuda_run.bat wrapper (but it's main-pinned per memory.md)

2. **Cycles/Blender availability:** `render_classroom_comparison.py` requires Blender 4.x on PATH.
   - If not available, use `run_parity.py` with `--blender <path>`
   - Or skip Cycles re-render and use the PR #357 reference EXR if it was saved

---

## Fallback: If GPU verification blocked

If the environment can't load astroray.pyd (DLL issues), the implementation is still DONE and can be reviewed on code quality alone:

1. **Open PR** with the current commit
2. **Mark as draft** with a note: "Gap 1 implemented; GPU verification pending due to local env"
3. **Request review** from a teammate with a working RTX setup
4. They can pull the branch, build, run the parity benchmark, and append the results

The code changes are self-contained and testable via `scripts/test_texture_import.py` (which runs without GPU).

---

## Summary for PR reviewer

**What changed:**
- `scene_builder.py`: Added `_node_texture_color()` and `_load_image_texture_color()` to walk shader node links, find TEX_IMAGE nodes, load images, and sample average RGB
- `reader.py`: Added `path` attribute to `BlendFile` to enable relative-path resolution
- Audit doc classifies 4 gaps; Gap 1 (highest impact) is fixed

**Expected impact:** SSIM 0.47 → 0.70–0.80 (estimated)

**Verification:** Run `python scripts/test_texture_import.py` to see non-default RGB values for textured materials.

**Full test:** `python scripts\run_parity.py --scene classroom --engine astroray-gpu` and check SSIM in the CSV output.
