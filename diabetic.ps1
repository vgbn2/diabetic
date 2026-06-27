# diabetic.ps1 — Bio-Quant CLI/TUI launcher (mirror of personal_finance_draft/sv.ps1)
#
# Usage:
#   .\diabetic.ps1                                  -> interactive TUI menu
#   .\diabetic.ps1 <category> <command> [--flags]   -> one-shot CLI
#
# Examples:
#   .\diabetic.ps1                          # opens the menu
#   .\diabetic.ps1 settings show --json
#   .\diabetic.ps1 op status
#   .\diabetic.ps1 admin cleanup --retention-days 90
#
# Runs from the repo root regardless of the caller's working directory so
# `python -m diabetic.cli` resolves the package on sys.path.

Push-Location $PSScriptRoot
try {
    if ($args.Count -eq 0) {
        python -m diabetic.cli.tui
    } else {
        python -m diabetic.cli @args
    }
} finally {
    Pop-Location
}
