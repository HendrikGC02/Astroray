# astroray GPU Header Notes

The headers in this directory define the CUDA-side data model and interfaces
for the optional GPU path tracer backend.

Important:

- They are not the primary CPU renderer implementation.
- The canonical CPU renderer remains in `include/raytracer.h` and
  `include/advanced_features.h`.
- Some GPU functionality may be partial or evolving; verify behavior against
  the CPU renderer and tests before relying on these headers as feature-complete.
