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

# ---------------------------------------------------------------------------
# CUDA detection (graceful fallback when toolkit not installed)
# ---------------------------------------------------------------------------
if(ASTRORAY_ENABLE_CUDA)
    include(CheckLanguage)
    check_language(CUDA)
    if(CMAKE_CUDA_COMPILER)
        enable_language(CUDA)
        find_package(CUDAToolkit REQUIRED)
        # Turing (75), Ampere (86), Ada Lovelace (89 — also runs on Blackwell via forward compat)
        # sm_120 (Blackwell) requires CUDA 12.8+; CUDA 12.6 targets up to sm_89
        set(CMAKE_CUDA_ARCHITECTURES "75;86;89")
        set(ASTRORAY_CUDA_FOUND TRUE)
        message(STATUS "CUDA found: ${CMAKE_CUDA_COMPILER}")
    else()
        set(ASTRORAY_CUDA_FOUND FALSE)
        message(STATUS "CUDA not found — GPU acceleration disabled")
    endif()
else()
    set(ASTRORAY_CUDA_FOUND FALSE)
    message(STATUS "CUDA disabled via ASTRORAY_ENABLE_CUDA=OFF")
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
    
    # OpenMP for parallel rendering
    find_package(OpenMP REQUIRED)
    if(OpenMP_CXX_FOUND)
        set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} ${OpenMP_CXX_FLAGS}")
    endif()
    
elseif(MSVC)
    # Only apply MSVC flags to C/CXX — nvcc rejects bare /flag syntax
    add_compile_options($<$<COMPILE_LANGUAGE:CXX>:/W4>)
    add_compile_options($<$<COMPILE_LANGUAGE:C>:/W4>)
    # Only apply optimizations in Release builds
    add_compile_options($<$<AND:$<COMPILE_LANGUAGE:CXX>,$<CONFIG:Release>>:/O2>)
    add_compile_options($<$<AND:$<COMPILE_LANGUAGE:CXX>,$<CONFIG:Release>>:/arch:AVX2>)
    add_compile_options($<$<COMPILE_LANGUAGE:CXX>:/openmp>)
    add_compile_options($<$<COMPILE_LANGUAGE:C>:/openmp>)

    if(USE_FAST_MATH)
        add_compile_options($<$<COMPILE_LANGUAGE:CXX>:/fp:fast>)
        add_compile_options($<$<COMPILE_LANGUAGE:C>:/fp:fast>)
    endif()
endif()

# Include directories
set(INCLUDE_DIR ${CMAKE_CURRENT_SOURCE_DIR}/include)
file(GLOB_RECURSE HEADERS ${INCLUDE_DIR}/*.h)

# Create header-only library for core raytracer
add_library(raytracer_core INTERFACE)
target_include_directories(raytracer_core INTERFACE ${INCLUDE_DIR})

# Source files
set(SOURCES
    apps/main.cpp
)

# Compile stb_image_write_impl.c as C++ to avoid linking issues
set_source_files_properties(src/stb_image_write_impl.c PROPERTIES LANGUAGE CXX)
add_library(stb_image_write_lib STATIC src/stb_image_write_impl.c)
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
# CUDA static library (compiled by nvcc, exposes pure-C++ CUDARenderer)
# ---------------------------------------------------------------------------
if(ASTRORAY_CUDA_FOUND)
    add_library(astroray_cuda STATIC
        src/gpu/cuda_renderer.cu
        src/gpu/path_trace_kernel.cu
        src/gpu/scene_upload.cu
    )
    target_include_directories(astroray_cuda PUBLIC ${CMAKE_SOURCE_DIR}/include)
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
    target_link_libraries(astroray_cuda PRIVATE CUDA::curand)
endif()

# Standalone executable
if(WIN32 AND WIN32_STANDALONE)
    # Windows console application
    add_executable(raytracer_standalone WIN32 ${SOURCES} ${HEADERS})
else()
    add_executable(raytracer_standalone ${SOURCES} ${HEADERS})
endif()

target_link_libraries(raytracer_standalone PRIVATE
    raytracer_core
    stb_image_write_lib
    stb_impl
)

if(OpenMP_CXX_FOUND)
    target_link_libraries(raytracer_standalone PRIVATE OpenMP::OpenMP_CXX)
endif()

if(ASTRORAY_CUDA_FOUND)
    target_link_libraries(raytracer_standalone PRIVATE astroray_cuda)
    target_compile_definitions(raytracer_standalone PRIVATE ASTRORAY_CUDA_ENABLED)
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
    # Find Python and pybind11
    find_package(Python3 COMPONENTS Interpreter Development REQUIRED)
    
    # Try to find pybind11
    find_package(pybind11 CONFIG)
    if(NOT pybind11_FOUND)
        message(STATUS "pybind11 not found, fetching from GitHub...")
        include(FetchContent)
        FetchContent_Declare(
            pybind11
            GIT_REPOSITORY https://github.com/pybind/pybind11.git
            GIT_TAG v2.11.1
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
        stb_image_write_lib
        stb_impl
    )

    if(OpenMP_CXX_FOUND)
        target_link_libraries(astroray PRIVATE OpenMP::OpenMP_CXX)
    endif()

    if(ASTRORAY_CUDA_FOUND)
        target_link_libraries(astroray PRIVATE astroray_cuda)
        target_compile_definitions(astroray PRIVATE ASTRORAY_CUDA_ENABLED)
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
endif()

# Build Blender module if requested
if(BUILD_BLENDER_MODULE)
    # Find Python and pybind11
    find_package(Python3 COMPONENTS Interpreter Development REQUIRED)
    
    # Try to find pybind11
    find_package(pybind11 CONFIG)
    if(NOT pybind11_FOUND)
        message(STATUS "pybind11 not found, fetching from GitHub...")
        include(FetchContent)
        FetchContent_Declare(
            pybind11
            GIT_REPOSITORY https://github.com/pybind/pybind11.git
            GIT_TAG v2.11.1
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
        stb_impl
    )
    
    if(OpenMP_CXX_FOUND)
        target_link_libraries(raytracer_blender PRIVATE OpenMP::OpenMP_CXX)
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
    
    # Installation for Blender addons directory
    if(WIN32)
        set(BLENDER_ADDON_DIR "$ENV{APPDATA}/Blender Foundation/Blender/4.5/scripts/addons/custom_raytracer")
    elseif(APPLE)
        set(BLENDER_ADDON_DIR "$ENV{HOME}/Library/Application Support/Blender/4.5/scripts/addons/custom_raytracer")
    else()
        set(BLENDER_ADDON_DIR "$ENV{HOME}/.config/blender/4.5/scripts/addons/custom_raytracer")
    endif()
    
    install(TARGETS raytracer_blender
        LIBRARY DESTINATION ${BLENDER_ADDON_DIR}
    )
    
    install(FILES blender_addon/__init__.py
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

# Note: Tests are run via pytest, not CMake.
# The tests directory contains Python test files (pytest.ini, tests/*.py)
# that are automatically discovered when running `pytest tests/`.

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
