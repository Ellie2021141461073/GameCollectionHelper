#requires -Version 5.1
<#
.SYNOPSIS
    Set up the local development environment for GameCollectionHelper.

.DESCRIPTION
    Creates .venv with a Python version that has PyTorch wheels, installs the
    lint/test dependencies, installs the npm packages and runs the fast test
    suites as a smoke check.

    The heavy runtime stack (sentence-transformers + torch + the BGE-M3 model,
    ~2.5 GB + 2.3 GB) is NOT installed unless -Full is passed.

.PARAMETER Python
    Path to the interpreter used to create .venv. Defaults to the highest
    supported version found through the `py` launcher.

.PARAMETER Full
    Also install recommender/requirements.txt (torch, sentence-transformers).

.PARAMETER SkipNode
    Do not run `npm install`.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1 -Full
#>
[CmdletBinding()]
param(
    [string]$Python,
    [switch]$Full,
    [switch]$SkipNode
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$MinMinor = 10   # 3.10
$MaxMinor = 12   # 3.12 - sentence-transformers/torch wheels lag behind newer CPython

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Get-PythonVersion([string]$Exe) {
    # No double quotes inside the snippet: Windows PowerShell 5.1 mangles them
    # when passing an argument to a native executable.
    $output = & $Exe -c "import sys; print(*sys.version_info[:3])" 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $output) { return $null }
    $parts = ($output.Trim() -split '\s+')
    if ($parts.Count -lt 3) { return $null }
    return [version]("{0}.{1}.{2}" -f $parts[0], $parts[1], $parts[2])
}

function Install-PythonPackages([string]$RequirementsFile) {
    # uv resolves and downloads far faster than pip and fails loudly instead of
    # backtracking, so prefer it whenever the developer already has it.
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv) {
        Write-Host "    uv pip install -r $RequirementsFile" -ForegroundColor DarkGray
        & $uv.Source pip install --python $VenvPython -r $RequirementsFile
    } else {
        Write-Host "    python -m pip install -r $RequirementsFile" -ForegroundColor DarkGray
        & $VenvPython -m pip install --disable-pip-version-check --progress-bar off -r $RequirementsFile
    }
    if ($LASTEXITCODE -ne 0) { throw "Failed to install $RequirementsFile" }
}

function Resolve-BasePython {
    param([string]$Explicit)
    if ($Explicit) {
        $version = Get-PythonVersion $Explicit
        if (-not $version) { throw "Not a usable Python interpreter: $Explicit" }
        return @{ Exe = $Explicit; Version = $version }
    }
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if (-not $launcher) {
        throw "No 'py' launcher found. Pass -Python <path-to-python.exe> explicitly."
    }
    foreach ($minor in @($MaxMinor, 11, $MinMinor)) {
        $probe = & py "-3.$minor" -c 'import sys; print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0 -and $probe) {
            $exe = $probe.Trim()
            return @{ Exe = $exe; Version = (Get-PythonVersion $exe) }
        }
    }
    throw "No Python 3.$MinMinor-3.$MaxMinor found. Install one from https://www.python.org/downloads/"
}

$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    Write-Step "Reusing the existing .venv"
    $venvVersion = Get-PythonVersion $VenvPython
    Write-Host ("    {0} (Python {1})" -f $VenvPython, $venvVersion)
} else {
    Write-Step "Resolving a base interpreter"
    $base = Resolve-BasePython -Explicit $Python
    Write-Host ("    {0} -> Python {1}" -f $base.Exe, $base.Version)

    if ($base.Version.Major -ne 3 -or $base.Version.Minor -lt $MinMinor) {
        throw ("Python {0} is too old; 3.{1}+ is required." -f $base.Version, $MinMinor)
    }
    if ($base.Version.Minor -gt $MaxMinor) {
        $message = "Python {0} is newer than 3.{1}. PyTorch/sentence-transformers wheels may not exist yet, so the recommender runtime would fail to import them." -f $base.Version, $MaxMinor
        Write-Warning $message
    }

    Write-Step "Creating .venv"
    & $base.Exe -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Failed to create .venv" }
    Write-Host ("    {0}" -f (& $VenvPython -c 'import sys; print(sys.version.split()[0])'))
}

Write-Step "Installing the lint/test dependencies"
Install-PythonPackages -RequirementsFile "requirements-dev.txt"

if ($Full) {
    Write-Step "Installing the full runtime stack (torch + sentence-transformers)"
    Install-PythonPackages -RequirementsFile "recommender/requirements.txt"
} else {
    Write-Host "    skipped: pass -Full to install torch and sentence-transformers" -ForegroundColor DarkGray
}

if (-not $SkipNode) {
    Write-Step "Installing npm packages"
    if (Get-Command npm -ErrorAction SilentlyContinue) {
        & npm install --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
    } else {
        Write-Warning "npm not found; skipping the web dependencies. Install Node.js 22+."
    }
}

Write-Step "Running the fast test suites"
& $VenvPython -m ruff check recommender tests/python
if ($LASTEXITCODE -ne 0) { throw "ruff reported problems" }
& $VenvPython -m unittest discover -s tests/python
if ($LASTEXITCODE -ne 0) { throw "Python tests failed" }

Write-Step "Done"
Write-Host @"
Next steps
    1. Activate the environment:
           .\.venv\Scripts\Activate.ps1
    2. Copy the config template and fill in your own key:
           Copy-Item .env.example .env.local
    3. Put games.csv in the repository root (see README.md) and start the services:
           npm run recommend:api      # FastAPI on 127.0.0.1:8000
           npm run dev                # Next.js on localhost:3000
"@ -ForegroundColor Green
