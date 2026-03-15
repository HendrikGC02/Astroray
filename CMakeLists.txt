cmake_minimum_required(VERSION 3.15)
project(CustomRaytracer VERSION 3.0 LANGUAGES CXX)

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

# Compiler flags for optimization
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    # Base optimization flags
    add_compile_options(-Wall -Wextra -O3)
    
    # Architecture-specific optimizations
    if(USE_NATIVE_ARCH)
        add_compile_options(-march=native)
    else()
        # Minimum SIMD requirements
        add_compile_options(-msse4.1 -mavx2)
    endif()
    
    # Fast math (trades precision for speed)
    if(USE_FAST_MATH)
        add_compile_options(-ffast-math)
    endif()
    
    # OpenMP for parallel rendering
    find_package(OpenMP REQUIRED)
    if(OpenMP_CXX_FOUND)
        set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} ${OpenMP_CXX_FLAGS}")
    endif()
    
elseif(MSVC)
    add_compile_options(/W4)
    # Only apply optimizations in Release builds
    add_compile_options($<$<CONFIG:Release>:/O2>)
    add_compile_options($<$<CONFIG:Release>:/arch:AVX2>)
    add_compile_options(/openmp)
    
    if(USE_FAST_MATH)
        add_compile_options(/fp:fast)
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
set_source_files_properties(include/stb_image_write_impl.c PROPERTIES LANGUAGE CXX)
add_library(stb_image_write_lib STATIC include/stb_image_write_impl.c)
set_target_properties(stb_image_write_lib PROPERTIES 
    CXX_STANDARD 17
    CXX_STANDARD_REQUIRED ON
)

# Standalone executable
add_executable(raytracer_standalone ${SOURCES} ${HEADERS})

target_link_libraries(raytracer_standalone PRIVATE
    raytracer_core
    stb_image_write_lib
)

if(OpenMP_CXX_FOUND)
    target_link_libraries(raytracer_standalone PRIVATE OpenMP::OpenMP_CXX)
endif()

# Set output name
set_target_properties(raytracer_standalone PROPERTIES
    OUTPUT_NAME raytracer
    RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin
)

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
    )
    
    if(OpenMP_CXX_FOUND)
        target_link_libraries(astroray PRIVATE OpenMP::OpenMP_CXX)
    endif()
    
    # Set properties for Python module
    set_target_properties(astroray PROPERTIES
        LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}
        OUTPUT_NAME astroray
        SUFFIX ".pyd"
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

# Testing
if(BUILD_TESTS)
    enable_testing()
    add_subdirectory(tests)
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

# Print configuration summary
message(STATUS "")
message(STATUS "===== Configuration Summary =====")
message(STATUS "Build type: ${CMAKE_BUILD_TYPE}")
message(STATUS "C++ standard: ${CMAKE_CXX_STANDARD}")
message(STATUS "Compiler: ${CMAKE_CXX_COMPILER_ID}")
message(STATUS "OpenMP: ${OpenMP_CXX_FOUND}")
message(STATUS "Native arch: ${USE_NATIVE_ARCH}")
message(STATUS "Fast math: ${USE_FAST_MATH}")
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
