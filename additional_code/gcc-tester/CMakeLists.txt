cmake_minimum_required(VERSION 3.20)

set(CMAKE_C_COMPILER "/usr/bin/clang-20")
set(CMAKE_CXX_COMPILER "/usr/bin/clang++-20")
set(CMAKE_CXX_STANDARD 20)  # WebRTC uses C++20

# Use LLD linker to match WebRTC
set(CMAKE_LINKER_TYPE LLD CACHE STRING "")

set(TARGET_CPU "x86_64" CACHE STRING "Target CPU architecture (e.g. x86_64, arm64)")
set(TARGET_TRIPLE "" CACHE STRING "Optional clang target triple used for cross-compilation")
set(TARGET_SYSROOT "" CACHE PATH "Optional sysroot path used for cross-compilation")

if(TARGET_CPU STREQUAL "arm64" AND NOT TARGET_TRIPLE)
        set(TARGET_TRIPLE "aarch64-linux-gnu" CACHE STRING "Optional clang target triple used for cross-compilation" FORCE)
endif()

if(TARGET_CPU STREQUAL "arm64")
        set(CMAKE_SYSTEM_PROCESSOR "aarch64")
elseif(TARGET_CPU STREQUAL "x86_64")
        set(CMAKE_SYSTEM_PROCESSOR "x86_64")
endif()

if(TARGET_TRIPLE)
        set(CMAKE_C_COMPILER_TARGET "${TARGET_TRIPLE}")
        set(CMAKE_CXX_COMPILER_TARGET "${TARGET_TRIPLE}")
endif()

if(TARGET_SYSROOT)
        set(CMAKE_SYSROOT "${TARGET_SYSROOT}")
endif()

project(gcc_tester)

option(USE_WEBRTC_LIBCXX "Link against WebRTC's custom libc++ artifacts" ON)

# Provide a default build type (Ninja is single-config). Keep Debug unless user specifies Release.
if(NOT CMAKE_BUILD_TYPE)
        set(CMAKE_BUILD_TYPE Debug CACHE STRING "Build type (Debug or Release)" FORCE)
endif()
message(STATUS "CMAKE_BUILD_TYPE: ${CMAKE_BUILD_TYPE}")
message(STATUS "TARGET_CPU: ${TARGET_CPU}")
if(TARGET_TRIPLE)
        message(STATUS "Using clang target triple: ${TARGET_TRIPLE}")
endif()
if(TARGET_SYSROOT)
        message(STATUS "Using sysroot: ${TARGET_SYSROOT}")
endif()
message(STATUS "USE_WEBRTC_LIBCXX: ${USE_WEBRTC_LIBCXX}")

# Allow selecting which WebRTC GN/Ninja output directory to link against.
# Default stays "out/Default" so existing build directory keeps working.
set(WEBRTC_ROOT "/home/yannis/code/webrtc-checkout/src" CACHE PATH "Root of the WebRTC checkout (src directory)")
set(WEBRTC_OUT_SUBDIR "Default" CACHE STRING "Name of the GN output subdirectory under WEBRTC_ROOT/out (e.g. Default, Release)")
set(WEBRTC_OUT_DIR "${WEBRTC_ROOT}/out/${WEBRTC_OUT_SUBDIR}" CACHE PATH "Full path to the selected WebRTC GN output directory")

message(STATUS "Using WebRTC output directory: ${WEBRTC_OUT_DIR}")

# Derived paths (generated libc++ headers & libs inside the GN output tree)
set(WEBRTC_LIBCXX_GEN_INCLUDE "${WEBRTC_OUT_DIR}/gen/third_party/libc++/src/include")
set(WEBRTC_LIBWEBRTC_LIB     "${WEBRTC_OUT_DIR}/obj/libwebrtc.a")
set(WEBRTC_LIBCXX_LIB        "${WEBRTC_OUT_DIR}/obj/buildtools/third_party/libc++/libc++.a")
set(WEBRTC_LIBCXXABI_LIB     "${WEBRTC_OUT_DIR}/obj/buildtools/third_party/libc++abi/libc++abi.a")

# Simple sanity checks (non-fatal, just informative)
if(NOT EXISTS "${WEBRTC_LIBWEBRTC_LIB}")
        message(WARNING "libwebrtc.a not found at ${WEBRTC_LIBWEBRTC_LIB}. Did you build the chosen GN config?")
endif()
if(USE_WEBRTC_LIBCXX AND NOT EXISTS "${WEBRTC_LIBCXX_GEN_INCLUDE}")
        message(WARNING "Generated libc++ includes not found at ${WEBRTC_LIBCXX_GEN_INCLUDE}.")
endif()
if(USE_WEBRTC_LIBCXX)
        if(NOT EXISTS "${WEBRTC_LIBCXX_LIB}")
                message(WARNING "libc++.a not found at ${WEBRTC_LIBCXX_LIB}.")
        endif()
        if(NOT EXISTS "${WEBRTC_LIBCXXABI_LIB}")
                message(WARNING "libc++abi.a not found at ${WEBRTC_LIBCXXABI_LIB}.")
        endif()
endif()

# Set libc++ flags after project() to avoid CMake test issues
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -v")
if(USE_WEBRTC_LIBCXX)
        set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -stdlib=libc++")
endif()

# Preprocessor definitions
add_definitions(-DWEBRTC_POSIX=1)
add_definitions(-D__STDC_CONSTANT_MACROS=1)
# Match WebRTC's custom ABI namespace
add_definitions(-D_LIBCPP_ABI_NAMESPACE=__Cr)
# Add missing hardening mode definition
add_definitions(-D_LIBCPP_HARDENING_MODE_DEFAULT=_LIBCPP_HARDENING_MODE_NONE)

# Include directories - WebRTC's custom generated libc++ first
set(PROJECT_EXTERNAL_INCLUDES
        /home/yannis/.vcpkg-clion/vcpkg/installed/x64-linux/include
        ${WEBRTC_ROOT}
        ${WEBRTC_ROOT}/third_party/abseil-cpp
        ${WEBRTC_ROOT}/third_party/libyuv/include
)

if(USE_WEBRTC_LIBCXX)
        list(PREPEND PROJECT_EXTERNAL_INCLUDES ${WEBRTC_LIBCXX_GEN_INCLUDE})
endif()

include_directories(${PROJECT_EXTERNAL_INCLUDES})

# Source files
set(PROJECT_SOURCES
        main.cpp
        webrtc_test_peer.cpp
        syncodecs.cpp
        fake_track_source.cpp
        ffmpeg_receiver_sink.cpp
        ffmpeg_receiver_sink.h
        arm_runtime_stubs.cpp
)

# Create target
add_executable(gcc_tester ${PROJECT_SOURCES})

# Compiler flags to match WebRTC build environment
target_compile_options(gcc_tester PRIVATE
        $<$<COMPILE_LANGUAGE:CXX>:
        -Werror
        -Wall
        -Wextra
        -pedantic-errors
        -Wconversion
        -Wsign-conversion
        
        # Match WebRTC's build flags
        -fvisibility=hidden
        -fvisibility-inlines-hidden
        >
        
        # Basic optimizations for Release builds (kept minimal & safe)
        $<$<AND:$<CONFIG:Release>,$<COMPILE_LANGUAGE:CXX>>:-O2 -DNDEBUG>
        $<$<AND:$<CONFIG:Release>,$<COMPILE_LANGUAGE:C>>:-O2 -DNDEBUG>
)

if(TARGET_TRIPLE)
        target_compile_options(gcc_tester PRIVATE --target=${TARGET_TRIPLE})
        target_link_options(gcc_tester PRIVATE --target=${TARGET_TRIPLE})
endif()

if(TARGET_SYSROOT)
        target_compile_options(gcc_tester PRIVATE --sysroot=${TARGET_SYSROOT})
        target_link_options(gcc_tester PRIVATE --sysroot=${TARGET_SYSROOT})
endif()

# Mark external headers as system to suppress warnings
foreach(dir ${PROJECT_EXTERNAL_INCLUDES})
        target_include_directories(gcc_tester SYSTEM PRIVATE ${dir})
endforeach()

# Find required system libraries
find_library(PTHREAD_LIB pthread REQUIRED)
find_library(DL_LIB dl REQUIRED) 
find_library(RT_LIB rt REQUIRED)
find_library(M_LIB m REQUIRED)

# Link libraries in correct order
set(WEBRTC_THIRD_PARTY_LIBS ${WEBRTC_LIBWEBRTC_LIB})
if(USE_WEBRTC_LIBCXX)
        list(APPEND WEBRTC_THIRD_PARTY_LIBS
                ${WEBRTC_LIBCXX_LIB}
                ${WEBRTC_LIBCXXABI_LIB})
endif()

target_link_libraries(gcc_tester
        ${WEBRTC_THIRD_PARTY_LIBS}
        ${PTHREAD_LIB}
        ${DL_LIB}
        ${RT_LIB}
        ${M_LIB}
)

# Linker options to match WebRTC
target_link_options(gcc_tester PRIVATE
        -fuse-ld=lld
        -Wl,--gc-sections
        -Wl,--as-needed
)

if(USE_WEBRTC_LIBCXX)
        target_link_options(gcc_tester PRIVATE -nostdlib++)
endif()
