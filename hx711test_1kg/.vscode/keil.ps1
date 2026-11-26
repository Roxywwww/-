param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('build', 'flash')]
    [string]$Action
)

$ErrorActionPreference = 'Stop'
$uv4 = 'C:\Keil_v5\UV4\UV4.exe'
$project = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\MDK-ARM\hx711test.uvprojx')).Path
$projectDirectory = Split-Path -Parent $project

if (-not (Test-Path -LiteralPath $uv4)) {
    throw "Keil uVision not found: $uv4"
}

function Invoke-Keil {
    param(
        [string]$Mode,
        [string]$LogName
    )

    $log = Join-Path $PSScriptRoot $LogName
    if (Test-Path -LiteralPath $log) {
        Remove-Item -LiteralPath $log -Force
    }

    $arguments = '{0} "{1}" -o "{2}"' -f $Mode, $project, $log
    $process = Start-Process -FilePath $uv4 -ArgumentList $arguments `
        -WorkingDirectory $projectDirectory -WindowStyle Hidden -Wait -PassThru

    if (Test-Path -LiteralPath $log) {
        Get-Content -LiteralPath $log | Write-Output
    }

    if ($process.ExitCode -ge 2) {
        throw "Keil $Mode failed (exit code $($process.ExitCode))."
    }
    if ($process.ExitCode -eq 1) {
        Write-Warning "Keil $Mode completed with warnings."
    }
}

Invoke-Keil -Mode '-b' -LogName 'keil-build.log'

if ($Action -eq 'flash') {
    Invoke-Keil -Mode '-f' -LogName 'keil-flash.log'
    $flashLog = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'keil-flash.log') -Raw
    if ($flashLog -notmatch 'Verify OK\.') {
        throw 'Keil did not report Verify OK; check the flash log above.'
    }
}
