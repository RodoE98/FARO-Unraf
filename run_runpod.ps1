# ============================================================
# run_runpod.ps1
#
# DOUBLE-CLICK THIS to run the chatbot using a Runpod GPU backend.
#
# IMPORTANT: The backend must ALREADY be running on Runpod
# before you use this script (started manually in the Runpod
# JupyterLab terminal, following the README Part 1 steps).
# This script only starts the FRONTEND on your computer and
# connects it to that Runpod backend.
#
# The backend now uses the model qwen2.5:14b. On the Runpod pod,
# install it once with:   ollama pull qwen2.5:14b
# (this script checks for it and warns you if it is missing)
# ============================================================

# Automatically find frontend/ next to this script,
# no matter where the FARO folder is placed on the computer.
$ScriptDir    = Split-Path -Parent $MyInvocation.MyCommand.Path
$FrontendPath = Join-Path $ScriptDir "frontend"

$ErrorActionPreference = "Stop"

function Write-Step($msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

Write-Host "============================================" -ForegroundColor Green
Write-Host "   Starting chatbot in RUNPOD mode" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green

if (-not (Test-Path $FrontendPath)) {
    Write-Host "ERROR: Frontend folder not found at $FrontendPath" -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}

# [FIX] Fail early with a clear message if Node.js / npm is not installed
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: npm was not found. Install Node.js (https://nodejs.org) and try again." -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}

# 1. Ask for the Runpod Pod ID
Write-Host ""
Write-Host "You'll find your Pod ID in the Runpod dashboard." -ForegroundColor Yellow
Write-Host "It's the string of letters/numbers in your pod's connect URL," -ForegroundColor Yellow
Write-Host "e.g. if the URL is https://abc123xyz-8000.proxy.runpod.net" -ForegroundColor Yellow
Write-Host "then your Pod ID is:  abc123xyz" -ForegroundColor Yellow
Write-Host ""
$PodId = (Read-Host "Enter your Runpod Pod ID").Trim()

# [FIX] If the whole URL was pasted by mistake, extract just the Pod ID from it
if ($PodId -match '^(?:https?://)?([A-Za-z0-9]+)-\d+\.proxy\.runpod\.net') {
    $PodId = $Matches[1]
}

if ([string]::IsNullOrWhiteSpace($PodId)) {
    Write-Host "ERROR: No Pod ID entered." -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}

$backendUrl = "https://$PodId-8000.proxy.runpod.net"

# 2. Write the .env.local file
Write-Step "Connecting frontend to: $backendUrl"
$envFile = Join-Path $FrontendPath ".env.local"
# [FIX] Write as UTF-8 WITHOUT BOM. Windows PowerShell 5.1's "Out-File -Encoding utf8" adds a BOM,
# which can stop Vite from reading the first variable in the file.
[System.IO.File]::WriteAllText($envFile, "VITE_API_URL=$backendUrl`r`n", (New-Object System.Text.UTF8Encoding($false)))

# 2b. [FIX] Check that the backend is reachable and that the model is installed on the pod
Write-Step "Checking the backend on Runpod..."
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $health = Invoke-RestMethod -Uri "$backendUrl/api/health" -TimeoutSec 20
    if ($health.ollama_reachable -and $health.model_available) {
        Write-Host "Backend OK. Model ready: $($health.model)" -ForegroundColor Green
    }
    elseif ($health.ollama_reachable) {
        Write-Host "WARNING: The backend is running, but the model '$($health.model)' is NOT installed in Ollama." -ForegroundColor Yellow
        Write-Host "In the Runpod terminal run:   ollama pull $($health.model)" -ForegroundColor Yellow
        Write-Host "Then restart the backend." -ForegroundColor Yellow
    }
    else {
        Write-Host "WARNING: The backend is running, but it cannot reach Ollama on the pod." -ForegroundColor Yellow
        Write-Host "Make sure 'ollama serve' is running in the Runpod terminal." -ForegroundColor Yellow
    }
}
catch {
    $code = $null
    if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }

    if ($code -eq 404) {
        Write-Host "WARNING: The backend answered, but has no /api/health endpoint." -ForegroundColor Yellow
        Write-Host "It is probably still running the OLD main.py." -ForegroundColor Yellow
        Write-Host "Upload the new main.py to the pod and restart the backend." -ForegroundColor Yellow
    }
    else {
        Write-Host "WARNING: Could not reach the backend at $backendUrl" -ForegroundColor Yellow
        Write-Host "Check that:" -ForegroundColor Yellow
        Write-Host "  - the pod is running (not stopped) in the Runpod dashboard" -ForegroundColor Yellow
        Write-Host "  - the Pod ID above is correct" -ForegroundColor Yellow
        Write-Host "  - the backend is started in the Runpod terminal (README Part 1)" -ForegroundColor Yellow
    }
    $answer = Read-Host "Start the frontend anyway? (y/N)"
    if ($answer -notmatch '^[yY]') {
        exit 1
    }
}

# 3. Install frontend dependencies
Write-Step "Installing frontend dependencies..."
Push-Location $FrontendPath
npm install
$npmExit = $LASTEXITCODE
Pop-Location
# [FIX] Native commands don't trigger $ErrorActionPreference, so check the exit code explicitly
if ($npmExit -ne 0) {
    Write-Host "ERROR: npm install failed (exit code $npmExit). See the messages above." -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}

# 4. Start frontend
Write-Step "Starting frontend..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$FrontendPath'; npm run dev"

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host " All set! A new window has opened." -ForegroundColor Green
Write-Host " Wait a few seconds, then open your browser to:" -ForegroundColor Green
Write-Host "     http://localhost:8080" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Make sure the backend is still running on Runpod" -ForegroundColor Yellow
Write-Host "(check the Runpod JupyterLab terminal window)." -ForegroundColor Yellow
Write-Host ""
Write-Host "To stop, close the new window. Remember to STOP" -ForegroundColor Yellow
Write-Host "your Runpod pod too, so you don't get charged" -ForegroundColor Yellow
Write-Host "while it's not in use!" -ForegroundColor Yellow
Read-Host "Press Enter to close this window"
