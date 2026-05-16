# pkg55 Phase B' — Session 2c Technique Review (first-principles)

**Author:** Architect (methodological/architectural review)
**Date:** 2026-05-16
**Status:** advisory — recommendation for owner decision
**Scope:** Session 2c close gate; program-wide bit-identity gate definition
**Method:** Aristotelian decomposition to irreducible causes. Read-only review of
`Astroray-pkg55-2c` worktree @ `pkg55-bprime-session2c`, the pkg55 spec, the
Session 2 design doc, the 2a handoff, and the wavefront research note. No code
was modified.

---

## 0. Bottom line up front

**The stated root cause is wrong.** The escalation history frames Session 2c's
failure as an `-ffast-math` FMA-fusion problem ("the oracle TU and the wavefront
stage TUs compute slightly differently from the SAME inlined headers"). That is
a *real second-order effect*, but it is **not** why the snapshot stream diverges.
The divergence enters because the wavefront skeleton **does not execute the same
sequence of IEEE-754 operations as the oracle** — by construction. Three
independent structural divergences are present in the code on
`pkg55-bprime-session2c` right now, any one of which alone defeats bit-identity:

1. **The RNG stream is reconstructed by hand-counted dimension replay** in
   `stage_shade_lambertian.cpp` (lines ~199–217, ~271–290, ~331–353). The
   oracle (`reference_pt_wavefront.cpp`) consumes ONE `WavefrontRNG` instance
   that auto-increments its dimension counter monotonically across the whole
   path. The wavefront re-keys a *fresh* `WavefrontRNG` at every NEE/RR/BSDF
   site and tries to fast-forward it with an open-coded draw-count model that
   the code's own comments admit is "brittle," "wasteful," "getting complex,"
   and "approx." This is not an FP problem. It is a *different random number
   sequence*. The `nee_light_pdf` ~8.85e-3 divergence the team measured is the
   signature of a different light sample, not a fused multiply-add.

2. **The wavefront re-traces the BVH inside the shade stage** to recover the
   material pointer (`stage_shade_lambertian.cpp:104–110`), because
   `stage_intersect.cpp` only stores `hit_material_id` as a flag (`1`/`-1`),
   not the geometry. The oracle never does this. Two BVH traversals with
   different `tmax` (`FLT_MAX` in intersect vs `hit_t + 0.001f` in shade) and
   different ray normalization state are not guaranteed to return the
   bit-identical `HitRecord`, and the second trace's `rec.point`/`rec.normal`
   is what actually flows into NEE and the next ray — *not* the SoA values the
   snapshot recorded at PostIntersect.

3. **The ray state round-trips through SoA scalar floats and is
   re-`Ray()`-constructed** every stage (`Ray ray(origin, direction)` in
   `stage_intersect.cpp:43` and `stage_shade_lambertian.cpp:104`). `Ray`'s
   constructor normalizes `direction`. The oracle carries one `Ray` object
   across the whole bounce loop and normalizes exactly once per bounce
   (`reference_pt_wavefront.cpp:225`, field-assigning the camera frame). This
   is the *exact* failure mode Phase A.1 already discovered and documented for
   the GPU path (spec lines 156–157: "reconstructed `GRay(o,d)` … re-normalize
   … 1-ulp drift … Fix: default-construct … field-assign"). The CPU skeleton
   reintroduced the identical bug A.1 had already root-caused.

The `-ffp-contract=off` patch on the scaffold TUs (CMakeLists diff in the
worktree) is **a symptom patch on the wrong layer**. It would, at best, remove
divergence source #4 (per-TU FMA fusion of *identical* op sequences) while
leaving #1, #2, #3 fully live. It cannot reach 0.0 and will read as
whack-a-mole. Worse, it sets a precedent (`/fp:precise` on scaffold) that does
not survive the CUDA port at all — nvcc FMA contraction, libm divergence, and
SSE-vs-PTX rounding are a different problem space, so a CPU-only flag fix
teaches the program nothing transferable.

**Recommended definitive technique:** make the wavefront a **pure scheduling
re-expression over one shared arithmetic kernel**, not a re-transcription.
Extract the per-bounce body (intersect + shade + NEE + RR) and the RNG carrier
into single functions that *both* `reference_pt_wavefront` and the CPU
wavefront call. Carry the live `WavefrontRNG` (and the material/hit) in SoA
state, not reconstruct it. Then bit-identity is **true by construction** —
the same function on the same bytes — and the close gate becomes a structural
proof, not an empirical diff that we keep chasing. Keep `-ffp-contract=off`
*only* as a belt-and-braces guard, not as the mechanism.

---

## 1. Is bit-identity-by-snapshot-stream the right Session 2c target?

### 1.1 Decompose the purpose

Session 2c does not exist to prove the renderer is correct (the SSIM gates and
the trip-wire do that). It exists to **validate one methodological claim**: that
*re-expressing a path tracer as a staged, SoA, per-slot wavefront does not
change the computation it performs.* If that claim holds on CPU for the
simplest possible scene, then every later session can trust the wavefront
decomposition itself and only debug the new material/feature it adds. If it
does not hold, the methodology is unsound and every later session inherits an
untrustworthy substrate.

So the irreducible thing Session 2c must guarantee is:

> **The wavefront and its oracle perform the identical computation.**

"Bit-identical snapshot stream" is one *witness* of that property — a necessary
consequence if the property holds. But the team has been treating the witness
as the target and chasing the diff. That inverts the logic. **The target is the
structural property; the snapshot diff is only how you detect a violation of
it.**

### 1.2 Is "exact 0.0" the right invariant?

Yes — but only because, and exactly when, the property in §1.1 is achievable by
construction on CPU. Two same-platform C++ routines that execute the *identical
ordered sequence of IEEE-754 operations on the identical input bits* produce
byte-identical results. That is deterministic, not aspirational. So on CPU↔CPU,
"exact 0.0" is the correct invariant **provided the wavefront is built as a
re-scheduling of the oracle's own arithmetic, not an independent transcription
of it.**

The owner was right to reject the 1e-5 ULP tolerance. A tolerance here is not
"accounting for floating-point" — it is *hiding the fact that the two code
paths are not the same computation.* The measured 8.85e-3 at `nee_light_pdf`
proves the point: that is not rounding, that is a different light sample drawn
from a desynchronized RNG. A tolerance would have shipped a broken methodology
with a green light.

### 1.3 The correct framing of the gate

The Session 2c close gate should be stated as a **structural guarantee with an
empirical witness**, in this order:

> **(Structural)** The CPU wavefront's per-bounce arithmetic is produced by
> calling the *same* intersect/shade/NEE/RR functions and the *same* live RNG
> object that `reference_pt_wavefront` calls; the wavefront only changes *when*
> and *in what loop nest* those functions run, never *what* they compute.
>
> **(Witness)** Therefore the per-stage `WavefrontSnapshot` stream is
> bit-identical (exact 0.0, slot-by-slot, field-by-field) on Lambertian-Cornell
> at 1 spp. A non-zero diff is a *proof that the structural guarantee was
> violated* and localizes where.

This is strictly stronger and more useful than "diff must be 0.0," because it
tells the implementer *why* it must be 0.0 and *what to fix* when it isn't:
don't tune flags — find the place where the wavefront stopped calling the
shared function.

---

## 2. Is scaffold-TU `-ffp-contract=off` fundamentally sound?

**No, not as the mechanism.** Decomposition:

### 2.1 The minimal conditions for byte-identical float results

Two C++ routines produce byte-identical `float`/`double` outputs **iff** all of:

1. **Identical ordered operation graph.** Same operations, same operands, same
   order, same associativity grouping. (`a*b+c` as one FMA vs `mul` then `add`
   is two different graphs; `(a+b)+c` vs `a+(b+c)` is two different graphs.)
2. **Identical rounding for every operation.** Same precision (no x87 80-bit
   intermediates vs SSE 32-bit), same rounding mode, same FMA-contraction
   decision per multiply-add site.
3. **Identical transcendental/library implementations.** `std::sin`, `exp`,
   `pow`, `1.0f/x`, `sqrtf` must resolve to the same routine with the same
   rounding (libm is not IEEE-correctly-rounded and is not portable).
4. **Identical inputs as bit patterns**, not as "mathematically equal" values.

Condition (1) subsumes "same RNG draws" because a different random sample is a
different operand → a different operation graph downstream.

### 2.2 What `-ffp-contract=off` actually addresses

It pins condition (2)'s *FMA-contraction* sub-clause, and only that. It does
nothing for (1) operation-graph divergence, nothing for (3) libm, nothing for
the `-ffast-math` *reassociation* still active on the scaffold under
`-ffast-math` minus only `-ffp-contract` (`-ffast-math` also enables
`-funsafe-math-optimizations` → reassociation, `-ffp-contract=fast` is one part
but `-fassociative-math`/`-freciprocal-math` reorder and rewrite independently;
turning off contraction does not turn those off). On MSVC, `/fp:precise` on the
scaffold while production is `/fp:fast` is a *different* codegen contract again,
and the scaffold calls into production headers compiled `/fp:fast` — so the
inlined `Vec3`/intersection math still fuses per the *including* TU's flags in
ways that are not uniform.

### 2.3 Why it springs leaks here specifically

The three structural divergences in §0 are all condition-(1) violations
(different operation graphs: a different RNG sample, a second BVH trace, an
extra normalization). `-ffp-contract=off` cannot touch a condition-(1)
violation. Even in the hypothetical where #1/#2/#3 were fixed, scaffold TUs
`#include` `raytracer.h` etc. and **inline production math compiled under the
*scaffold's* flags is not the same as under production's flags** — but that is
fine *for CPU↔CPU* because *both* scaffold sides (oracle and wavefront) get the
*same* scaffold flags, so they fuse identically *to each other*. That last point
is the only thing the flag buys, and it is **automatically satisfied the moment
both sides call one shared function compiled in one TU** — which is the §3
recommendation. So the flag is redundant with the real fix and insufficient
without it. Keep it only as a cheap defensive guard.

### 2.4 The structural answer

Two routines are guaranteed byte-identical *by construction* when they are
**literally the same routine invoked on the same bytes.** The wavefront should
not "mirror" the oracle's loop body — it should *call it*. The "wavefront" is
then provably nothing more than a different traversal order over a queue of
slots, where each slot's per-bounce step is the *identical* function call the
oracle makes. There is no diff to chase because there is no second
implementation. This is exactly what Phase A.1 did right on GPU and stated in
its own design ("calls the same `gpu_generateCameraRay()` helper the AoS
megakernel inlines, so identity is by construction" — spec line 132; "calls
`gpu_bvh_hit()` (the same entry point the megakernel uses)" — line 133). Session
2c violated A.1's own established principle by transcribing instead of sharing.

---

## 3. Definitive path to close Session 2c

**Technique: Shared-kernel wavefront (re-schedule, do not re-transcribe).**
Concrete, terminating, low-leak. Five steps.

### Step 1 — One shared per-bounce kernel

Extract the body of `reference_pt_wavefront.cpp::tracePathSpectral`'s loop
iteration into a free function with an explicit, serializable state object:

```cpp
// shared by BOTH the oracle and the wavefront. One TU, one definition.
struct PathStep {                 // everything a bounce needs / produces
    Ray        ray;               // carried object — normalized once, like the oracle
    SampledSpectrum throughput;
    SampledWavelengths lambdas;
    SampledSpectrum    radiance;  // accumulator
    bool       wasSpecular;
    bool       alive;
    HitRecord  rec;               // carried, NOT re-traced in shade
};
// returns next-bounce state; emits the 5 snapshots; consumes `rng` in the
// exact order the current oracle does. NO re-keying, NO dimension replay.
PathStep advance_one_bounce(Renderer&, PathStep, WavefrontRNG& rng,
                            int bounce, int maxDepth, SnapshotSink*);
```

The oracle becomes: `for (bounce…) state = advance_one_bounce(state, rng…)`.

### Step 2 — Carry the live RNG and hit in SoA, do not reconstruct them

The wavefront's SoA state stores the **`WavefrontRNG` object itself** (it is a
small POD: key + counter — serialize the 64–96 bits of PCG/counter state per
slot) and the carried `HitRecord`/material handle. Delete every
"reconstruct WavefrontRNG / consume init draws / replay per-bounce draws" block
in `stage_shade_lambertian.cpp`. The wavefront stage loop becomes:

```cpp
for (slot : active) {
    PathStep s = load_soa(slot);
    s = advance_one_bounce(renderer, s, rng[slot], bounce[slot], maxDepth, sink);
    store_soa(slot, s);
}
```

`advance_one_bounce` is *the same function* the oracle calls. Bit-identity is
now a theorem: same code, same bytes, same order. The only remaining freedom is
loop nesting (per-slot vs per-path), which by construction cannot change FP
results because each slot's call is independent and self-contained.

### Step 3 — Split intersect/shade *without* a second BVH trace

The wavefront's value is that intersect and shade are separate stages. Preserve
that by having `stage_intersect` call the shared closest-hit helper and store
the **full carried `HitRecord` (including material handle)** into SoA — not a
`1/-1` flag. `stage_shade_lambertian` then *consumes* that stored hit; it must
never call `bvh->hit` again. The stage boundary is a pure SoA serialize/restore
of the *same* `HitRecord` the oracle holds in a register. (This is also the
correct GPU design — A.1 already defers tangent/bitangent but stores the hit;
storing a material index is standard Cycles `isect.prim/object` practice, per
the research note §2.)

### Step 4 — Ray object discipline (re-apply the A.1 fix)

Never `Ray ray(origin,direction)` from SoA scalars in a stage (the constructor
re-normalizes → the A.1 1-ulp bug). Serialize/restore the `Ray`'s already-
normalized fields directly (default-construct, field-assign), exactly as spec
lines 156–157 mandate for GPU. Add a one-line comment citing the A.1 subtlety
so session 3+ does not regress it again.

### Step 5 — Keep `-ffp-contract=off` only as a guard, and document why

After steps 1–4, oracle and wavefront call one function in one TU; their FP
codegen is identical to each other *regardless* of the flag. Keep
`-ffp-contract=off` / `/fp:precise` on the scaffold TUs as a *defensive*
invariant (it also makes the scaffold's results stable across future compiler
upgrades and easier to reason about), but the doc/comment must state plainly:
**this flag is not the mechanism for bit-identity; shared-kernel construction
is. The flag is a guard against accidental future divergence and a courtesy to
the eventual CPU↔CPU debugging of new materials.** This kills the whack-a-mole:
there is no symptom left to patch because there is no second implementation.

### Why this terminates

Whack-a-mole happens when you fix outputs. This fixes the *generator* of the
outputs: there is exactly one generator. The diff harness can then only fail if
someone *adds* a second code path (e.g., a future session re-transcribes a
material) — and that failure is immediately localized by the snapshot field and
is, correctly, a real bug, not FP noise. The gate becomes self-policing for all
of sessions 3..N.

### How to verify

1. **Structural check (cheap, do first):** grep the wavefront stage TUs for
   `bvh->hit`, `WavefrontRNG gen(`, `Ray ray(`. After the refactor there must be
   *zero* `bvh->hit` in `stage_shade_*`, *zero* re-keyed `WavefrontRNG`
   constructions in any stage (RNG comes from SoA), *zero* `Ray(o,d)`
   constructions from SoA scalars. This is a static proof the structural
   guarantee holds; it should be a CI assertion.
2. **Witness check:** the existing snapshot diff harness must report exact 0.0
   across all 5 stages, all slots, all fields, Lambertian-Cornell 1 spp.
3. **Trip-wire + equivalence (already 2b's gates):** unchanged; must still pass.
4. **Determinism check:** run the wavefront twice; snapshot streams must be
   byte-identical run-to-run (guards against any latent ordering nondeterminism
   before it reaches the CUDA port where it would be catastrophic).

---

## 4. Does the bit-identity methodology survive the CUDA port? Program-wide gate.

**The CPU↔CPU "exact 0.0" gate is correct and must stay. The CPU↔GPU gate as
implied by spec line 279 ("Bit-identity gates each port") is physically
unsound and must be re-derived now, before sessions N+2..M inherit it.**

### 4.1 First principles: CPU↔GPU exact equality is impossible

The §2.1 conditions cannot all hold across CPU and GPU: nvcc fuses FMAs by
default and differently from host; CUDA `sinf`/`expf`/`__fdividef` are not the
host libm and not IEEE-correctly-rounded; SSE2 vs PTX rounding of intermediates
differ; `-ffast-math`/`/fp:fast` host reassociation has no PTX equivalent. No
flag makes them bitwise equal. **A "CPU↔GPU bit-identity" gate is unachievable
by construction** — chasing it on GPU would be the same whack-a-mole, one layer
out, and worse because the leaks are in vendor libm.

### 4.2 The right invariant per layer (re-derived)

The methodology must use **two different gate definitions for two
structurally-different equivalences**:

| Layer | What is provable | Correct gate |
|---|---|---|
| **CPU oracle ↔ CPU wavefront** | Same code, same bytes, same order → byte-identical | **Exact 0.0 snapshot diff** (structural guarantee + witness, §1.3). Keep as-is. |
| **CPU production ↔ CPU `reference_pt_production`** | Same RNG scheme, independent transcription tracking production | Bit-exact RGB at 1 spp (the existing trip-wire). Keep as-is. |
| **CPU wavefront ↔ CUDA wavefront** | *Not* the same operations (different hardware) — only the same *algorithm* | **ULP-bounded per-stage agreement on PostInit/PostIntersect, and statistical agreement thereafter.** Define: PostInit/PostIntersect (no transcendentals, geometry only) ≤ a small fixed ULP bound (e.g. ≤ 4 ULP, *measured and pinned*, not invented); Post-Shade/LightSample/RR compared as **per-stage relative-error distribution** with a hard p99.9 bound, plus the existing SSIM ≥ 0.985 image gate. The CPU↔GPU per-stage harness's job is *localization* (which stage's distribution widened), not exact equality. |
| **Whole program (final)** | Algorithm parity, not bit parity | The original Phase B/C SSIM (≥0.985 vis / ≥0.97 NIR) and perf gates. Unchanged. |

The crucial re-derivation: **the CPU↔CPU gate is a correctness-by-construction
proof; the CPU↔GPU gate is a numerical-agreement bound.** Conflating them (spec
line 279's "bit-identity gates each port") would force the GPU sessions into an
impossible target and re-trigger exactly the crisis Session 2c is in. Fix the
spec language now.

### 4.3 Why this preserves the methodology's value

The point of the per-stage CPU↔GPU harness was never bitwise equality — it was
**localization**: if the final image is wrong, which stage introduced it? That
value is fully retained by a per-stage *bounded-agreement* harness. The exact-
0.0 discipline still does real work where it is achievable (CPU↔CPU), catching
any session that breaks the shared-kernel structure. The two gates compose: a
CPU↔GPU stage that exceeds its ULP/distribution bound is debugged by first
confirming the CPU side is still exact-0.0 against the oracle (so the bug is in
the CUDA mirror, not the algorithm), then comparing the CUDA stage's inputs
(which are ULP-close) to isolate the divergent op. That is a *terminating*
debugging procedure; "make GPU bit-equal CPU" is not.

### 4.4 Concrete spec actions (for the architect to file, not done here)

1. Rewrite Phase B' staged-plan item 5 ("Bit-identity gates each port") to the
   §4.2 two-tier definition. The word "bit-identity" must appear *only* for
   CPU↔CPU.
2. Add to Phase B' design decisions a 9th decision: **"Wavefront is a
   re-scheduling of one shared per-bounce kernel, never a re-transcription"** —
   with the structural CI checks from §3-verify as the enforcement. This is the
   single most important invariant for sessions 3..N and is currently *implicit
   and violated*.
3. Add the A.1 ray-normalization subtlety (spec 156–157) to the Session 2c
   design doc as an explicit checklist item, because it has now regressed twice
   (once on GPU in A.1, once on CPU in 2c).

---

## 5. Opinionated verdict

The current direction (`-ffp-contract=off` on scaffold TUs) is **wrong as a
solution and right only as an afterthought**. It treats a condition-(1)
operation-graph divergence with a condition-(2) flag, which cannot close and
will read as the next whack-a-mole turn. The escalation's own framing ("under
`-ffast-math`, header-inlined FP fuses per TU") is a true statement about a
*fourth, smallest* divergence source that is irrelevant until the first three
(hand-replayed RNG, in-shade BVH re-trace, ray re-normalization) are removed —
and all three are removed *for free* by the one correct move: **make the
wavefront call the oracle's own per-bounce kernel and carry live RNG+hit in
SoA, so bit-identity is a theorem, not a measurement.** Phase A.1 already proved
this is the right pattern on GPU and even wrote it down; Session 2c regressed
from it. Adopt the shared-kernel construction, keep exact-0.0 for CPU↔CPU,
and re-derive the CPU↔GPU gate to bounded-agreement before any CUDA session
inherits an impossible target.

**One focusing question for the owner:** Are you willing to spend Session 2c's
remaining budget on a *refactor to shared-kernel* (one `advance_one_bounce`
called by both sides, RNG+hit carried in SoA) rather than continuing to pin FP
flags — accepting that this is the only path that terminates and that it also
de-risks every later session — or is there a constraint (e.g., the wavefront
must not share C++ code with the oracle for the GPU port to be a clean mirror)
that I should factor in before you commit?
