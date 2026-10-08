param([string]$Python='python')
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
$projectPython=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
  & $Python -m venv .venv
  if ($LASTEXITCODE -ne 0) { throw 'Failed to create the Python virtual environment.' }
}
# SQLAlchemy supports a pure-Python build; no Windows security policy is changed.
$previousCext=$env:DISABLE_SQLALCHEMY_CEXT
$env:DISABLE_SQLALCHEMY_CEXT='1'
try {
  & $projectPython -m pip install --no-binary SQLAlchemy -r requirements.txt
  if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
  & $projectPython -c "from sqlalchemy.util._has_cython import HAS_CYEXTENSION; raise SystemExit(1 if HAS_CYEXTENSION else 0)"
  if ($LASTEXITCODE -ne 0) {
    # Existing virtual environments may still contain a prebuilt native wheel.
    & $projectPython -m pip install --force-reinstall --no-deps --no-binary SQLAlchemy --no-cache-dir SQLAlchemy==2.1.3
    if ($LASTEXITCODE -ne 0) { throw 'SQLAlchemy pure-Python installation failed.' }
  }
} finally {
  if ($null -eq $previousCext) { Remove-Item Env:DISABLE_SQLALCHEMY_CEXT -ErrorAction SilentlyContinue }
  else { $env:DISABLE_SQLALCHEMY_CEXT=$previousCext }
}
& $projectPython scripts/check_runtime.py
if ($LASTEXITCODE -ne 0) { throw 'Runtime checks failed; see the diagnostic above.' }
Write-Host 'Ready. Run .\start.ps1 -Demo -Port 8082 for the local demo.'
