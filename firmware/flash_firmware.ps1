param(
    [string]$Port = "COM7",
    [int]$Baud = 460800,
    [switch]$SkipBuild,
    [switch]$SkipErase,
    [switch]$Clean
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-Idf {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    Write-Host ("[run] idf.py " + ($Arguments -join " "))
    & idf.py @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "idf.py failed with exit code $LASTEXITCODE."
    }
}

if (-not (Get-Command idf.py -ErrorAction SilentlyContinue)) {
    throw "idf.py was not found. Open an ESP-IDF PowerShell session first."
}

Set-Location -LiteralPath (Split-Path -Parent $MyInvocation.MyCommand.Path)

if ($Clean) {
    Invoke-Idf -Arguments @("fullclean")
    $sdkconfigPath = Join-Path $PWD "sdkconfig"
    if (Test-Path -LiteralPath $sdkconfigPath) {
        Remove-Item -LiteralPath $sdkconfigPath -Force
    }
}

if (-not $SkipBuild) {
    Invoke-Idf -Arguments @("build")
}

if (-not $SkipErase) {
    Invoke-Idf -Arguments @("-p", $Port, "erase-flash")
}

Invoke-Idf -Arguments @("-p", $Port, "-b", $Baud, "flash")

Write-Host "[ok] Firmware flash completed."
