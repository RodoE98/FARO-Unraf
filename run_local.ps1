# ============================================================
# run_local.ps1
#
# DOUBLE-CLICK THIS to run the chatbot fully on YOUR computer.
# No internet/Runpod needed. Everything runs locally.
# ============================================================

# Optional: run_local.bat -Model qwen2.5:7b   (needs a GPU with 8 GB+ of VRAM; default is the small phi3:mini)
param([string]$Model = "phi3:mini")

# Automatically find backend/ and frontend/ next to this script,
# no matter where the FARO folder is placed on the computer.
$ScriptDir    = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendPath  = Join-Path $ScriptDir "backend"
$FrontendPath = Join-Path $ScriptDir "frontend"

$ErrorActionPreference = "Stop"

function Write-Step($msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

Write-Host "============================================" -ForegroundColor Green
Write-Host "   Starting chatbot in LOCAL mode" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green

# 1. Check paths exist
if (-not (Test-Path $BackendPath)) {
    Write-Host "ERROR: Backend folder not found at $BackendPath" -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}
if (-not (Test-Path $FrontendPath)) {
    Write-Host "ERROR: Frontend folder not found at $FrontendPath" -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}

# 2. Check / install Ollama
Write-Step "Checking for Ollama..."
$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama) {
    Write-Host "Ollama not found. Installing via winget..." -ForegroundColor Yellow
    winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements
    Write-Host "Ollama installed. Please close this window and double-click run_local.ps1 again." -ForegroundColor Yellow
    Read-Host "Press Enter to close"
    exit 0
} else {
    Write-Host "Ollama found."
}

# 3. Start Ollama server if not already running
Write-Step "Starting Ollama server..."
$ollamaRunning = Get-Process ollama -ErrorAction SilentlyContinue
if (-not $ollamaRunning) {
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "ollama serve"
    Start-Sleep -Seconds 3
} else {
    Write-Host "Ollama server already running."
}

# 4. Pull the local model (skips if already downloaded)
# [FIX] The backend now reads the model name from the LLM_MODEL environment variable
# (default: qwen2.5:14b, meant for the Runpod GPU). A normal PC cannot run that,
# so local mode keeps the small model. If your PC has a GPU with 8 GB+ of VRAM you can
# try "qwen2.5:7b" here (and set $NumCtx = 8192, $RagChunks = 4, $MaxContextChars = 12000).
$LlmModel        = $Model
if ($LlmModel -like "phi3*") {
    # Small model: 4k context. Everything that goes into the prompt is reduced so it fits
    # (fichas + book + conversation history + the answer must all fit in NUM_CTX).
    $NumCtx          = 4096
    $RagChunks       = 2      # book fragments when there are no fichas
    $RagChunksFichas = 1      # book fragments when there ARE fichas
    $FichasMax       = 2
    $MaxContextChars = 5000
    $MaxTokens       = 700    # max answer length
    $HistMensajes    = 4      # previous messages sent to the model (2 turns)
    $HistChars       = 2500
    $HistMsgChars    = 1200
} else {
    # Bigger model (e.g. qwen2.5:7b): same values as the Runpod setup
    $NumCtx          = 8192
    $RagChunks       = 4
    $RagChunksFichas = 2
    $FichasMax       = 3
    $MaxContextChars = 12000
    $MaxTokens       = 1000
    $HistMensajes    = 6
    $HistChars       = 6000
    $HistMsgChars    = 2500
}

Write-Step "Checking $LlmModel model (this may take a while the first time)..."
ollama pull $LlmModel
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: could not download the model $LlmModel (exit code $LASTEXITCODE)." -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}

# The backend window started in step 7 inherits these variables
$env:LLM_MODEL         = $LlmModel
$env:NUM_CTX           = "$NumCtx"
$env:RAG_CHUNKS        = "$RagChunks"
$env:MAX_CONTEXT_CHARS = "$MaxContextChars"
$env:RENDER_LATEX      = "1"
$env:RAG_CHUNKS_CON_FICHAS      = "$RagChunksFichas"
$env:FICHAS_MAX                 = "$FichasMax"
$env:MAX_TOKENS                 = "$MaxTokens"
$env:HISTORIAL_MAX_MENSAJES     = "$HistMensajes"
$env:HISTORIAL_MAX_CHARS        = "$HistChars"
$env:HISTORIAL_MSG_MAX_CHARS    = "$HistMsgChars"
$env:PYTHONUNBUFFERED           = "1"

# 5. Point frontend at local backend
Write-Step "Configuring frontend to use local backend..."
$envFile = Join-Path $FrontendPath ".env.local"
# [FIX] UTF-8 WITHOUT BOM (Windows PowerShell 5.1 "Out-File -Encoding utf8" adds a BOM that can break Vite)
[System.IO.File]::WriteAllText($envFile, "VITE_API_URL=http://localhost:8000`r`n", (New-Object System.Text.UTF8Encoding($false)))

# 6. Install backend dependencies
Write-Step "Installing backend dependencies..."
Push-Location $BackendPath
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Pop-Location

# 7. Start backend in its own window
Write-Step "Starting backend server..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$BackendPath'; python -m uvicorn main:app --host 0.0.0.0 --port 8000"

# 8. Install frontend dependencies
Write-Step "Installing frontend dependencies..."
Push-Location $FrontendPath
npm install
Pop-Location

# 9. Start frontend in its own window
Write-Step "Starting frontend..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$FrontendPath'; npm run dev"

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host " All set! Two new windows have opened." -ForegroundColor Green
Write-Host " Wait a few seconds, then open your browser to:" -ForegroundColor Green
Write-Host "     http://localhost:8080" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Each conversation shows its own code (FARO-XXXXXX) on the chat page;" -ForegroundColor Yellow
Write-Host "use the 'Nueva conversacion' button to get a new one." -ForegroundColor Yellow
Write-Host ""
Write-Host "NOTE: Without a powerful GPU, responses can take" -ForegroundColor Yellow
Write-Host "several minutes. This is normal, not a crash." -ForegroundColor Yellow
Write-Host ""
Write-Host "To stop everything, just close the two new windows." -ForegroundColor Yellow
Read-Host "Press Enter to close this window"
