param([int]$Port=8083)
$ErrorActionPreference='Stop'
# DATABASE_URL 若殘留在終端機，之後執行 .\start.ps1 -Demo 會開到 factory.db 並寫入展示資料，所以結束時一律還原
$managedVariables='BOOTSTRAP_PASSWORD','DATABASE_URL','APP_MODE','DEMO_MODE'
$savedVariables=@{}
foreach ($name in $managedVariables) { $savedVariables[$name]=[Environment]::GetEnvironmentVariable($name,'Process') }
try {
  Set-Location -LiteralPath $PSScriptRoot
  $productionData=Join-Path $PSScriptRoot 'data'
  $productionDatabase=Join-Path $productionData 'factory.db'
  $productionAccess=Join-Path $productionData 'production-access.json'
  New-Item -ItemType Directory -Path $productionData -Force | Out-Null
  if ((Test-Path -LiteralPath $productionAccess) -or -not (Test-Path -LiteralPath $productionDatabase)) {
    if (Test-Path -LiteralPath $productionAccess) {
      $productionCredential=Get-Content -LiteralPath $productionAccess -Raw | ConvertFrom-Json
      $env:BOOTSTRAP_PASSWORD=$productionCredential.password
    } else {
      $productionBytes=New-Object byte[] 32
      [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($productionBytes)
      $env:BOOTSTRAP_PASSWORD=[Convert]::ToBase64String($productionBytes)
      @{username='supervisor';password=$env:BOOTSTRAP_PASSWORD;url="http://127.0.0.1:$Port/";notice='首次登入後請修改密碼並刪除這份初始密碼檔案'} | ConvertTo-Json | Set-Content -LiteralPath $productionAccess -Encoding UTF8
    }
    Write-Host "初始登入資料已保存至 $productionAccess（未納入 Git）。"
  }
  $env:DATABASE_URL='sqlite:///'+$productionDatabase.Replace('\','/')
  $env:APP_MODE='production'
  $env:DEMO_MODE='0'
  & (Join-Path $PSScriptRoot 'start.ps1') -Port $Port
}
finally {
  foreach ($name in $managedVariables) { [Environment]::SetEnvironmentVariable($name,$savedVariables[$name],'Process') }
}
