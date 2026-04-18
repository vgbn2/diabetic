@echo off
echo ==========================================
echo    BIO-QUANT: PREDICTOR ENGINE v2.0
echo ==========================================
echo Starting Metabolic Engine...

:: Check for .env
if not exist .env (
    echo [ERROR] .env file missing! Please create it from .env.example
    pause
    exit /b
)

:: Run the engine
echo 1. Normal Simulation
echo 2. Crash Test
echo 3. Faint Risk Test
echo 4. Live Mode
set /p choice="Select mode (1-4): "

if "%choice%"=="1" python main.py simulation
if "%choice%"=="2" python main.py crash
if "%choice%"=="3" python main.py faint
if "%choice%"=="4" python main.py live

if errorlevel 1 (
    echo [ERROR] Engine failed to start!
)
