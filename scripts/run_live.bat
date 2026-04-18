@echo off
setlocal

:: --- BIO-QUANT: PERSISTENT RUNNER ---
:: This script will run the metabolic engine 24/7.
:: If the engine crashes (due to Nightscout timeout or sensor loss),
:: it will automatically wait 10 seconds and restart.

:RESTART
echo [%date% %time%] Starting BIO-QUANT Predictive Engine (LIVE MODULE MODE)...

:: Step up from scripts/ to project root
cd ..
:: Run the engine as a module
python -m diabetic.main live

:: If python exits with error code (nonzero)
if errorlevel 1 (
    echo [%date% %time%] CRASH DETECTED. Restarting in 10 seconds...
    timeout /t 10 /nobreak
    goto RESTART
)

:: If user manually stops with Ctrl+C (python exits with 0 usually)
echo [%date% %time%] Engine stopped gracefully or manually.
set /p retry="Restart now? (y/n): "
if /i "%retry%"=="y" goto RESTART

endlocal
