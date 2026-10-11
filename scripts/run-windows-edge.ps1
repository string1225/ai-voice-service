param(
    [string]$EnvFile = (Join-Path $PSScriptRoot "..\.env.windows")
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$logDir = Join-Path $repoRoot ".run-logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw "Missing runtime configuration: $EnvFile"
}

foreach ($line in Get-Content -LiteralPath $EnvFile) {
    $trimmed = $line.Trim()
    if (-not $trimmed -or $trimmed.StartsWith("#")) { continue }
    $parts = $trimmed.Split("=", 2)
    if ($parts.Count -ne 2) { continue }
    [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim(), "Process")
}

$required = @("PYTHON_EXE", "SSH_EXE", "SSH_HOST", "SSH_KEY", "API_KEY")
foreach ($name in $required) {
    $value = [Environment]::GetEnvironmentVariable($name, "Process")
    if (-not $value) { throw "Missing $name in $EnvFile" }
}

$created = $false
$mutex = [Threading.Mutex]::new($true, "Local\AiVoiceEdgeSupervisor", [ref]$created)
if (-not $created) { exit 0 }

$python = $env:PYTHON_EXE
$ssh = $env:SSH_EXE
$gatewayProcess = $null
$apiProcess = $null
$tunnelProcess = $null

function Test-ListeningPort([int]$Port) {
    return $null -ne (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1)
}

function Start-LoggedProcess([string]$FilePath, [string[]]$Arguments, [string]$Name) {
    $stdout = Join-Path $logDir "$Name.stdout.log"
    $stderr = Join-Path $logDir "$Name.stderr.log"
    return Start-Process -FilePath $FilePath -ArgumentList $Arguments -WorkingDirectory $repoRoot `
        -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
}

try {
    while ($true) {
        if (-not (Test-ListeningPort 8006)) {
            if ($null -eq $gatewayProcess -or $gatewayProcess.HasExited) {
                $gatewayProcess = Start-LoggedProcess $python @(
                    "gateway.py", "--host", "0.0.0.0", "--port", "8006",
                    "--internal-port", "8007", "--http", "--lang", "zh"
                ) "gateway"
            }
        }

        if (-not (Test-ListeningPort 8080)) {
            if ($null -eq $apiProcess -or $apiProcess.HasExited) {
                $env:GATEWAY_HTTP_URL = "http://127.0.0.1:8006"
                $env:GATEWAY_WS_URL = "ws://127.0.0.1:8006/v1/realtime"
                if (-not $env:ALLOWED_ORIGINS) { $env:ALLOWED_ORIGINS = "https://codex.sunny-string.cn" }
                $apiProcess = Start-LoggedProcess $python @(
                    "-m", "uvicorn", "service_api:app", "--host", "127.0.0.1", "--port", "8080",
                    "--root-path", "/ai-voice"
                ) "api"
            }
        }

        if ($null -eq $tunnelProcess -or $tunnelProcess.HasExited) {
            $tunnelProcess = Start-LoggedProcess $ssh @(
                "-NT", "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
                "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3",
                "-i", $env:SSH_KEY,
                "-R", "127.0.0.1:18006:127.0.0.1:8006",
                "-R", "127.0.0.1:18080:127.0.0.1:8080",
                $env:SSH_HOST
            ) "tunnel"
        }

        Start-Sleep -Seconds 5
    }
}
finally {
    foreach ($process in @($tunnelProcess, $apiProcess, $gatewayProcess)) {
        if ($null -ne $process -and -not $process.HasExited) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
    }
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
