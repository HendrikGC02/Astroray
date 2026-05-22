cmake_minimum_required(VERSION 3.18)
project(CustomRaytracer VERSION 3.0 LANGUAGES CXX)

# Windows-specific options
option(WIN32_STANDALONE "Build standalone executable (Windows console app)" ON)

# Set C++ standard
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Options
option(BUILD_PYTHON_MODULE "Build Python module for Jupyter notebooks" ON)
option(BUILD_BLENDER_MODULE "Build as Blender Python module" OFF)
option(BUILD_TESTS "Build test suite" OFF)
option(BUILD_DOCS "Build documentation" OFF)
option(USE_NATIVE_ARCH "Build with -march=native" ON)
option(USE_FAST_MATH "Enable fast math optimizations" ON)
option(ASTRORAY_ENABLE_CUDA "Enable CUDA GPU acceleration" ON)
option(ASTRORAY_ENABLE_OIDN "Enable Intel Open Image Denoise integration when available" ON)
# pkg70 — NVIDIA OptiX AI denoiser. AUTO = enable when SDK headers are
# located by cmake/FindOptiX.cmake; ON = error when not found; OFF = skip.
set(ASTRORAY_ENABLE_OPTIX "AUTO" CACHE STRING
    "Enable NVIDIA OptiX AI denoiser pass (ON/OFF/AUTO). AUTO requires CUDA + the OptiX SDK headers")
set_property(CACHE ASTRORAY_ENABLE_OPTIX PROPERTY STRINGS "AUTO" "ON" "OFF")
list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")
option(ASTRORAY_ENABLE_PYTEST_TARGET "Add an astroray_pytest convenience target" ON)
# Disable OpenMP entirely. Needed when building the Python module (.pyd) for
# distribution as a Blender addon: MinGW's libgomp deadlocks during module
# init when loaded into Blender's MSVC-built Python host. Standalone pytest
# usage is unaffected because we always build a fresh target; the addon
# packager sets this to ON.
option(ASTRORAY_DISABLE_OPENMP "Disable OpenMP (needed for MinGW .pyd in Blender)" OFF)

# ---------------------------------------------------------------------------
# Python hint bridge: -DPYTHON_EXECUTABLE (legacy/CI) → Python3_EXECUTABLE
# find_package(Python3) reads Python3_EXECUTABLE, not PYTHON_EXECUTABLE.
# ---------------------------------------------------------------------------
if(PYTHON_EXECUTABLE AND NOT Python3_EXECUTABLE)
    set(Python3_EXECUTABLE "${PYTHON_EXECUTABLE}" CACHE FILEPATH "" FORCE)
endif()

# ---------------------------------------------------------------------------
# CUDA detection (graceful fallback when toolkit not installed)
# ---------------------------------------------------------------------------
if(ASTRORAY_ENABLE_CUDA)
    include(CheckLanguage)
    check_language(CUDA)
    if(CMAKE_CUDA_COMPILER)
        enable_language(CUDA)
        find_package(CUDAToolkit QUIET)
        if(CUDAToolkit_FOUND)
            # Turing (75), Ampere (86), Ada Lovelace (89 — also runs on Blackwell via forward compat)
            # sm_120 (Blackwell) requires CUDA 12.8+; CUDA 12.6 targets up to sm_89
            set(CMAKE_CUDA_ARCHITECTURES "75;86;89")
            set(ASTRORAY_CUDA_FOUND TRUE)
            message(STATUS "CUDA found: ${CMAKE_CUDA_COMPILER}")
        else()
            set(ASTRORAY_CUDA_FOUND FALSE)
            message(STATUS "CUDAToolkit not found — GPU acceleration disabled")
        endif()
    else()
        set(ASTRORAY_CUDA_FOUND FALSE)
        message(STATUS "CUDA not found — GPU acceleration disabled")
    endif()
else()
    set(ASTRORAY_CUDA_FOUND FALSE)
    message(STATUS "CUDA disabled via ASTRORAY_ENABLE_CUDA=OFF")
endif()

# ---------------------------------------------------------------------------
# Optional Intel Open Image Denoise (OIDN)
# ---------------------------------------------------------------------------
set(ASTRORAY_OIDN_FOUND FALSE)
set(ASTRORAY_OIDN_TARGET "")
if(ASTRORAY_ENABLE_OIDN)
    # 1. Honour caller-supplied hints: -DOpenImageDenoise_DIR=... or OIDN_DIR env var.
    if(NOT OpenImageDenoise_DIR AND DEFINED ENV{OIDN_DIR})
        file(GLOB _oidn_env_cmake "$ENV{OIDN_DIR}/lib/cmake/OpenImageDenoise*")
        if(_oidn_env_cmake)
            list(GET _oidn_env_cmake 0 OpenImageDenoise_DIR)
        else()
            set(OpenImageDenoise_DIR "$ENV{OIDN_DIR}")
        endif()
    endif()

    # 2. Probe well-known Windows install locations (e.g. C:/oidn from the
    #    RenderKit prebuilt zip, or Intel oneAPI install paths).
    if(WIN32 AND NOT OpenImageDenoise_DIR)
        foreach(_oidn_root
                "C:/oidn"
                "C:/Program Files/Intel/OpenImageDenoise"
                "C:/Program Files/OpenImageDenoise")
            file(GLOB _oidn_cmake_dirs "${_oidn_root}/lib/cmake/OpenImageDenoise*")
            if(_oidn_cmake_dirs)
                list(GET _oidn_cmake_dirs 0 OpenImageDenoise_DIR)
                break()
            endif()
        endforeach()
    endif()

    find_package(OpenImageDenoise CONFIG QUIET)

    # 3. FetchContent fallback — download the OIDN 2.4.1 Windows x64 prebuilt
    #    zip when the library is not installed locally.  Only attempted on
    #    Windows because the prebuilt packages are platform-specific.
    #    pkg68: bumped 2.3.3 → 2.4.1 (latest release with CUDA backend support).
    if(NOT OpenImageDenoise_FOUND AND WIN32)
        message(STATUS "OIDN not found locally — fetching prebuilt binary (v2.4.1)…")
        include(FetchContent)
        FetchContent_Declare(oidn_prebuilt
            URL      "https://github.com/RenderKit/oidn/releases/download/v2.4.1/oidn-2.4.1.x64.windows.zip"
            DOWNLOAD_EXTRACT_TIMESTAMP TRUE
        )
        # The prebuilt zip contains no CMakeLists.txt, so FetchContent_MakeAvailable
        # would fail trying to add_subdirectory it.  Use FetchContent_Populate
        # (populate-only).  CMP0169 deprecated the bare FetchContent_Populate()
        # call in CMake 3.30 — silence the policy warning while keeping the old
        # behaviour so we can point find_package at the extracted tree.
        cmake_policy(PUSH)
        if(POLICY CMP0169)
            cmake_policy(SET CMP0169 OLD)
        endif()
        FetchContent_GetProperties(oidn_prebuilt)
        if(NOT oidn_prebuilt_POPULATED)
            FetchContent_Populate(oidn_prebuilt)
        endif()
        cmake_policy(POP)

        file(GLOB _fetched_cmake_dirs "${oidn_prebuilt_SOURCE_DIR}/lib/cmake/OpenImageDenoise*")
        if(_fetched_cmake_dirs)
            list(GET _fetched_cmake_dirs 0 OpenImageDenoise_DIR)
            find_package(OpenImageDenoise CONFIG QUIET)
        endif()
    endif()

    if(OpenImageDenoise_FOUND)
        if(TARGET OpenImageDenoise::OpenImageDenoise)
            set(ASTRORAY_OIDN_TARGET OpenImageDenoise::OpenImageDenoise)
            set(ASTRORAY_OIDN_FOUND TRUE)
        elseif(TARGET OpenImageDenoise)
            set(ASTRORAY_OIDN_TARGET OpenImageDenoise)
            set(ASTRORAY_OIDN_FOUND TRUE)
        endif()
    endif()

    if(ASTRORAY_OIDN_FOUND)
        message(STATUS "OIDN found: ${OpenImageDenoise_VERSION}")
    else()
        message(STATUS "OIDN not found — denoiser pass will be a no-op")
    endif()
endif()

# ---------------------------------------------------------------------------
# pkg70 — Optional NVIDIA OptiX AI denoiser
# Headers are NOT bundled (NVIDIA SDK license forbids redistribution).
# We locate optix.h via cmake/FindOptiX.cmake (OPTIX_INSTALL_DIR env or
# default Windows path C:\ProgramData\NVIDIA Corporation\OptiX SDK 8.x).
# OptiX needs CUDA: with no CUDA toolkit the option is silently disabled.
# ---------------------------------------------------------------------------
set(ASTRORAY_OPTIX_FOUND FALSE)
if(NOT ASTRORAY_ENABLE_OPTIX STREQUAL "OFF")
    if(ASTRORAY_CUDA_FOUND)
        find_package(OptiX QUIET)
        if(OptiX_FOUND)
            set(ASTRORAY_OPTIX_FOUND TRUE)
            message(STATUS "OptiX found: ${OptiX_VERSION} (${OptiX_INCLUDE_DIR})")
        elseif(ASTRORAY_ENABLE_OPTIX STREQUAL "ON")
            message(FATAL_ERROR
                "ASTRORAY_ENABLE_OPTIX=ON but OptiX SDK was not found. "
                "Install the OptiX 8.x SDK and set OPTIX_INSTALL_DIR.")
        else()
            message(STATUS "OptiX SDK not found — OptiX denoiser disabled")
            message(STATUS "  (Install OptiX 8.x from https://developer.nvidia.com/designworks/optix/download")
            message(STATUS "   to default path 'C:/ProgramData/NVIDIA Corporation/OptiX SDK 8.x.x/' or set OPTIX_INSTALL_DIR.")
            message(STATUS "   Without OptiX, the denoiser falls back to OIDN. See docs/QUICKSTART.md for details.)")
        endif()
    elseif(ASTRORAY_ENABLE_OPTIX STREQUAL "ON")
        message(FATAL_ERROR
            "ASTRORAY_ENABLE_OPTIX=ON but CUDA was not found. "
            "OptiX requires CUDA.")
    else()
        message(STATUS "CUDA disabled/missing — OptiX denoiser disabled")
    endif()
endif()

# ---------------------------------------------------------------------------
# pkg47 — Optional FITS I/O (requires cfitsio)
# cfitsio is a NASA/HEASARC public-domain library for reading FITS files.
# System dependency; not vendored. Install via vcpkg (Windows) or package
# manager (Linux): vcpkg install cfitsio  or  apt install libcfitsio-dev
# ---------------------------------------------------------------------------
option(ASTRORAY_ENABLE_FITS "Enable FITS I/O (requires cfitsio)" OFF)

if(ASTRORAY_ENABLE_FITS)
    # vcpkg provides cfitsio::cfitsio; system installs may use pkg-config
    find_package(cfitsio CONFIG QUIET)
    if(NOT cfitsio_FOUND)
        find_package(PkgConfig QUIET)
        if(PkgConfig_FOUND)
            pkg_check_modules(cfitsio IMPORTED_TARGET cfitsio)
            if(cfitsio_FOUND)
                add_library(cfitsio::cfitsio ALIAS PkgConfig::cfitsio)
            endif()
        endif()
    endif()

    if(cfitsio_FOUND)
        message(STATUS "FITS I/O enabled (cfitsio found)")
    else()
        message(WARNING
            "ASTRORAY_ENABLE_FITS=ON but cfitsio not found. "
            "Install via: vcpkg install cfitsio  (Windows) or  apt install libcfitsio-dev  (Linux). "
            "FITS plugins will be skipped.")
    endif()
endif()

# ---------------------------------------------------------------------------
# pkg87a — Optional OpenEXR (for Cryptomatte EXR write)
# OpenEXR is ILM's HDR image library (BSD-3). Install via vcpkg (Windows) or
# package manager (Linux): vcpkg install openexr  or  apt install libopenexr-dev
# Graceful degradation: Cryptomatte infrastructure builds without it; EXR write
# stubs to runtime error until OpenEXR is available.
# ---------------------------------------------------------------------------
find_package(OpenEXR CONFIG QUIET)
if(OpenEXR_FOUND)
    message(STATUS "OpenEXR found — Cryptomatte EXR write enabled")
else()
    message(STATUS "OpenEXR not found — Cryptomatte EXR write will throw runtime error")
    message(STATUS "  (Install via: vcpkg install openexr  or  apt install libopenexr-dev)")
endif()

# Compiler flags for optimization
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    # Base optimization flags
    add_compile_options(-Wall -Wextra -O3)

    # Force stack realignment at every function entry so SSE/AVX instructions work
    # correctly in OpenMP worker threads (MinGW does not guarantee 16-byte alignment).
    add_compile_options(-mstackrealign)

    # Architecture-specific optimizations
    if(USE_NATIVE_ARCH)
        add_compile_options(-march=native)
    else()
        # Minimum SIMD requirements
        add_compile_options(-msse4.1 -mavx2)
    endif()

    # Fast math (trades precision for speed)
    # -fno-finite-math-only is added unconditionally so that std::isfinite / isnan
    # remain correct even when fast-math is enabled. Without it, -ffinite-math-only
    # (implied by -ffast-math) causes the compiler to assume all values are finite,
    # turning isfinite() into a constant true and letting NaN propagate undetected
    # into BVH traversal (crash). All other fast-math opts are kept for speed.
    if(USE_FAST_MATH)
        add_compile_options(-ffast-math)
    endif()
    add_compile_options(-fno-finite-math-only)

    # OpenMP for parallel rendering (suppressed for the Blender .pyd build —
    # libgomp deadlocks inside Blender's host Python on Windows/MinGW)
    if(NOT ASTRORAY_DISABLE_OPENMP)
        find_package(OpenMP REQUIRED)
        if(OpenMP_CXX_FOUND)
            set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} ${OpenMP_CXX_FLAGS}")
        endif()
    else()
        message(STATUS "OpenMP disabled via ASTRORAY_DISABLE_OPENMP=ON")
        set(OpenMP_CXX_FOUND FALSE)
    endif()

elseif(MSVC)
    # Only apply MSVC flags to C/CXX — nvcc rejects bare /flag syntax
    add_compile_options($<$<COMPILE_LANGUAGE:CXX>:/W4>)
    add_compile_options($<$<COMPILE_LANGUAGE:C>:/W4>)
    # Only apply optimizations in Release builds
    add_compile_options($<$<AND:$<COMPILE_LANGUAGE:CXX>,$<CONFIG:Release>>:/O2>)
    add_compile_options($<$<AND:$<COMPILE_LANGUAGE:CXX>,$<CONFIG:Release>>:/arch:AVX2>)
    if(NOT ASTRORAY_DISABLE_OPENMP)
        add_compile_options($<$<COMPILE_LANGUAGE:CXX>:/openmp>)
        add_compile_options($<$<COMPILE_LANGUAGE:C>:/openmp>)
    endif()

    if(USE_FAST_MATH)
        add_compile_options($<$<COMPILE_LANGUAGE:CXX>:/fp:fast>)
        add_compile_options($<$<COMPILE_LANGUAGE:C>:/fp:fast>)
    endif()
endif()

# Include directories
set(INCLUDE_DIR ${CMAKE_CURRENT_SOURCE_DIR}/include)
file(GLOB_RECURSE HEADERS ${INCLUDE_DIR}/*.h)

# Plugin sources — collected by glob; pkg02+ populates plugins/*.cpp
# pkg47: FITS loader excluded from glob; added conditionally below if cfitsio found
file(GLOB_RECURSE ASTRORAY_PLUGIN_SOURCES CONFIGURE_DEPENDS
     "${CMAKE_SOURCE_DIR}/plugins/*.cpp")
list(FILTER ASTRORAY_PLUGIN_SOURCES EXCLUDE REGEX "plugins/data/fits_loader\\.cpp$")

# Create header-only library for core raytracer
add_library(raytracer_core INTERFACE)
target_include_directories(raytracer_core INTERFACE ${INCLUDE_DIR})

# Plugin object library — OBJECT (not STATIC) ensures static initializers from
# ASTRORAY_REGISTER_* macros are not dead-stripped by the linker.
if(ASTRORAY_PLUGIN_SOURCES)
    add_library(astroray_plugins OBJECT ${ASTRORAY_PLUGIN_SOURCES})
    target_link_libraries(astroray_plugins PUBLIC raytracer_core)
    set_target_properties(astroray_plugins PROPERTIES
        CXX_STANDARD 17
        CXX_STANDARD_REQUIRED ON
        POSITION_INDEPENDENT_CODE ON
    )
    if(ASTRORAY_OIDN_FOUND)
        target_link_libraries(astroray_plugins PUBLIC ${ASTRORAY_OIDN_TARGET})
        target_compile_definitions(astroray_plugins PUBLIC ASTRORAY_OIDN_ENABLED)
    endif()
    if(ASTRORAY_OPTIX_FOUND)
        # OptiX is a header-only host API at compile time; the function
        # table is loaded at runtime via optixInit() from optix_stubs.h.
        # We do still need the CUDA runtime headers + CUDA::cudart to call
        # cudaMalloc/cudaMemcpy from the plugin.
        target_include_directories(astroray_plugins PUBLIC
            ${OptiX_INCLUDE_DIRS}
            ${CUDAToolkit_INCLUDE_DIRS}
        )
        target_compile_definitions(astroray_plugins PUBLIC ASTRORAY_OPTIX_ENABLED)
        if(TARGET CUDA::cudart)
            target_link_libraries(astroray_plugins PUBLIC CUDA::cudart)
        endif()
    endif()
    # pkg47: FITS I/O conditionally included if cfitsio found
    if(ASTRORAY_ENABLE_FITS AND cfitsio_FOUND)
        target_sources(astroray_plugins PRIVATE
            "${CMAKE_SOURCE_DIR}/plugins/data/fits_loader.cpp"
            "${CMAKE_SOURCE_DIR}/src/io/fits_io.cpp"
        )
        target_link_libraries(astroray_plugins PUBLIC cfitsio::cfitsio)
        target_compile_definitions(astroray_plugins PUBLIC ASTRORAY_FITS_ENABLED)
    endif()
    # pkg87a: OpenEXR EXR writer conditionally included if OpenEXR found
    if(OpenEXR_FOUND)
        target_sources(astroray_core_impl PRIVATE
            "${CMAKE_SOURCE_DIR}/src/io/exr_writer.cpp"
        )
        target_link_libraries(astroray_core_impl PUBLIC OpenEXR::OpenEXR)
        target_compile_definitions(astroray_core_impl PUBLIC ASTRORAY_EXR_ENABLED)
    endif()
endif()

# Source files
set(SOURCES
    apps/main.cpp
)

# Compile stb_image_write_impl.c as C++ to avoid linking issues
set_source_files_properties(src/stb_image_write_impl.c PROPERTIES LANGUAGE CXX)
add_library(stb_image_write_lib STATIC src/stb_image_write_impl.c)
target_include_directories(stb_image_write_lib PRIVATE ${CMAKE_SOURCE_DIR}/include)
set_target_properties(stb_image_write_lib PROPERTIES
    CXX_STANDARD 17
    CXX_STANDARD_REQUIRED ON
    POSITION_INDEPENDENT_CODE ON
)

# stb_image implementation (STB_IMAGE_IMPLEMENTATION defined once here)
add_library(stb_impl STATIC src/stb_impl.cpp)
target_include_directories(stb_impl PRIVATE ${CMAKE_SOURCE_DIR}/include)
set_target_properties(stb_impl PROPERTIES
    CXX_STANDARD 17
    CXX_STANDARD_REQUIRED ON
    POSITION_INDEPENDENT_CODE ON
)

# ---------------------------------------------------------------------------
# Pillar 2 spectral core (pkg10). STATIC library so it can be linked into
# raytracer_standalone, the Python module, the Blender module, and
# astroray_plugins without duplicating translation units. ASTRORAY_DATA_DIR
# points the Jakob-Hanika LUT loader at data/ in the source tree for
# in-tree test runs; installed builds override via an env var.
# ---------------------------------------------------------------------------
add_library(astroray_core_impl STATIC
    src/spectrum.cpp
    src/default_integrator.cpp
    src/energy_compensation.cpp
    src/material_closure.cpp
    src/spectral_profile.cpp
    src/emission_spectrum.cpp
    src/light.cpp
    src/lights/point_light.cpp
    src/lights/spot_light.cpp
    src/lights/distant_light.cpp
    src/lights/area_light.cpp
    src/lights/background_light.cpp
    # pkg87a — Cryptomatte infrastructure
    src/util/murmurhash3.cpp
    src/util/cryptomatte.cpp
    # pkg86 — Light Tree (Conty 2018 + Cycles, CPU)
    src/light_tree.cpp
    src/light_sampler.cpp
    src/light_list.cpp
)

# pkg55 Phase B' — CPU wavefront reference oracle + driver (Session 2b/2c).
# Glob auto-picks up files as 2b/2c lands them. Session 2a only ships the
# wavefront_snapshot.h header (no .cpp yet); the if-guard avoids adding an
# empty source list to the target. See:
#   - .astroray_plan/packages/pkg55-wavefront-soa-refactor.md §"Phase B'"
#   - .astroray_plan/docs/pkg55-B-cpu-reference-design.md §10
file(GLOB ASTRORAY_CPU_WAVEFRONT_SOURCES CONFIGURE_DEPENDS
     "${CMAKE_CURRENT_SOURCE_DIR}/src/cpu/wavefront/*.cpp")
if(ASTRORAY_CPU_WAVEFRONT_SOURCES)
    target_sources(astroray_core_impl PRIVATE ${ASTRORAY_CPU_WAVEFRONT_SOURCES})
    message(STATUS "pkg55-B': CPU wavefront sources: ${ASTRORAY_CPU_WAVEFRONT_SOURCES}")
    # pkg55-B' Session 2c — DEFENSIVE FP-contraction guard for scaffold TUs.
    #
    # NOT the bit-identity mechanism. Bit-identity is achieved STRUCTURALLY
    # by the shared per-bounce kernel (src/cpu/wavefront/path_kernel.{h,cpp}):
    # reference_pt_wavefront AND the cpu_wavefront driver call the EXACT SAME
    # compiled advance_one_bounce()/init_path() over carried live state, so
    # the snapshot streams are bit-identical by construction.
    #
    # This flag is a belt-and-braces guard recommended by both senior reviews
    # (architect PR #296 + Codex, 2026-05-15): -ffast-math may fuse identical
    # source into FMA differently across inlining contexts; -ffp-contract=off
    # on the scaffold TUs removes that as a confound and documents the FP-env
    # precondition (SSE2, consistent rounding, no x87 80-bit intermediates).
    # It is a guard, not the fix — if the shared kernel were duplicated this
    # flag would NOT save bit-identity.
    #
    # Scaffold-only: the glob is src/cpu/wavefront/*.cpp ONLY. Production TUs
    # keep -ffast-math UNCHANGED — production codegen is byte-identical to
    # origin/main (verified: git diff origin/main excluding scaffold is empty).
    # Owner decision 2026-05-15 (pkg55-bprime-session2c): scaffold guard only.
    # Laine 2013 §3, PBRT-v4 src/pbrt/wavefront/integrator.cpp.
    if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
        set_source_files_properties(${ASTRORAY_CPU_WAVEFRONT_SOURCES}
            PROPERTIES COMPILE_FLAGS "-ffp-contract=off")
    elseif(MSVC)
        set_source_files_properties(${ASTRORAY_CPU_WAVEFRONT_SOURCES}
            PROPERTIES COMPILE_FLAGS "/fp:precise")
    endif()
endif()
target_include_directories(astroray_core_impl
    PUBLIC  ${INCLUDE_DIR}
    PRIVATE ${CMAKE_SOURCE_DIR})
target_compile_definitions(astroray_core_impl
    PRIVATE ASTRORAY_DATA_DIR="${CMAKE_SOURCE_DIR}/data")
set_target_properties(astroray_core_impl PROPERTIES
    CXX_STANDARD 17
    CXX_STANDARD_REQUIRED ON
    POSITION_INDEPENDENT_CODE ON
)
if(TARGET astroray_plugins)
    target_link_libraries(astroray_plugins PUBLIC astroray_core_impl)
endif()

# ---------------------------------------------------------------------------
# CUDA static library (compiled by nvcc, exposes pure-C++ CUDARenderer)
# ---------------------------------------------------------------------------
# pkg55-B' Session N+3 — CUDA wavefront (spectral + PCG32).
# Phase A.1's curandState + RGB structure is REPLACED.
option(ASTRORAY_WAVEFRONT_CUDA_N3
    "Build the Session N+3 CUDA wavefront (stage_init spectral + PCG32) [pkg55-B']."
    ON)

if(ASTRORAY_CUDA_FOUND)
    set(ASTRORAY_CUDA_SOURCES
        src/gpu/cuda_renderer.cu
        src/gpu/path_trace_kernel.cu
        src/gpu/multiwavelength_kernel.cu
        src/gpu/scene_upload.cu
        src/gpu/pkg64_sms_probe.cu
    )
    if(ASTRORAY_WAVEFRONT_CUDA_N3)
        list(APPEND ASTRORAY_CUDA_SOURCES
            src/gpu/wavefront/wavefront_state.cu
            src/gpu/wavefront/stage_init.cu
            src/gpu/wavefront/gpu_wavefront_snapshot.cu
        )
        message(STATUS "pkg55-B' Session N+3: CUDA wavefront stage_init (spectral + PCG32)")
    endif()
    add_library(astroray_cuda STATIC ${ASTRORAY_CUDA_SOURCES})
    if(ASTRORAY_WAVEFRONT_CUDA_N3)
        target_compile_definitions(astroray_cuda PUBLIC ASTRORAY_WAVEFRONT_CUDA_N3)
    endif()
    target_include_directories(astroray_cuda
        PUBLIC  ${CMAKE_SOURCE_DIR}/include
        PRIVATE ${CMAKE_SOURCE_DIR})  # for data/spectra/cie_cmf.inc (pkg54b)
    target_compile_options(astroray_cuda PRIVATE
        $<$<COMPILE_LANGUAGE:CUDA>:--extended-lambda --expt-relaxed-constexpr -O3>
    )
    set_target_properties(astroray_cuda PROPERTIES
        CUDA_SEPARABLE_COMPILATION ON
        POSITION_INDEPENDENT_CODE ON
        CUDA_RESOLVE_DEVICE_SYMBOLS ON
        CXX_STANDARD 17
        CUDA_STANDARD 17
    )
    # On Windows with MSVC+NMake, nvcc rejects the /Fd PDB flag injected by CMake.
    # Suppress debug-info generation for CUDA objects to avoid this.
    if(MSVC)
        string(REPLACE "/Zi" "" CMAKE_CUDA_FLAGS_DEBUG "${CMAKE_CUDA_FLAGS_DEBUG}")
        string(REPLACE "/ZI" "" CMAKE_CUDA_FLAGS_DEBUG "${CMAKE_CUDA_FLAGS_DEBUG}")
        # Remove /Fd (PDB tracking) from flags passed to nvcc
        set_property(TARGET astroray_cuda PROPERTY CUDA_FLAGS
            "--extended-lambda --expt-relaxed-constexpr -O3")
    endif()
    # pkg55-B' Session N+3: PCG32 RNG (no cuRAND needed for wavefront).
    # The megakernel still uses cuRAND; only link it when building megakernel.
    if(NOT ASTRORAY_WAVEFRONT_CUDA_N3)
        if(TARGET CUDA::curand)
            target_link_libraries(astroray_cuda PRIVATE CUDA::curand)
        elseif(TARGET CUDA::curand_static)
            target_link_libraries(astroray_cuda PRIVATE CUDA::curand_static)
        else()
            find_library(CURAND_LIB curand
                HINTS
                    "${CUDAToolkit_LIBRARY_DIR}"
                    "${CUDAToolkit_LIBRARY_ROOT}/lib"
                    "${CUDAToolkit_LIBRARY_ROOT}/lib64"
            )
            if(NOT CURAND_LIB)
                message(FATAL_ERROR "CUDA Toolkit found, but cuRAND is missing (no CUDA::curand and curand not found in library path).")
            endif()
            target_link_libraries(astroray_cuda PRIVATE "${CURAND_LIB}")
        endif()
    endif()
endif()

# Standalone executable (always console subsystem)
add_executable(raytracer_standalone ${SOURCES} ${HEADERS})

target_link_libraries(raytracer_standalone PRIVATE
    raytracer_core
    astroray_core_impl
    stb_image_write_lib
    stb_impl
)
if(TARGET astroray_plugins)
    target_link_libraries(raytracer_standalone PRIVATE astroray_plugins)
endif()

if(OpenMP_CXX_FOUND)
    target_link_libraries(raytracer_standalone PRIVATE OpenMP::OpenMP_CXX)
endif()

if(ASTRORAY_CUDA_FOUND)
    target_link_libraries(raytracer_standalone PRIVATE astroray_cuda)
    target_compile_definitions(raytracer_standalone PRIVATE ASTRORAY_CUDA_ENABLED)
endif()
if(ASTRORAY_OPTIX_FOUND)
    target_compile_definitions(raytracer_standalone PRIVATE ASTRORAY_OPTIX_ENABLED)
endif()

# Set output name and configuration-specific properties
set_target_properties(raytracer_standalone PROPERTIES
    OUTPUT_NAME raytracer
    RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin
)

# Ensure consistent output on Windows
if(WIN32)
    set_target_properties(raytracer_standalone PROPERTIES
        VS_DEBUGGER_WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    )
endif()

# Build Python module for Jupyter notebooks
if(BUILD_PYTHON_MODULE)
    # Find Python (Development.Module is sufficient for building a module —
    # we don't need the embed libs).
    find_package(Python3 COMPONENTS Interpreter Development.Module REQUIRED)

    # Force pybind11 to use the Python3 we just found via the new FindPython
    # module, instead of its default legacy FindPythonInterp/FindPythonLibs
    # which ignores Python3_EXECUTABLE and walks PATH. Without this, pybind11
    # will grab whichever python is first on PATH and build for the wrong ABI.
    set(PYBIND11_FINDPYTHON ON CACHE BOOL "Use new FindPython in pybind11" FORCE)

    # Try to find pybind11
    find_package(pybind11 CONFIG)
    if(NOT pybind11_FOUND)
        message(STATUS "pybind11 not found, fetching from GitHub...")
        include(FetchContent)
        FetchContent_Declare(
            pybind11
            GIT_REPOSITORY https://github.com/pybind/pybind11.git
            # v2.12+ is required for Python 3.13 support (Blender 5.1 ships 3.13)
            GIT_TAG v2.13.6
        )
        FetchContent_MakeAvailable(pybind11)
    endif()

    # Python module for Jupyter notebooks
    pybind11_add_module(astroray
        module/blender_module.cpp
        ${HEADERS}
    )

    # Rename module to 'astroray' in Python (so it's importable as 'import astroray')
    set_target_properties(astroray PROPERTIES
        OUTPUT_NAME astroray
    )

    target_link_libraries(astroray PRIVATE
        raytracer_core
        astroray_core_impl
        stb_image_write_lib
        stb_impl
    )
    if(TARGET astroray_plugins)
        target_link_libraries(astroray PRIVATE astroray_plugins)
    endif()

    if(OpenMP_CXX_FOUND)
        target_link_libraries(astroray PRIVATE OpenMP::OpenMP_CXX)
    endif()

    if(ASTRORAY_OIDN_FOUND)
        target_link_libraries(astroray PRIVATE ${ASTRORAY_OIDN_TARGET})
        target_compile_definitions(astroray PRIVATE ASTRORAY_OIDN_ENABLED)
    endif()

    # When building with MinGW for distribution as a Blender addon, statically
    # link the GCC runtime so the .pyd doesn't depend on libgcc_s_seh-1.dll /
    # libstdc++-6.dll / libwinpthread-1.dll being on the loader's PATH.
    # Blender's bundled Python search path doesn't include MinGW's bin/ dir,
    # so without this the addon fails with "DLL load failed". OpenMP's libgomp
    # is bundled separately by the build script (it can't be statically linked
    # cleanly with GCC).
    if(WIN32 AND CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
        target_link_options(astroray PRIVATE
            -static-libgcc
            -static-libstdc++
            -Wl,-Bstatic,--whole-archive -lwinpthread -Wl,--no-whole-archive -Wl,-Bdynamic
        )
    endif()

    if(ASTRORAY_CUDA_FOUND)
        target_link_libraries(astroray PRIVATE astroray_cuda)
        target_compile_definitions(astroray PRIVATE ASTRORAY_CUDA_ENABLED)
    endif()

    if(ASTRORAY_OPTIX_FOUND)
        target_compile_definitions(astroray PRIVATE ASTRORAY_OPTIX_ENABLED)
    endif()

    # Set output directory to CMAKE_BINARY_DIR for both Windows and Linux
    # pybind11_add_module automatically handles .pyd on Windows and .so on Linux
    set_target_properties(astroray PROPERTIES
        LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}
        RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}
        OUTPUT_NAME astroray
        # On Windows, ensure the module is built as a shared library
        POSITION_INDEPENDENT_CODE ON
    )

    # pkg92 — Test helpers module (internal utilities, not public API).
    pybind11_add_module(astroray_test_helpers
        module/test_helpers_module.cpp
        ${HEADERS}
    )

    set_target_properties(astroray_test_helpers PROPERTIES
        OUTPUT_NAME astroray_test_helpers
    )

    target_link_libraries(astroray_test_helpers PRIVATE
        raytracer_core
        astroray_core_impl
    )

    set_target_properties(astroray_test_helpers PROPERTIES
        LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}
        RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}
        OUTPUT_NAME astroray_test_helpers
        POSITION_INDEPENDENT_CODE ON
    )
endif()

# Build Blender module if requested
if(BUILD_BLENDER_MODULE)
    # Find Python (Development.Module is sufficient for building a module —
    # we don't need the embed libs).
    find_package(Python3 COMPONENTS Interpreter Development.Module REQUIRED)

    # Force pybind11 to use the Python3 we just found via the new FindPython
    # module, instead of its default legacy FindPythonInterp/FindPythonLibs
    # which ignores Python3_EXECUTABLE and walks PATH. Without this, pybind11
    # will grab whichever python is first on PATH and build for the wrong ABI.
    set(PYBIND11_FINDPYTHON ON CACHE BOOL "Use new FindPython in pybind11" FORCE)

    # Try to find pybind11
    find_package(pybind11 CONFIG)
    if(NOT pybind11_FOUND)
        message(STATUS "pybind11 not found, fetching from GitHub...")
        include(FetchContent)
        FetchContent_Declare(
            pybind11
            GIT_REPOSITORY https://github.com/pybind/pybind11.git
            # v2.12+ is required for Python 3.13 support (Blender 5.1 ships 3.13)
            GIT_TAG v2.13.6
        )
        FetchContent_MakeAvailable(pybind11)
    endif()

    # Python module
    pybind11_add_module(raytracer_blender
        module/blender_module.cpp
        ${HEADERS}
    )

    target_link_libraries(raytracer_blender PRIVATE
        raytracer_core
        astroray_core_impl
        stb_impl
    )

    if(OpenMP_CXX_FOUND)
        target_link_libraries(raytracer_blender PRIVATE OpenMP::OpenMP_CXX)
    endif()

    if(ASTRORAY_OIDN_FOUND)
        target_link_libraries(raytracer_blender PRIVATE ${ASTRORAY_OIDN_TARGET})
        target_compile_definitions(raytracer_blender PRIVATE ASTRORAY_OIDN_ENABLED)
    endif()

    if(ASTRORAY_OPTIX_FOUND)
        target_compile_definitions(raytracer_blender PRIVATE ASTRORAY_OPTIX_ENABLED)
    endif()

    # Set properties for Python module
    set_target_properties(raytracer_blender PROPERTIES
        LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/blender_addon
    )

    # Copy Python files to addon directory
    configure_file(
        ${CMAKE_CURRENT_SOURCE_DIR}/blender_addon/__init__.py
        ${CMAKE_BINARY_DIR}/blender_addon/__init__.py
        COPYONLY
    )

    # Installation for Blender 5.1 extensions directory.
    # Blender 5.x uses `extensions/user_default/` instead of `scripts/addons/`
    # for manifest-based extensions (blender_manifest.toml).
    if(WIN32)
        set(BLENDER_ADDON_DIR "$ENV{APPDATA}/Blender Foundation/Blender/5.1/extensions/user_default/astroray")
    elseif(APPLE)
        set(BLENDER_ADDON_DIR "$ENV{HOME}/Library/Application Support/Blender/5.1/extensions/user_default/astroray")
    else()
        set(BLENDER_ADDON_DIR "$ENV{HOME}/.config/blender/5.1/extensions/user_default/astroray")
    endif()

    install(TARGETS raytracer_blender
        LIBRARY DESTINATION ${BLENDER_ADDON_DIR}
    )

    install(FILES
        blender_addon/__init__.py
        blender_addon/blender_manifest.toml
        DESTINATION ${BLENDER_ADDON_DIR}
    )
endif()

# Install standalone executable
install(TARGETS raytracer_standalone
    RUNTIME DESTINATION bin
)

# Install headers
install(DIRECTORY include/
    DESTINATION include/raytracer
    FILES_MATCHING PATTERN "*.h"
)

# Install spectral data files (Jakob-Hanika LUT, CIE CMF, D65 SPD).
# The runtime also searches for these via the ASTRORAY_DATA_DIR env var,
# which installed deployments should point at share/astroray/.
install(DIRECTORY data/spectra/
    DESTINATION share/astroray/spectra
    FILES_MATCHING
        PATTERN "*.coeff"
        PATTERN "*.inc"
        PATTERN "*.csv"
)

install(DIRECTORY data/disney_compensation/
    DESTINATION share/astroray/disney_compensation
    FILES_MATCHING
        PATTERN "*.bin"
        PATTERN "README.md"
)

# Note: Tests are run via pytest, not CMake.
# The tests directory contains Python test files (pytest.ini, tests/*.py)
# that are automatically discovered when running `pytest tests/`.

# ---------------------------------------------------------------------------
# pkg25-pkg27 — tiny-cuda-nn / NRC targets (opt-in)
# Enable with -DASTRORAY_TINY_CUDA_NN=ON. Requires CUDA. No production
# targets depend on tiny-cuda-nn unless this flag is explicitly enabled.
# ---------------------------------------------------------------------------
option(ASTRORAY_TINY_CUDA_NN "Build tiny-cuda-nn smoke harness and NRC neural backend" OFF)
if(ASTRORAY_TINY_CUDA_NN)
    if(NOT ASTRORAY_CUDA_FOUND)
        message(WARNING "ASTRORAY_TINY_CUDA_NN=ON but CUDA not found — skipping")
    else()
        include(FetchContent)
        FetchContent_Declare(
            tiny-cuda-nn
            GIT_REPOSITORY https://github.com/NVlabs/tiny-cuda-nn.git
            GIT_TAG        master
            GIT_SHALLOW    TRUE
        )
        # Disable benchmarks and examples so only the core library is compiled.
        set(TCNN_BUILD_BENCHMARK OFF CACHE BOOL "" FORCE)
        set(TCNN_BUILD_EXAMPLES  OFF CACHE BOOL "" FORCE)
        FetchContent_MakeAvailable(tiny-cuda-nn)

        # pkg27 — reusable NeuralCache backend. Production targets link this
        # only when ASTRORAY_TINY_CUDA_NN=ON; default builds keep the
        # neural-cache integrator registered with its path-tracer fallback.
        add_library(astroray_neural_cache STATIC src/neural_cache.cu)
        target_link_libraries(astroray_neural_cache PUBLIC
            tiny-cuda-nn
            raytracer_core
        )
        target_include_directories(astroray_neural_cache PUBLIC
            ${CMAKE_SOURCE_DIR}/include
            ${CMAKE_SOURCE_DIR}/src
            ${tiny-cuda-nn_SOURCE_DIR}/include
            ${tiny-cuda-nn_SOURCE_DIR}/dependencies
        )
        set_target_properties(astroray_neural_cache PROPERTIES
            CUDA_ARCHITECTURES         "89"
            CUDA_SEPARABLE_COMPILATION ON
            CUDA_RESOLVE_DEVICE_SYMBOLS ON
            POSITION_INDEPENDENT_CODE  ON
            CUDA_STANDARD              17
            CXX_STANDARD               17
            CXX_STANDARD_REQUIRED      ON
        )

        if(TARGET astroray_plugins)
            target_include_directories(astroray_plugins PUBLIC
                ${CMAKE_SOURCE_DIR}/src
                ${tiny-cuda-nn_SOURCE_DIR}/include
                ${tiny-cuda-nn_SOURCE_DIR}/dependencies
            )
            target_compile_definitions(astroray_plugins PUBLIC
                ASTRORAY_NEURAL_CACHE_ENABLED
            )
            target_link_libraries(astroray_plugins PUBLIC astroray_neural_cache)
        endif()

        foreach(_astroray_target IN ITEMS raytracer_standalone astroray raytracer_blender)
            if(TARGET ${_astroray_target})
                target_link_libraries(${_astroray_target} PRIVATE astroray_neural_cache)
                target_compile_definitions(${_astroray_target} PRIVATE
                    ASTRORAY_NEURAL_CACHE_ENABLED
                )
            endif()
        endforeach()

        add_executable(tcnn_smoke scripts/cuda/tiny_cuda_nn_smoke.cu)
        target_link_libraries(tcnn_smoke PRIVATE tiny-cuda-nn)
        # FetchContent doesn't propagate tcnn's include path via INTERFACE_INCLUDE_DIRECTORIES;
        # add them explicitly so nvcc can find <tiny-cuda-nn/common.h>.
        target_include_directories(tcnn_smoke PRIVATE
            ${tiny-cuda-nn_SOURCE_DIR}/include
            ${tiny-cuda-nn_SOURCE_DIR}/dependencies
        )
        set_target_properties(tcnn_smoke PROPERTIES
            CUDA_ARCHITECTURES         "89"
            CUDA_SEPARABLE_COMPILATION ON
            RUNTIME_OUTPUT_DIRECTORY   ${CMAKE_BINARY_DIR}/bin
        )
        message(STATUS "tiny-cuda-nn smoke target: tcnn_smoke")

        # pkg26 — NRC prototype harness.
        # Renders 50 frames of a Cornell box using NeuralCache for secondary bounces.
        # Links the same NeuralCache backend promoted by pkg27.
        # No production targets (raytracer, astroray) depend on this.
        add_executable(nrc_smoke_render
            scripts/cuda/nrc_smoke_render.cu
        )
        target_link_libraries(nrc_smoke_render PRIVATE
            astroray_neural_cache
            astroray_core_impl    # SampledSpectrum, Jakob-Hanika LUT (via raytracer.h)
            stb_impl              # stb_image (via raytracer.h includes)
        )
        if(TARGET astroray_plugins)
            target_link_libraries(nrc_smoke_render PRIVATE astroray_plugins)
        endif()
        target_include_directories(nrc_smoke_render PRIVATE
            ${CMAKE_SOURCE_DIR}/include
            ${CMAKE_SOURCE_DIR}/src
            ${tiny-cuda-nn_SOURCE_DIR}/include
            ${tiny-cuda-nn_SOURCE_DIR}/dependencies
        )
        target_compile_definitions(nrc_smoke_render PRIVATE
            ASTRORAY_DATA_DIR="${CMAKE_SOURCE_DIR}/data"
        )
        set_target_properties(nrc_smoke_render PROPERTIES
            CUDA_ARCHITECTURES         "89"
            CUDA_SEPARABLE_COMPILATION ON
            RUNTIME_OUTPUT_DIRECTORY   ${CMAKE_BINARY_DIR}/bin
        )
        message(STATUS "NRC prototype target: nrc_smoke_render")
    endif()
endif()

# Documentation
if(BUILD_DOCS)
    find_package(Doxygen)
    if(DOXYGEN_FOUND)
        set(DOXYGEN_IN ${CMAKE_CURRENT_SOURCE_DIR}/docs/Doxyfile.in)
        set(DOXYGEN_OUT ${CMAKE_CURRENT_BINARY_DIR}/Doxyfile)
        configure_file(${DOXYGEN_IN} ${DOXYGEN_OUT} @ONLY)
        add_custom_target(docs
            COMMAND ${DOXYGEN_EXECUTABLE} ${DOXYGEN_OUT}
            WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
            COMMENT "Generating API documentation with Doxygen"
            VERBATIM
        )
    endif()
endif()

# ---------------------------------------------------------------------------
# Developer test convenience target
# ---------------------------------------------------------------------------
if(ASTRORAY_ENABLE_PYTEST_TARGET)
    find_package(Python3 COMPONENTS Interpreter QUIET)
    if(Python3_Interpreter_FOUND)
        add_custom_target(astroray_pytest
            COMMAND ${Python3_EXECUTABLE}
                    ${CMAKE_SOURCE_DIR}/scripts/dev/run_tests.py
                    --build-dir ${CMAKE_BINARY_DIR}
                    --temp-dir ${CMAKE_BINARY_DIR}/pytest_tmp
                    -- tests -v --tb=short
            WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
            USES_TERMINAL
            COMMENT "Running Astroray pytest suite against ${CMAKE_BINARY_DIR}"
        )
        foreach(_pytest_dep IN ITEMS raytracer_standalone astroray tcnn_smoke nrc_smoke_render)
            if(TARGET ${_pytest_dep})
                add_dependencies(astroray_pytest ${_pytest_dep})
            endif()
        endforeach()
    else()
        message(STATUS "Python3 interpreter not found - astroray_pytest target disabled")
    endif()
endif()

# Print configuration summary
message(STATUS "")
message(STATUS "===== Configuration Summary =====")
message(STATUS "Build type: ${CMAKE_BUILD_TYPE}")
message(STATUS "C++ standard: ${CMAKE_CXX_STANDARD}")
message(STATUS "Compiler: ${CMAKE_CXX_COMPILER_ID}")
message(STATUS "OpenMP: ${OpenMP_CXX_FOUND}")
message(STATUS "Native arch: ${USE_NATIVE_ARCH}")
message(STATUS "Fast math: ${USE_FAST_MATH}")
message(STATUS "CUDA GPU backend: ${ASTRORAY_CUDA_FOUND}")
message(STATUS "OIDN denoiser: ${ASTRORAY_OIDN_FOUND}")
message(STATUS "OptiX denoiser: ${ASTRORAY_OPTIX_FOUND}")
message(STATUS "Python module: ${BUILD_PYTHON_MODULE}")
if(BUILD_PYTHON_MODULE)
    message(STATUS "  Python: ${Python3_VERSION}")
    message(STATUS "  pybind11: ${pybind11_FOUND}")
endif()
message(STATUS "Blender module: ${BUILD_BLENDER_MODULE}")
if(BUILD_BLENDER_MODULE)
    message(STATUS "  Python: ${Python3_VERSION}")
    message(STATUS "  Install to: ${BLENDER_ADDON_DIR}")
endif()
message(STATUS "Tests: ${BUILD_TESTS}")
message(STATUS "Documentation: ${BUILD_DOCS}")
message(STATUS "================================")
