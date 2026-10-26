$ErrorActionPreference = 'Stop'

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallDir = Join-Path $env:LOCALAPPDATA 'RecCLI'
$VenvDir = Join-Path $InstallDir 'venv'
$BinDir = Join-Path $InstallDir 'bin'
$Launcher = Join-Path $BinDir 'reccli.cmd'

if (-not (Test-Path (Join-Path $ProjectDir 'pyproject.toml'))) {
    throw "Could not find pyproject.toml in $ProjectDir"
}

$PythonCommand = Get-Command py -ErrorAction SilentlyContinue
if ($PythonCommand) {
    $Python = 'py'
    $PythonArgs = @('-3')
} else {
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $PythonCommand) {
        throw 'Python 3.10 or newer is required. Install it from https://www.python.org/downloads/windows/ and enable the Python launcher or add Python to PATH.'
    }
    $Python = $PythonCommand.Source
    $PythonArgs = @()
}

$Version = & $Python @PythonArgs --version 2>&1
if ($LASTEXITCODE -ne 0 -or $Version -notmatch 'Python 3\.(1[0-9]|[2-9][0-9])') {
    throw "RecCLI requires Python 3.10 or newer; found: $Version"
}

New-Item -ItemType Directory -Force -Path $InstallDir, $BinDir | Out-Null
if (-not (Test-Path (Join-Path $VenvDir 'Scripts\python.exe'))) {
    & $Python @PythonArgs -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python virtual environment.' }
}

$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'
& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'Could not upgrade pip.' }
& $VenvPython -m pip install --editable $ProjectDir
if ($LASTEXITCODE -ne 0) { throw 'Could not install RecCLI.' }

@('@echo off', ('"{0}" %*' -f (Join-Path $VenvDir 'Scripts\reccli.exe'))) |
    Set-Content -Encoding ASCII $Launcher

$UserPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$PathEntries = @($UserPath -split ';' | Where-Object { $_ })
if ($PathEntries -notcontains $BinDir) {
    $NewPath = (@($PathEntries) + $BinDir) -join ';'
    [Environment]::SetEnvironmentVariable('Path', $NewPath, 'User')
}

$Ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
Write-Host "`nInstalled RecCLI. Open a new terminal and run: reccli"
Write-Host "Launcher: $Launcher"
if (-not $Ffmpeg) {
    Write-Warning 'FFmpeg was not found on PATH. Install FFmpeg and add its bin folder to PATH for recording.'
}
