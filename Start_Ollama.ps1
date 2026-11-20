$ErrorActionPreference = 'Stop'
$raycuraRoot = $PSScriptRoot
$env:TEMP = Join-Path $raycuraRoot 'temp'
$env:TMP = $env:TEMP
$env:OLLAMA_MODELS = Join-Path $raycuraRoot 'models\ollama'
$env:OLLAMA_HOST = '127.0.0.1:11434'
& (Join-Path $raycuraRoot 'tools\ollama\ollama.exe') serve
