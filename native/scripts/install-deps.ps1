#Requires -Version 5.1
<#
.SYNOPSIS
    Install build dependencies for the SwissAgent Native (C++) application.

.DESCRIPTION
    This script:
      1. Checks / installs cmake (via winget if not present)
      2. Checks / installs the WebView2 Runtime
      3. Verifies Python 3.10+ is available
      4. Installs the SwissAgent Python package in the project root
         (so the backend can be spawned by the native app)

.PARAMETER SkipPython
    Skip Python package installation.

.PARAMETER SkipWebView2Runtime
    Skip WebView2 Runtime installation check.

.EXAMPLE
    .\install-deps.ps1
    .\install-deps.ps1 -SkipPython
#>
[CmdletBinding()]
param(
    [switch]$SkipPython,
    [switch]$SkipWebView2Runtime
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Step([string]$msg) {
    Write-Host "`n  ► $msg" -ForegroundColor Cyan
}
function Write-OK([string]$msg) {
    Write-Host "    ✓ $msg" -ForegroundColor Green
}
function Write-Warn([string]$msg) {
    Write-Host "    ⚠ $msg" -ForegroundColor Yellow
}
function Write-Fail([string]$msg) {
    Write-Host "    ✗ $msg" -ForegroundColor Red
}

Write-Host ""
Write-Host "  ============================================================" -ForegroundColor Magenta
Write-Host "   SwissAgent Native — Dependency Installer" -ForegroundColor Magenta
Write-Host "  ============================================================" -ForegroundColor Magenta

# ── 1. CMake ──────────────────────────────────────────────────────────────────
Write-Step "Checking cmake ..."
$cmakePath = Get-Command cmake -ErrorAction SilentlyContinue
if ($cmakePath) {
    $ver = (cmake --version 2>&1 | Select-String 'version').ToString().Trim()
    Write-OK "cmake found: $ver"
} else {
    Write-Warn "cmake not found — attempting to install via winget ..."
    try {
        winget install --id Kitware.CMake -e --source winget --silent
        Write-OK "cmake installed. Please restart your terminal."
    } catch {
        Write-Fail "Could not auto-install cmake."
        Write-Host "         Download from: https://cmake.org/download/" -ForegroundColor Yellow
    }
}

# ── 2. Visual Studio Build Tools / Compiler ───────────────────────────────────
Write-Step "Checking for a C++ compiler ..."
$vsWhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (Test-Path $vsWhere) {
    $vsInfo = & $vsWhere -latest -products * -requires Microsoft.VisualCpp.Tools.HostX64.TargetX64 `
              -property displayName 2>&1
    if ($vsInfo) {
        Write-OK "Visual Studio found: $vsInfo"
    } else {
        Write-Warn "Visual Studio found but C++ workload may be missing."
        Write-Host "         Open Visual Studio Installer and add:" -ForegroundColor Yellow
        Write-Host "           Desktop development with C++" -ForegroundColor Yellow
    }
} else {
    $mingw = Get-Command g++ -ErrorAction SilentlyContinue
    if ($mingw) {
        $gppVer = (g++ --version 2>&1 | Select-String 'g\+\+').ToString().Trim()
        Write-OK "MinGW g++ found: $gppVer"
    } else {
        Write-Warn "No C++ compiler detected."
        Write-Host "         Options:" -ForegroundColor Yellow
        Write-Host "           1. Install Visual Studio 2019/2022 with 'Desktop development with C++'" -ForegroundColor Yellow
        Write-Host "           2. Install MinGW-w64: winget install --id MSYS2.MSYS2" -ForegroundColor Yellow
    }
}

# ── 3. WebView2 Runtime ───────────────────────────────────────────────────────
if (-not $SkipWebView2Runtime) {
    Write-Step "Checking WebView2 Runtime ..."

    # WebView2 is registered under HKLM or HKCU depending on install type
    $wv2Keys = @(
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}',
        'HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
    )
    $wv2Found = $false
    foreach ($k in $wv2Keys) {
        if (Test-Path $k) {
            try {
                $pv = (Get-ItemProperty $k).pv
                Write-OK "WebView2 Runtime installed (version $pv)"
                $wv2Found = $true
                break
            } catch {}
        }
    }

    # Also check via the Edge installation (Edge 88+ ships WebView2)
    if (-not $wv2Found) {
        $edgePath = "$env:ProgramFiles (x86)\Microsoft\EdgeWebView\Application"
        if (Test-Path $edgePath) {
            Write-OK "WebView2 Runtime present via Edge WebView"
            $wv2Found = $true
        }
    }

    if (-not $wv2Found) {
        Write-Warn "WebView2 Runtime not found."
        Write-Host "         It is pre-installed on Windows 10 21H1+ and Windows 11." -ForegroundColor Yellow
        Write-Host "         To install manually, run the app — it will prompt you," -ForegroundColor Yellow
        Write-Host "         or download from:" -ForegroundColor Yellow
        Write-Host "           https://go.microsoft.com/fwlink/p/?LinkId=2124703" -ForegroundColor Yellow

        $install = Read-Host "  Install WebView2 Runtime now? [Y/n]"
        if ($install -ne 'n' -and $install -ne 'N') {
            try {
                $installer = "$env:TEMP\MicrosoftEdgeWebview2Setup.exe"
                Invoke-WebRequest `
                    -Uri 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' `
                    -OutFile $installer
                Start-Process $installer -ArgumentList '/silent /install' -Wait
                Write-OK "WebView2 Runtime installed."
            } catch {
                Write-Fail "Auto-install failed: $_"
            }
        }
    }
}

# ── 4. Python 3.10+ ───────────────────────────────────────────────────────────
if (-not $SkipPython) {
    Write-Step "Checking Python ..."
    $pyCmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pyCmd) {
        $pyCmd = Get-Command python3 -ErrorAction SilentlyContinue
    }

    if ($pyCmd) {
        $pyVer = & $pyCmd.Source --version 2>&1
        Write-OK "Python found: $pyVer at $($pyCmd.Source)"

        # Check version >= 3.10
        $verMatch = $pyVer -match '(\d+)\.(\d+)'
        if ($Matches -and ([int]$Matches[1] -gt 3 -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 10))) {
            Write-OK "Python version is 3.10+ — OK"

            # Install SwissAgent package
            Write-Step "Installing SwissAgent Python package ..."
            $projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..') -ErrorAction SilentlyContinue)
            if ($projectRoot -and (Test-Path (Join-Path $projectRoot 'pyproject.toml'))) {
                & $pyCmd.Source -m pip install -e "$projectRoot" --quiet
                Write-OK "SwissAgent package installed."
            } else {
                Write-Warn "pyproject.toml not found at $projectRoot — skipping pip install."
            }
        } else {
            Write-Fail "Python $pyVer is too old. SwissAgent requires Python 3.10+."
            Write-Host "         Download from: https://www.python.org/downloads/" -ForegroundColor Yellow
        }
    } else {
        Write-Fail "Python not found on PATH."
        Write-Host "         Download from: https://www.python.org/downloads/" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "  ============================================================" -ForegroundColor Magenta
Write-Host "   Setup complete." -ForegroundColor Green
Write-Host "   Next steps:" -ForegroundColor Cyan
Write-Host "     1. cd native\scripts" -ForegroundColor White
Write-Host "     2. .\build.bat" -ForegroundColor White
Write-Host "     3. native\build\Release\SwissAgent.exe" -ForegroundColor White
Write-Host "  ============================================================" -ForegroundColor Magenta
Write-Host ""
