# Bio-Quant: 5-Layer Metabolic Command Center Orchestrator
$ProjectRoot = "C:\Users\Lenovo\Desktop\VGBN\.vscode\CODEPTIT\hyperglycemia-faint-predictor"

# Define the 5 Operational Contexts (L1 - L5)
$Tabs = @(
    @{Title="[SENSOR] L1/L2 - Ingestion & DSP"; Dir="."; Cmd="python -m diabetic.ingestion.nightscout"},
    @{Title="[BRAIN] L3 - ML Engine"; Dir="."; Cmd="python -m diabetic.ml_engine.predictor"},
    @{Title="[INTERFACE] L5 - HUD & Bot"; Dir="."; Cmd="python -m diabetic.ui.cli_hud"},
    @{Title="[FORENSICS] L4 - Audit & Memory"; Dir="."; Cmd="python check_audit_db.py"},
    @{Title="[COORDINATOR] Core - Master Loop"; Dir="."; Cmd="python main.py live"}
)

# Check for Windows Terminal (wt.exe)
$wt_exists = Get-Command wt -ErrorAction SilentlyContinue

if ($wt_exists) {
    Write-Host "Initializing Windows Terminal: 5-Layer Metabolic Suite..." -ForegroundColor Cyan
    $first = $true
    $wt_cmd = ""
    foreach ($tab in $Tabs) {
        $dir = Join-Path $ProjectRoot $tab.Dir
        # Construct the internal command for each tab
        $internal_cmd = "powershell -NoExit -Command `"Set-Location '$ProjectRoot'; Write-Host '--- $($tab.Title) ---' -ForegroundColor Cyan; $($tab.Cmd)`""
        
        if ($first) {
            $wt_cmd = "wt -d `"$ProjectRoot`" -p `"PowerShell`" --title `"$($tab.Title)`" $internal_cmd"
            $first = $false
        } else {
            $wt_cmd += " `; nt -d `"$ProjectRoot`" -p `"PowerShell`" --title `"$($tab.Title)`" $internal_cmd"
        }
    }
    # Execute the combined wt command
    Invoke-Expression $wt_cmd
} else {
    Write-Host "Windows Terminal not detected. Spawning 5 separate PowerShell contexts..." -ForegroundColor Yellow
    foreach ($tab in $Tabs) {
        $dir = Join-Path $ProjectRoot $tab.Dir
        Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$ProjectRoot'; `$Host.UI.RawUI.WindowTitle = '$($tab.Title)'; Write-Host '--- $($tab.Title) ---' -ForegroundColor Cyan; $($tab.Cmd)"
    }
}
