# Heroku Config Sync Utility
# Purpose: Bulk upload .env variables to Heroku for the 'hyper-hypo-tracker' app.

$APP_NAME = "hyper-hypo-tracker"

if (-not (Test-Path ".env")) {
    Write-Error ".env file not found in current directory."
    exit
}

Write-Host "--- Syncing .env to Heroku App: $APP_NAME ---" -ForegroundColor Cyan

Get-Content ".env" | ForEach-Object {
    if ($_ -match "^(?<key>[^#\s][^=]*)=(?<value>.*)$") {
        $key = $Matches['key'].Trim()
        $value = $Matches['value'].Trim()
        
        # Strip optional quotes
        if ($value -match "^`"(.*)`"$") { $value = $Matches[1] }
        if ($value -match "^'(.*)'$") { $value = $Matches[1] }
        
        if ($key -ne "" -and $value -ne "") {
            Write-Host "Setting $key..."
            heroku config:set "$key=$value" --app $APP_NAME
        }
    }
}

Write-Host "--- Sync Complete ---" -ForegroundColor Green
