$ErrorActionPreference = 'Stop'
$raycuraRoot = $PSScriptRoot
Set-Location -LiteralPath $raycuraRoot
$env:TEMP = Join-Path $raycuraRoot 'temp'
$env:TMP = $env:TEMP
$env:PIP_CACHE_DIR = Join-Path $raycuraRoot 'cache\pip'
$env:PYTHONPYCACHEPREFIX = Join-Path $raycuraRoot 'cache\python'
$env:OLLAMA_MODELS = Join-Path $raycuraRoot 'models\ollama'
$env:STREAMLIT_BROWSER_GATHER_USAGE_STATS = 'false'
New-Item -ItemType Directory -Force -Path $env:TEMP, $env:PIP_CACHE_DIR, $env:PYTHONPYCACHEPREFIX | Out-Null
if (-not (Test-Path -LiteralPath (Join-Path $raycuraRoot '.venv\Scripts\python.exe'))) {
    throw 'Project Python environment is missing. Follow the setup in README.md.'
}
$env:npm_config_cache = Join-Path $raycuraRoot 'cache\npm'
$frontend = Join-Path $raycuraRoot 'frontend'
if (-not (Test-Path -LiteralPath (Join-Path $frontend 'dist\index.html'))) {
    & npm.cmd --prefix $frontend ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependencies could not be installed.' }
    & npm.cmd --prefix $frontend run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
}
Write-Host 'Better. gait assessment: http://127.0.0.1:8765'
& (Join-Path $raycuraRoot '.venv\Scripts\python.exe') -m uvicorn raycura.assessment_api:app --host 127.0.0.1 --port 8765 --no-access-log
exit $LASTEXITCODE
