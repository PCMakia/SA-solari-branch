# Install Sleeper into global Cursor (Windows)
#
# From the Solari clone root:
#   powershell -ExecutionPolicy Bypass -File packages/sleeper-mcp/install/install_cursor_sleeper.ps1
#   powershell -ExecutionPolicy Bypass -File packages/sleeper-mcp/install/install_cursor_sleeper.ps1 -SolariApiKey "slr_live_..."

param(
    [string]$SolariApiKey = "",
    [string]$SolariHome = ""
)

$ErrorActionPreference = "Stop"

# This script lives at packages/sleeper-mcp/install/ -> repo root is ../../..
if (-not $SolariHome) {
    $SolariHome = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
}

$mcpPkg = Join-Path $SolariHome "packages\sleeper-mcp"
$daemonPkg = Join-Path $SolariHome "packages\sleeper-daemon"
$ruleSrc = Join-Path $PSScriptRoot "sleeper-afk.mdc"
$mergePy = Join-Path $PSScriptRoot "merge_mcp_sleeper.py"

if (-not (Test-Path $mcpPkg)) {
    throw "Cannot find packages/sleeper-mcp under $SolariHome"
}

Write-Host "Sleeper install (SLEEPER_HOME)=$SolariHome"

Write-Host "Installing Python packages..."
python -m pip install -e $mcpPkg -r (Join-Path $mcpPkg "requirements.txt")
python -m pip install -e $daemonPkg -r (Join-Path $daemonPkg "requirements.txt")

$cursorDir = Join-Path $env:USERPROFILE ".cursor"
$mcpPath = Join-Path $cursorDir "mcp.json"
$rulesDir = Join-Path $cursorDir "rules"
New-Item -ItemType Directory -Force -Path $cursorDir | Out-Null
New-Item -ItemType Directory -Force -Path $rulesDir | Out-Null

if (-not $SolariApiKey) {
    if ($env:SOLARI_API_KEY) {
        $SolariApiKey = $env:SOLARI_API_KEY
    } else {
        $SolariApiKey = "slr_live_YOUR_KEY_HERE"
        Write-Host "WARN: Set SOLARI_API_KEY in mcp.json if missing."
    }
}

python $mergePy --mcp-path $mcpPath --sleeper-home $SolariHome --api-key $SolariApiKey

Copy-Item -Force $ruleSrc (Join-Path $rulesDir "sleeper-afk.mdc")
Write-Host "Installed Cursor rule: $rulesDir\sleeper-afk.mdc"
Write-Host ""
Write-Host "Done. Reload Cursor MCP (Settings -> MCP -> toggle sleeper-agent-mcp)."
Write-Host "Open any project and use Sleeper-call{...} -- workspace = that project."
