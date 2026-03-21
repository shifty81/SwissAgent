@echo off
REM ============================================================
REM  SwissAgent Native — Windows Build Script
REM  Usage: build.bat [Debug|Release]  (default: Release)
REM ============================================================
setlocal EnableDelayedExpansion

set "CONFIG=%~1"
if "%CONFIG%"=="" set "CONFIG=Release"

set "SCRIPT_DIR=%~dp0"
set "NATIVE_DIR=%SCRIPT_DIR%.."
set "BUILD_DIR=%NATIVE_DIR%\build"

echo.
echo  ============================================================
echo   SwissAgent Native — Building (%CONFIG%)
echo  ============================================================
echo.

REM ── Detect CMake ──────────────────────────────────────────────────────────
where cmake >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] cmake not found on PATH.
    echo         Install CMake from https://cmake.org/download/
    echo         and make sure it is on your PATH.
    exit /b 1
)
for /f "tokens=*" %%V in ('cmake --version 2^>nul ^| findstr /i "version"') do (
    echo  cmake: %%V
)

REM ── Detect Visual Studio generator ───────────────────────────────────────
set "GENERATOR="
for %%G in (
    "Visual Studio 17 2022"
    "Visual Studio 16 2019"
    "Visual Studio 15 2017"
) do (
    if "!GENERATOR!"=="" (
        cmake -G %%G -A x64 --version >nul 2>&1
        if not errorlevel 1 set "GENERATOR=%%~G"
    )
)

if "!GENERATOR!"=="" (
    echo  [INFO] No Visual Studio generator found, trying Ninja / MinGW ...
    where ninja >nul 2>&1
    if not errorlevel 1 (
        set "GENERATOR=Ninja"
    ) else (
        set "GENERATOR=MinGW Makefiles"
    )
)
echo  Generator: !GENERATOR!
echo.

REM ── Configure ─────────────────────────────────────────────────────────────
echo  [1/3] Configuring with CMake ...
if "!GENERATOR!"=="Ninja" (
    cmake -B "%BUILD_DIR%" -G "!GENERATOR!" ^
          -DCMAKE_BUILD_TYPE=%CONFIG% ^
          "%NATIVE_DIR%"
) else if "!GENERATOR!"=="MinGW Makefiles" (
    cmake -B "%BUILD_DIR%" -G "!GENERATOR!" ^
          -DCMAKE_BUILD_TYPE=%CONFIG% ^
          "%NATIVE_DIR%"
) else (
    cmake -B "%BUILD_DIR%" -G "!GENERATOR!" -A x64 ^
          "%NATIVE_DIR%"
)

if errorlevel 1 (
    echo.
    echo  [ERROR] CMake configure failed.
    exit /b 1
)

REM ── Build ─────────────────────────────────────────────────────────────────
echo.
echo  [2/3] Building ...
cmake --build "%BUILD_DIR%" --config %CONFIG% --parallel

if errorlevel 1 (
    echo.
    echo  [ERROR] Build failed.
    exit /b 1
)

REM ── Locate the executable ─────────────────────────────────────────────────
set "EXE_PATH=%BUILD_DIR%\%CONFIG%\SwissAgent.exe"
if not exist "%EXE_PATH%" (
    REM Flat build (Ninja / MinGW)
    set "EXE_PATH=%BUILD_DIR%\SwissAgent.exe"
)

echo.
echo  [3/3] Build complete!
if exist "%EXE_PATH%" (
    echo.
    echo   Executable: %EXE_PATH%
    echo.
    set /p "LAUNCH=Launch SwissAgent now? [Y/n] "
    if /i "!LAUNCH!"=="" set "LAUNCH=Y"
    if /i "!LAUNCH!"=="Y" start "" "%EXE_PATH%"
) else (
    echo  [WARN] Could not find SwissAgent.exe at expected path.
)

endlocal
