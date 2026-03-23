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
python -m backend.src.coordinator

pause
