# Start DataWiz Digital Archive System
# Launches: Backend API, Worker, Frontend in parallel

Write-Host "Starting DataWiz Digital Archive System..." -ForegroundColor Cyan
Write-Host ""

# Get script directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

# Check if dependencies exist
Write-Host "Checking dependencies..." -ForegroundColor Yellow

# Backend
if (!(Test-Path "backend\venv")) {
    Write-Host "Installing backend dependencies..." -ForegroundColor Yellow
    Set-Location backend
    python -m venv venv
    .\venv\Scripts\Activate.ps1
    pip install -e ".[worker]"
    Set-Location ..
} else {
    Write-Host "[OK] Backend venv found" -ForegroundColor Green
}

# Frontend
if (!(Test-Path "frontend\node_modules")) {
    Write-Host "Installing frontend dependencies..." -ForegroundColor Yellow
    Set-Location frontend
    npm install
    Set-Location ..
} else {
    Write-Host "[OK] Frontend node_modules found" -ForegroundColor Green
}

Write-Host ""
Write-Host "Starting services..." -ForegroundColor Cyan
Write-Host ""

# Start Backend API (Terminal 1)
Write-Host "[1/3] Starting Backend API (port 8000)..." -ForegroundColor Green
$backendProcess = Start-Process powershell -ArgumentList `
    "-NoExit -Command `"cd '$scriptDir\backend'; `$env:PYTHONUNBUFFERED=1; .\venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`"" `
    -PassThru
Write-Host "[OK] Backend started (PID: $($backendProcess.Id))" -ForegroundColor Green

Start-Sleep -Seconds 3

# Start Worker (Terminal 2)
Write-Host "[2/3] Starting Worker..." -ForegroundColor Green
$workerProcess = Start-Process powershell -ArgumentList `
    "-NoExit -Command `"cd '$scriptDir\backend'; `$env:PYTHONUNBUFFERED=1; .\venv\Scripts\python.exe -m app.worker`"" `
    -PassThru
Write-Host "[OK] Worker started (PID: $($workerProcess.Id))" -ForegroundColor Green

Start-Sleep -Seconds 2

# Start Frontend (Terminal 3)
Write-Host "[3/3] Starting Frontend (port 3000)..." -ForegroundColor Green
$frontendProcess = Start-Process powershell -ArgumentList `
    "-NoExit -Command `"cd '$scriptDir\frontend'; npm run dev`"" `
    -PassThru
Write-Host "[OK] Frontend started (PID: $($frontendProcess.Id))" -ForegroundColor Green

Write-Host ""
Write-Host "================================" -ForegroundColor Cyan
Write-Host "All services started!" -ForegroundColor Green
Write-Host "================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Service URLs:" -ForegroundColor Yellow
Write-Host "  Backend API:    http://localhost:8000" -ForegroundColor White
Write-Host "  API Docs:       http://localhost:8000/docs" -ForegroundColor White
Write-Host "  Frontend:       http://localhost:3000" -ForegroundColor White
Write-Host ""
Write-Host "Process IDs:" -ForegroundColor Yellow
Write-Host "  Backend:  $($backendProcess.Id)" -ForegroundColor White
Write-Host "  Worker:   $($workerProcess.Id)" -ForegroundColor White
Write-Host "  Frontend: $($frontendProcess.Id)" -ForegroundColor White
Write-Host ""
Write-Host "Waiting for services to initialize (allow 10-15 seconds)..." -ForegroundColor Yellow
Start-Sleep -Seconds 12

Write-Host "Open browser to: http://localhost:3000" -ForegroundColor Cyan
Write-Host ""
