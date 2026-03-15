## Project Structure
src/          C++ ray tracer source
include/      Header files (raytracer.h, advanced_features.h)
blender_addon/ Python Blender integration module
CMakeLists.txt Build configuration

## Build & Test Commands
Build:  mkdir -p build && cd build && cmake .. && make -j8
Test:   ./build/astroray --test    # or however you run tests

## Domain Context
C++ ray tracer with physically-based rendering. Key concepts:
Vec3, Ray, Material, Hittable, BVH, MoE (not ML — Monte Carlo estimation).
Blender integration via pybind11.

## Important Files
include/raytracer.h       - Core data structures, do not refactor casually
include/advanced_features.h - Transform classes and mesh support
CMakeLists.txt            - Controls both standalone and Blender build targets