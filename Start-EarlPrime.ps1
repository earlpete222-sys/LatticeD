param(
    [switch]$Watch,
    [switch]$Dev
)

# ── Path Configuration ────────────────────────────────────────────────────────
# Override any of these via environment variables before launching:
#   $env:LATTICED_PYTHON  = "C:\path\to\python.exe"   (default: just "python")
#   $env:LATTICED_HOME    = "C:\path\to\LatticeD"     (default: script's own folder)
#   $env:LATTICED_OLLAMA  = "C:\path\to\ollama.exe"   (default: %LOCALAPPDATA%\Programs\Ollama)
$PYTHON       = if ($env:LATTICED_PYTHON) { $env:LATTICED_PYTHON } else { "python" }
$LATTICED_ROOT = if ($env:LATTICED_HOME) { $env:LATTICED_HOME } else { $PSScriptRoot }
$AGENT_SCRIPT = Join-Path $LATTICED_ROOT "End_Game_AI\End_Game_AI.py"
$AGENT_DIR    = Join-Path $LATTICED_ROOT "End_Game_AI"
$OLLAMA_EXE   = if ($env:LATTICED_OLLAMA) { $env:LATTICED_OLLAMA } else { "$env:LOCALAPPDATA\Programs\Ollama\ollama app.exe" }
$OLLAMA_API   = "http://localhost:11434/api/version"
$MAX_WAIT     = 60

function Log-Step($msg) { Write-Host "`n[$(Get-Date -Format 'HH:mm:ss')] $msg" -ForegroundColor Cyan }
function Log-Ok($msg)   { Write-Host "  OK  $msg" -ForegroundColor Green }
function Log-Warn($msg) { Write-Host "  !!  $msg" -ForegroundColor Yellow }

# Step 1 - Set env vars
Log-Step "Setting environment variables..."
[System.Environment]::SetEnvironmentVariable("OLLAMA_NUM_PARALLEL", "2", "User")
$env:OLLAMA_NUM_PARALLEL = "2"
Log-Ok "OLLAMA_NUM_PARALLEL=2 (persisted to User scope)"

# Prevents HuggingFace Hub from firing 40+ HEAD requests at startup to check
# for model updates — models are local-only, updates are irrelevant.
[System.Environment]::SetEnvironmentVariable("HF_HUB_OFFLINE", "1", "User")
$env:HF_HUB_OFFLINE = "1"
Log-Ok "HF_HUB_OFFLINE=1  (suppresses HuggingFace network calls at startup)"

# Step 2 - Kill Ollama
Log-Step "Stopping existing Ollama processes..."
$procs = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Name -like "*ollama*" }
if ($procs) {
    foreach ($p in $procs) {
        taskkill /PID $p.Id /F 2>$null | Out-Null
        Log-Ok "Killed $($p.Name) (PID $($p.Id))"
    }
    Start-Sleep -Seconds 3
} else {
    Log-Ok "No Ollama processes running."
}

# Step 3 - Start Ollama
Log-Step "Starting Ollama with OLLAMA_NUM_PARALLEL=2..."
if (Test-Path $OLLAMA_EXE) {
    Start-Process $OLLAMA_EXE
    Log-Ok "Ollama tray app launched."
} else {
    Log-Warn "ollama app.exe not found at expected path. Trying PATH..."
    Start-Process "ollama" -ErrorAction SilentlyContinue
}

# Step 4 - Wait for API
Log-Step "Waiting for Ollama API..."
$elapsed = 0
$ready = $false
while ($elapsed -lt $MAX_WAIT) {
    Start-Sleep -Seconds 2
    $elapsed += 2
    try {
        $r = Invoke-RestMethod -Uri $OLLAMA_API -Method GET -TimeoutSec 2 -ErrorAction Stop
        Log-Ok "Ollama ready (version: $($r.version))"
        $ready = $true
        break
    } catch {
        Write-Host "  ...waiting ($elapsed / $MAX_WAIT s)" -ForegroundColor DarkGray
    }
}
if (-not $ready) {
    Log-Warn "Ollama API did not respond in $MAX_WAIT s. Continuing anyway."
}

# Step 5 - Launch Earl Prime
if ($Dev) {
    Log-Step "DEV mode - uvicorn --reload (restarts on file save)"
    Log-Warn "Press Ctrl+C to stop."
    Set-Location $AGENT_DIR
    & $PYTHON -m uvicorn End_Game_AI:app --reload --host 127.0.0.1 --port 8000

} elseif ($Watch) {
    Log-Step "WATCHDOG mode - Earl Prime restarts automatically on crash"
    Log-Warn "Press Ctrl+C to stop."
    $delay = 5
    $attempts = 0
    while ($true) {
        $attempts++
        Write-Host "`n  [$(Get-Date -Format 'HH:mm:ss')] Starting Earl Prime (attempt $attempts)..." -ForegroundColor Cyan
        Set-Location $AGENT_DIR
        & $PYTHON $AGENT_SCRIPT
        $code = $LASTEXITCODE
        if ($code -eq 0) {
            Log-Ok "Earl Prime exited cleanly. Watchdog stopping."
            break
        }
        Log-Warn "Earl Prime stopped (exit code: $code). Restarting in $delay s..."
        Start-Sleep -Seconds $delay
        if ($delay -lt 60) { $delay = $delay * 2 }
    }

} else {
    Log-Step "Starting Earl Prime..."
    Log-Warn "Press Ctrl+C to stop."
    Set-Location $AGENT_DIR
    & $PYTHON $AGENT_SCRIPT
}
