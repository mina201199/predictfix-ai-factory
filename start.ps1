param([int]$Port=8080,[switch]$Demo)
$ErrorActionPreference='Stop'
$env:DEMO_MODE=if($Demo){'1'}else{'0'}
$env:APP_MODE=if($Demo){'demo'}else{'production'}
Set-Location -LiteralPath $PSScriptRoot
$projectPython=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) { throw '請先依 README 安裝 Python 相依套件。' }
& $projectPython (Join-Path $PSScriptRoot 'scripts\check_runtime.py')
if ($LASTEXITCODE -ne 0) { throw '依賴檢查失敗，請先執行 .\setup.ps1。' }
$localServer=Join-Path $PSScriptRoot '.runtime\llama\llama-server.exe'
$localModel=Join-Path $PSScriptRoot '.runtime\models\Qwen3-0.6B-Q8_0.gguf'
if ((Test-Path -LiteralPath $localServer) -and (Test-Path -LiteralPath $localModel)) {
  try { Invoke-RestMethod 'http://127.0.0.1:8081/health' -TimeoutSec 2 | Out-Null }
  catch {
    $arguments=@('-m',('"'+$localModel+'"'),'--host','127.0.0.1','--port','8081','-c','2048','-t','4','--reasoning','off','--reasoning-budget','0')
    Start-Process -FilePath $localServer -ArgumentList $arguments -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot '.runtime\llama-out.log') -RedirectStandardError (Join-Path $PSScriptRoot '.runtime\llama-error.log')
  }
  $env:LLM_PROVIDER='llamacpp'
  $env:LOCAL_LLM_MODEL='Qwen3-0.6B-Q8_0'
  $env:LLM_URL='http://127.0.0.1:8081'
}
$localOllama=Join-Path $PSScriptRoot '.runtime\ollama\ollama.exe'
if (-not (Test-Path -LiteralPath $localServer) -and (Test-Path -LiteralPath $localOllama)) {
  $env:OLLAMA_MODELS=Join-Path $PSScriptRoot '.runtime\models'
  $env:OLLAMA_HOST='127.0.0.1:11434'
  try { Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 | Out-Null }
  catch { Start-Process -FilePath $localOllama -ArgumentList 'serve' -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot '.runtime\ollama-out.log') -RedirectStandardError (Join-Path $PSScriptRoot '.runtime\ollama-error.log') }
  $env:OLLAMA_MODEL='qwen3:0.6b'
}
& $projectPython -m uvicorn backend.app:app --host 127.0.0.1 --port $Port
