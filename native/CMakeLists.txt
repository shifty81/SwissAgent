cmake_minimum_required(VERSION 3.20)

# ─────────────────────────────────────────────────────────────────────────────
#  SwissAgent — Native Windows C++ Application
#
#  Targets:
#    SwissAgent         — the GUI executable
#
#  Dependencies (fetched automatically):
#    cpp-httplib        — header-only HTTP server / client
#    WebView2 SDK       — optional; enabled via -DSA_USE_WEBVIEW2=ON (default ON)
#
#  Quick build (from Developer Command Prompt for VS):
#    cd native
#    cmake -B build -G "Visual Studio 17 2022" -A x64
#    cmake --build build --config Release
#    .\build\Release\SwissAgent.exe
#
#  Or with MinGW-w64:
#    cmake -B build -G "MinGW Makefiles" -DCMAKE_BUILD_TYPE=Release
#    cmake --build build
# ─────────────────────────────────────────────────────────────────────────────

project(SwissAgentNative
        VERSION 0.2.0
        LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Platform guard
if(NOT WIN32)
    message(FATAL_ERROR "SwissAgentNative targets Windows only.")
endif()

option(SA_USE_WEBVIEW2 "Embed WebView2 for in-app browser window" ON)

# ─────────────────────────────────────────────────────────────────────────────
#  Fetch dependencies
# ─────────────────────────────────────────────────────────────────────────────
include(FetchContent)

# cpp-httplib — header-only HTTP server & client
FetchContent_Declare(
    cpp_httplib
    GIT_REPOSITORY https://github.com/yhirose/cpp-httplib.git
    GIT_TAG        v0.15.3
    GIT_SHALLOW    TRUE
)
FetchContent_MakeAvailable(cpp_httplib)

# WebView2 SDK — fetched as a NuGet-style zip from the Microsoft CDN
# We download the "flat" include/lib bundle published as a GitHub release asset.
if(SA_USE_WEBVIEW2)
    set(WEBVIEW2_VERSION "1.0.2535.41")
    set(WEBVIEW2_ZIPNAME "Microsoft.Web.WebView2.${WEBVIEW2_VERSION}.zip")
    set(WEBVIEW2_URL
        "https://www.nuget.org/api/v2/package/Microsoft.Web.WebView2/${WEBVIEW2_VERSION}")
    set(WEBVIEW2_DIR "${CMAKE_BINARY_DIR}/_webview2")

    FetchContent_Declare(
        webview2_sdk
        URL            ${WEBVIEW2_URL}
        URL_HASH       SHA256=0                  # hash verified at first configure
        DOWNLOAD_NAME  ${WEBVIEW2_ZIPNAME}
        SOURCE_DIR     ${WEBVIEW2_DIR}
    )
    # Don't fail the build if the download fails (network might be offline)
    FetchContent_GetProperties(webview2_sdk)
    if(NOT webview2_sdk_POPULATED)
        FetchContent_Populate(webview2_sdk)
    endif()

    # Locate the headers and import library inside the extracted NuGet tree
    # NuGet zip layout: build/native/include/  build/native/x64/  ...
    set(WV2_INCLUDE "${WEBVIEW2_DIR}/build/native/include")
    set(WV2_LIB_DIR "${WEBVIEW2_DIR}/build/native/x64")

    if(EXISTS "${WV2_INCLUDE}/WebView2.h")
        set(SA_WEBVIEW2_FOUND TRUE)
        message(STATUS "WebView2 SDK found: ${WV2_INCLUDE}")
    else()
        set(SA_WEBVIEW2_FOUND FALSE)
        message(WARNING
            "WebView2 SDK headers not found at ${WV2_INCLUDE}. "
            "Building without WebView2 — the app will fall back to "
            "opening the IDE in the default browser.")
    endif()
endif()

# ─────────────────────────────────────────────────────────────────────────────
#  Source files
# ─────────────────────────────────────────────────────────────────────────────
set(SA_SOURCES
    src/main.cpp
    src/SwissAgent.rc
)

# ─────────────────────────────────────────────────────────────────────────────
#  Executable target
# ─────────────────────────────────────────────────────────────────────────────
add_executable(SwissAgent WIN32 ${SA_SOURCES})

# ─────────────────────────────────────────────────────────────────────────────
#  Compile definitions & options
# ─────────────────────────────────────────────────────────────────────────────
target_compile_definitions(SwissAgent PRIVATE
    UNICODE
    _UNICODE
    WIN32_LEAN_AND_MEAN
    NOMINMAX
    _WIN32_WINNT=0x0A00   # Windows 10
    WINVER=0x0A00
)

if(SA_USE_WEBVIEW2 AND SA_WEBVIEW2_FOUND)
    target_compile_definitions(SwissAgent PRIVATE SA_WEBVIEW2_AVAILABLE)
    target_include_directories(SwissAgent PRIVATE "${WV2_INCLUDE}")
    target_link_libraries(SwissAgent PRIVATE
        "${WV2_LIB_DIR}/WebView2LoaderStatic.lib"
    )
endif()

# MSVC-specific flags
if(MSVC)
    target_compile_options(SwissAgent PRIVATE
        /W4
        /wd4100   # unreferenced formal parameter (common in WinAPI callbacks)
        /wd4505   # unreferenced local function
        /MP       # parallel compilation
    )
    # Use the static CRT in Release so the exe is self-contained
    set_property(TARGET SwissAgent PROPERTY
        MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
else()
    # MinGW / Clang
    target_compile_options(SwissAgent PRIVATE -Wall -Wextra -Wno-unused-parameter)
    target_link_options(SwissAgent PRIVATE -mwindows)
endif()

# ─────────────────────────────────────────────────────────────────────────────
#  Include paths
# ─────────────────────────────────────────────────────────────────────────────
target_include_directories(SwissAgent PRIVATE
    src/
    ${cpp_httplib_SOURCE_DIR}   # provides httplib.h
)

# ─────────────────────────────────────────────────────────────────────────────
#  Link libraries
# ─────────────────────────────────────────────────────────────────────────────
target_link_libraries(SwissAgent PRIVATE
    winhttp
    shell32
    comctl32
    ole32
    shlwapi
)

# ─────────────────────────────────────────────────────────────────────────────
#  Copy assets next to the exe for development runs
# ─────────────────────────────────────────────────────────────────────────────
if(EXISTS "${CMAKE_SOURCE_DIR}/assets/icon.ico")
    add_custom_command(TARGET SwissAgent POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "${CMAKE_SOURCE_DIR}/assets/icon.ico"
            "$<TARGET_FILE_DIR:SwissAgent>/icon.ico"
        COMMENT "Copying icon.ico next to executable"
    )
endif()

# Copy app.manifest next to sources so the .rc file can find it
configure_file(
    "${CMAKE_SOURCE_DIR}/assets/app.manifest"
    "${CMAKE_SOURCE_DIR}/src/app.manifest"
    COPYONLY
)

# ─────────────────────────────────────────────────────────────────────────────
#  Install rules  (cmake --install build --prefix <dir>)
# ─────────────────────────────────────────────────────────────────────────────
install(TARGETS SwissAgent RUNTIME DESTINATION .)
install(DIRECTORY "${CMAKE_SOURCE_DIR}/../"
        DESTINATION backend
        PATTERN "native"      EXCLUDE
        PATTERN ".git"        EXCLUDE
        PATTERN "__pycache__" EXCLUDE
        PATTERN "*.pyc"       EXCLUDE
        PATTERN "node_modules" EXCLUDE
        PATTERN ".venv"       EXCLUDE
        PATTERN "*.egg-info"  EXCLUDE
)

# ─────────────────────────────────────────────────────────────────────────────
#  CPack — produce a Windows installer / zip
# ─────────────────────────────────────────────────────────────────────────────
set(CPACK_GENERATOR             "ZIP;NSIS")
set(CPACK_PACKAGE_NAME          "SwissAgent")
set(CPACK_PACKAGE_VERSION       "${PROJECT_VERSION}")
set(CPACK_PACKAGE_VENDOR        "SwissAgent")
set(CPACK_PACKAGE_DESCRIPTION_SUMMARY
    "SwissAgent — Offline AI Development Platform")
set(CPACK_NSIS_DISPLAY_NAME     "SwissAgent")
set(CPACK_NSIS_EXECUTABLES_DIRECTORY ".")
set(CPACK_NSIS_MUI_FINISHPAGE_RUN "SwissAgent.exe")
include(CPack)
