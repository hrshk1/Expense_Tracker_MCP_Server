param(
    [string]$ServerName = "expense-tracker",
    [string]$WriterEmails = "",
    [string]$ExpenseDataDir = "",
    [string]$ConfigPath = ""
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$MainPath = Join-Path $ProjectRoot "main.py"

if (-not $ExpenseDataDir) {
    $ExpenseDataDir = Join-Path $ProjectRoot ".tmp_data"
}

if (-not $ConfigPath) {
    if (-not $env:APPDATA) {
        throw "APPDATA is not set. Pass -ConfigPath explicitly."
    }
    $ConfigPath = Join-Path $env:APPDATA "Claude\claude_desktop_config.json"
}

if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "Python executable not found at $PythonPath"
}

if (-not (Test-Path -LiteralPath $MainPath)) {
    throw "main.py not found at $MainPath"
}

$ConfigDir = Split-Path -Parent $ConfigPath
if (-not (Test-Path -LiteralPath $ConfigDir)) {
    New-Item -ItemType Directory -Path $ConfigDir | Out-Null
}

function New-EmptyConfig {
    $config = New-Object psobject
    $config | Add-Member -MemberType NoteProperty -Name "mcpServers" -Value (New-Object psobject)
    return $config
}

if (Test-Path -LiteralPath $ConfigPath) {
    $rawConfig = Get-Content -LiteralPath $ConfigPath -Raw
    if ($rawConfig.Trim()) {
        $config = $rawConfig | ConvertFrom-Json
    } else {
        $config = New-EmptyConfig
    }

    $backupPath = "$ConfigPath.bak-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    Copy-Item -LiteralPath $ConfigPath -Destination $backupPath
    Write-Host "Backed up existing Claude config to $backupPath"
} else {
    $config = New-EmptyConfig
}

if (-not $config.PSObject.Properties.Name.Contains("mcpServers")) {
    $config | Add-Member -MemberType NoteProperty -Name "mcpServers" -Value (New-Object psobject)
}

$serverConfig = New-Object psobject
$serverConfig | Add-Member -MemberType NoteProperty -Name "command" -Value $PythonPath
$serverConfig | Add-Member -MemberType NoteProperty -Name "args" -Value @($MainPath)

$envConfig = New-Object psobject
$envConfig | Add-Member -MemberType NoteProperty -Name "EXPENSE_DATA_DIR" -Value $ExpenseDataDir
$envConfig | Add-Member -MemberType NoteProperty -Name "WRITER_EMAILS" -Value $WriterEmails
$envConfig | Add-Member -MemberType NoteProperty -Name "MCP_BASE_URL" -Value "http://localhost:8000"
$serverConfig | Add-Member -MemberType NoteProperty -Name "env" -Value $envConfig

$existingServer = $config.mcpServers.PSObject.Properties[$ServerName]
if ($existingServer) {
    $existingServer.Value = $serverConfig
} else {
    $config.mcpServers | Add-Member -MemberType NoteProperty -Name $ServerName -Value $serverConfig
}

$config | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $ConfigPath -Encoding UTF8

Write-Host "Installed Claude Desktop MCP config for '$ServerName'."
Write-Host "Config path: $ConfigPath"
Write-Host "Restart Claude Desktop to load the server."
