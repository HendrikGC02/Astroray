# FindOptiX.cmake — locate the NVIDIA OptiX SDK headers.
#
# We do NOT bundle the SDK (NVIDIA license forbids redistribution). Users
# install OptiX 8.0+ themselves and we just locate the include directory.
#
# Search order:
#   1. -DOPTIX_INSTALL_DIR=<path>
#   2. $ENV{OPTIX_INSTALL_DIR}
#   3. Default platform install paths.
#
# OptiX is a header-only API at compile time — the device functions are
# loaded at runtime through the optix function table (optixInit) so there
# is nothing to link. We expose:
#   OptiX_FOUND        — TRUE if optix.h was located.
#   OptiX_INCLUDE_DIRS — directory containing optix.h.
#   OptiX_VERSION      — string parsed from optix_function_table.h
#                        (best-effort; empty when not parseable).
#
# Adapted from NVIDIA's SDK/CMake/FindOptiX.cmake (NVIDIA OptiX SDK
# License — re-implemented from the public interface, no source mirrored).

set(_optix_search_paths "")

if(OPTIX_INSTALL_DIR)
    list(APPEND _optix_search_paths "${OPTIX_INSTALL_DIR}")
endif()
if(DEFINED ENV{OPTIX_INSTALL_DIR})
    list(APPEND _optix_search_paths "$ENV{OPTIX_INSTALL_DIR}")
endif()

if(WIN32)
    file(GLOB _optix_default_windows
        "C:/ProgramData/NVIDIA Corporation/OptiX SDK 8.*"
        "C:/ProgramData/NVIDIA Corporation/OptiX SDK 7.*"
    )
    list(APPEND _optix_search_paths ${_optix_default_windows})
elseif(UNIX)
    file(GLOB _optix_default_unix
        "/opt/optix"
        "/opt/NVIDIA-OptiX-SDK-*"
        "$ENV{HOME}/NVIDIA-OptiX-SDK-*"
    )
    list(APPEND _optix_search_paths ${_optix_default_unix})
endif()

find_path(OptiX_INCLUDE_DIR
    NAMES optix.h
    PATHS ${_optix_search_paths}
    PATH_SUFFIXES include
    DOC "Directory containing optix.h from the NVIDIA OptiX SDK"
)

if(OptiX_INCLUDE_DIR AND EXISTS "${OptiX_INCLUDE_DIR}/optix.h")
    file(STRINGS "${OptiX_INCLUDE_DIR}/optix.h" _optix_version_line
         REGEX "^#define[ \t]+OPTIX_VERSION[ \t]+[0-9]+")
    if(_optix_version_line)
        string(REGEX REPLACE "^#define[ \t]+OPTIX_VERSION[ \t]+([0-9]+).*" "\\1"
               _optix_version_int "${_optix_version_line}")
        # OPTIX_VERSION = major*10000 + minor*100 + micro
        math(EXPR _optix_major "${_optix_version_int} / 10000")
        math(EXPR _optix_minor "(${_optix_version_int} % 10000) / 100")
        math(EXPR _optix_micro "${_optix_version_int} % 100")
        set(OptiX_VERSION "${_optix_major}.${_optix_minor}.${_optix_micro}")
    endif()
endif()

set(OptiX_INCLUDE_DIRS "${OptiX_INCLUDE_DIR}")

include(FindPackageHandleStandardArgs)
find_package_handle_standard_args(OptiX
    REQUIRED_VARS OptiX_INCLUDE_DIR
    VERSION_VAR   OptiX_VERSION
)

mark_as_advanced(OptiX_INCLUDE_DIR)
