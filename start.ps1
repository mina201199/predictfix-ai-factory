param([int]$Port=8080,[switch]$Demo)
$ErrorActionPreference='Stop'
# 以 .\start.ps1 執行時 $env: 的修改會留在呼叫端的終端機；結束時還原，避免下次換模式啟動沿用到上次的設定
$managedVariables='DEMO_MODE','APP_MODE','LLM_PROVIDER','LOCAL_LLM_MODEL','LLM_URL','OLLAMA_MODELS','OLLAMA_HOST','OLLAMA_MODEL'
$savedVariables=@{}
foreach ($name in $managedVariables) { $savedVariables[$name]=[Environment]::GetEnvironmentVariable($name,'Process') }
try {
  $env:DEMO_MODE=if($Demo){'1'}else{'0'}
  $env:APP_MODE=if($Demo){'demo'}else{'production'}
  Set-Location -LiteralPath $PSScriptRoot
  $projectPython=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
  if (-not (Test-Path -LiteralPath $projectPython)) { throw '請先依 README 安裝 Python 相依套件。' }
  & $projectPython (Join-Path $PSScriptRoot 'scripts\check_runtime.py')
  if ($LASTEXITCODE -ne 0) { throw '依賴檢查失敗，請先執行 .\setup.ps1。' }
  $localServer=Join-Path $PSScriptRoot '.runtime\llama\llama-server.exe'
  $localModel=Join-Path $PSScriptRoot '.runtime\models\gemma-4-E2B-it-Q8_0.gguf'
  if ((Test-Path -LiteralPath $localServer) -and -not (Test-Path -LiteralPath $localModel)) {
    Write-Warning '找不到 Gemma 4 E2B 模型檔，本次不使用本機模型；請執行 .\.venv\Scripts\python.exe scripts\setup_local_llm.py。'
  }
  if ((Test-Path -LiteralPath $localServer) -and (Test-Path -LiteralPath $localModel)) {
    $serverRunning=$true
    try { Invoke-RestMethod 'http://127.0.0.1:8081/health' -TimeoutSec 2 | Out-Null } catch { $serverRunning=$false }
    if ($serverRunning) {
      # 背景的 llama-server 不會隨本程式結束；若仍是換模型前啟動的舊服務，會在不知情下繼續使用舊模型
      try { $runningModel=(Invoke-RestMethod 'http://127.0.0.1:8081/v1/models' -TimeoutSec 2).data[0].id } catch { $runningModel='未知' }
      if ($runningModel -notlike '*gemma-4-E2B-it-Q8_0*') { Write-Warning "8081 上執行的模型是 $runningModel，不是 Gemma 4 E2B；請先關閉舊的 llama-server 再重新啟動。" }
    }
    else {
      $arguments=@('-m',('"'+$localModel+'"'),'--host','127.0.0.1','--port','8081','-c','2048','-t','4','--reasoning','off','--reasoning-budget','0')
      Start-Process -FilePath $localServer -ArgumentList $arguments -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot '.runtime\llama-out.log') -RedirectStandardError (Join-Path $PSScriptRoot '.runtime\llama-error.log')
    }
    $env:LLM_PROVIDER='llamacpp'
    $env:LOCAL_LLM_MODEL='gemma-4-E2B-it-Q8_0'
    $env:LLM_URL='http://127.0.0.1:8081'
  }
  $localOllama=Join-Path $PSScriptRoot '.runtime\ollama\ollama.exe'
  if (-not (Test-Path -LiteralPath $localServer) -and (Test-Path -LiteralPath $localOllama)) {
    $env:OLLAMA_MODELS=Join-Path $PSScriptRoot '.runtime\models'
    $env:OLLAMA_HOST='127.0.0.1:11434'
    try { Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 | Out-Null }
    catch { Start-Process -FilePath $localOllama -ArgumentList 'serve' -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot '.runtime\ollama-out.log') -RedirectStandardError (Join-Path $PSScriptRoot '.runtime\ollama-error.log') }
    $env:OLLAMA_MODEL='gemma4:e2b-it-q8_0'
  }
  & $projectPython -m uvicorn backend.app:app --host 127.0.0.1 --port $Port
}
finally {
  foreach ($name in $managedVariables) { [Environment]::SetEnvironmentVariable($name,$savedVariables[$name],'Process') }
}
