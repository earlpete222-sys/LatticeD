<#
.SYNOPSIS
    Install LatticeD on Windows from a clean machine.

.DESCRIPTION
    Walks a non-developer through the full install: Python (via winget with
    a manual fallback URL), Python dependencies, Ollama, the two required
    1.5B models, a strong LATTICED_SECRET persisted to User scope, and a
    desktop shortcut that launches Start-LatticeD.ps1.

    Idempotent — re-running skips steps that are already done. Safe to use
    as an upgrade script after `git pull`.

.NOTES
    Sprint 45 — installer for the "free best-in-class personal assistant"
    strategy. Intentionally avoids Docker so users don't have to install
    Docker Desktop before they can try LatticeD.
#>
param(
    [switch]$SkipModels,     # Don't pull Ollama models (faster reinstalls)
    [switch]$SkipShortcut,   # Don't write the desktop shortcut
    [switch]$Force           # Re-pull deps and regenerate secret even if present
)

$ErrorActionPreference = "Stop"

function Step($msg) { Write-Host "`n[$(Get-Date -Format 'HH:mm:ss')] $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "  OK  $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "  !!  $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host "  XX  $msg" -ForegroundColor Red; exit 1 }

$LATTICED_ROOT = $PSScriptRoot
$REQS = Join-Path $LATTICED_ROOT "requirements.txt"
$MODELS = @("deepseek-r1:1.5b", "qwen2.5-coder:1.5b")
$PYTHON_MIN_MAJOR = 3
$PYTHON_MIN_MINOR = 12

Write-Host @"

  ============================================================
   LatticeD Installer
   Personal AI that runs on your machine. Nothing leaves it.
  ============================================================

"@ -ForegroundColor White

# ── Step 1: Python ──────────────────────────────────────────────────────────
Step "Checking Python..."
function Get-PythonVersion {
    try {
        $v = & python --version 2>&1
        if ($v -match "Python (\d+)\.(\d+)") {
            return @{ Major = [int]$Matches[1]; Minor = [int]$Matches[2] }
        }
    } catch {}
    return $null
}
$pyver = Get-PythonVersion
if ($null -eq $pyver) {
    Warn "Python not found."
    Write-Host "  Attempting install via winget (Windows Package Manager)..."
    try {
        winget install --id Python.Python.3.12 -e --accept-package-agreements --accept-source-agreements
        # winget can update PATH only for new shells, so refresh ours.
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                    [System.Environment]::GetEnvironmentVariable("Path","User")
        $pyver = Get-PythonVersion
    } catch {
        Fail "winget install failed. Download Python 3.12 manually from https://www.python.org/downloads/ and re-run this installer."
    }
}
if ($null -eq $pyver) {
    Fail "Python still not detected after install. Open a NEW PowerShell window and re-run Install-LatticeD.ps1."
}
if ($pyver.Major -lt $PYTHON_MIN_MAJOR -or
   ($pyver.Major -eq $PYTHON_MIN_MAJOR -and $pyver.Minor -lt $PYTHON_MIN_MINOR)) {
    Fail "Python $($pyver.Major).$($pyver.Minor) found; LatticeD needs $PYTHON_MIN_MAJOR.$PYTHON_MIN_MINOR or later."
}
Ok "Python $($pyver.Major).$($pyver.Minor) detected."

# ── Step 2: Python dependencies ─────────────────────────────────────────────
Step "Installing Python dependencies (this can take a few minutes the first time)..."
if (-not (Test-Path $REQS)) { Fail "requirements.txt not found at $REQS" }
$pipArgs = @("-m", "pip", "install", "-r", $REQS)
if ($Force) { $pipArgs += "--upgrade" }
& python @pipArgs
if ($LASTEXITCODE -ne 0) { Fail "pip install failed. Check the error above and re-run." }
Ok "Python dependencies installed."

# ── Step 3: Ollama ──────────────────────────────────────────────────────────
Step "Checking Ollama..."
$ollamaCmd = Get-Command ollama -ErrorAction SilentlyContinue
if ($null -eq $ollamaCmd) {
    $likelyExe = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
    if (Test-Path $likelyExe) {
        Ok "Ollama found at $likelyExe (not on PATH yet)."
    } else {
        Warn "Ollama not found."
        Write-Host "  Attempting install via winget..."
        try {
            winget install --id Ollama.Ollama -e --accept-package-agreements --accept-source-agreements
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                        [System.Environment]::GetEnvironmentVariable("Path","User")
            Ok "Ollama installed via winget."
        } catch {
            Warn "winget install failed. Download Ollama manually from https://ollama.com/download/windows"
            Warn "After installing Ollama, re-run this installer to pull the models."
        }
    }
} else {
    Ok "Ollama on PATH."
}

# ── Step 4: Pull models ─────────────────────────────────────────────────────
if ($SkipModels) {
    Warn "Skipping model pull (-SkipModels)."
} else {
    Step "Pulling required models (deepseek-r1:1.5b ~1.1 GB, qwen2.5-coder:1.5b ~986 MB)..."
    $ollamaResolved = if ($ollamaCmd) { "ollama" } else { Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe" }
    if (-not (Test-Path $ollamaResolved) -and $null -eq (Get-Command ollama -ErrorAction SilentlyContinue)) {
        Warn "Ollama executable not found — skipping model pull. Install Ollama, then re-run with -SkipShortcut to finish."
    } else {
        foreach ($m in $MODELS) {
            Write-Host "  Pulling $m ..."
            & ollama pull $m
            if ($LASTEXITCODE -ne 0) {
                Warn "ollama pull $m failed. You can retry later with: ollama pull $m"
            } else {
                Ok "$m ready."
            }
        }
    }
}

# ── Step 5: LATTICED_SECRET ────────────────────────────────────────────────
Step "Setting LATTICED_SECRET..."
$existing = [System.Environment]::GetEnvironmentVariable("LATTICED_SECRET", "User")
$defaultSecret = "local_dev_secret_123"
if ($existing -and $existing -ne $defaultSecret -and -not $Force) {
    Ok "LATTICED_SECRET already set in User scope (length $($existing.Length))."
} else {
    # 32 bytes of cryptographic randomness, base64-encoded (~43 chars).
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $secret = [Convert]::ToBase64String($bytes).TrimEnd("=")
    [System.Environment]::SetEnvironmentVariable("LATTICED_SECRET", $secret, "User")
    $env:LATTICED_SECRET = $secret
    Ok "Generated a strong LATTICED_SECRET (persisted to User scope)."
    Write-Host "  Stored in the User environment. New PowerShell windows pick it up automatically." -ForegroundColor DarkGray
}

# ── Step 6: Desktop shortcut ────────────────────────────────────────────────
if ($SkipShortcut) {
    Warn "Skipping desktop shortcut (-SkipShortcut)."
} else {
    Step "Writing desktop shortcut..."
    $startScript = Join-Path $LATTICED_ROOT "Start-LatticeD.ps1"
    if (-not (Test-Path $startScript)) {
        Warn "Start-LatticeD.ps1 not found — skipping shortcut."
    } else {
        $desktop = [Environment]::GetFolderPath("Desktop")
        $lnk = Join-Path $desktop "LatticeD.lnk"
        $shell = New-Object -ComObject WScript.Shell
        $sc = $shell.CreateShortcut($lnk)
        $sc.TargetPath = "powershell.exe"
        $sc.Arguments = "-NoExit -ExecutionPolicy Bypass -File `"$startScript`""
        $sc.WorkingDirectory = $LATTICED_ROOT
        $sc.IconLocation = "powershell.exe,0"
        $sc.Description = "Launch LatticeD (sovereign personal AI)"
        $sc.Save()
        Ok "Desktop shortcut written: $lnk"
    }
}

# ── Done ────────────────────────────────────────────────────────────────────
Write-Host @"

  ============================================================
   Install complete.

   Launch with:
     .\Start-LatticeD.ps1            (this window)
     LatticeD desktop shortcut       (any future session)

   For phone access over Tailscale, see MOBILE.md.
  ============================================================

"@ -ForegroundColor Green
