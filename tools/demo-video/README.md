# Vulkrion AI Demo 影片工具

產出 `output/predictfix-demo.mp4`、`output/predictfix-preview.gif` 與 `output/predictfix-thumbnail.png`。旁白與分鏡見 [narration.md](narration.md)。工具位於主專案的 `tools/demo-video/`，會讀取專案根目錄的 `demo-measurements.csv`。

## 安裝

先依主專案 README 建立後端 `.venv` 並設定本機模型。在專案根目錄執行 PowerShell：

```powershell
python -m venv tools/demo-video/.venv
& tools/demo-video/.venv/Scripts/python.exe -m pip install -r tools/demo-video/requirements.txt
& tools/demo-video/.venv/Scripts/python.exe -m playwright install chromium
```

ffmpeg 由 `imageio-ffmpeg` 套件提供，不需指定個人電腦的安裝路徑。`edge-tts` 產生旁白時需要網路連線。

## 重新錄製

1. 依主專案 README 啟動本機模型服務，預期位址為 `http://127.0.0.1:8081`。
2. 在專案根目錄的另一個 PowerShell 視窗，以獨立展示資料庫啟動後端：

```powershell
$env:APP_MODE = 'demo'
$env:DEMO_MODE = '1'
$env:LLM_PROVIDER = 'llamacpp'
$env:LOCAL_LLM_MODEL = 'Qwen3-0.6B-Q8_0'
$env:LLM_URL = 'http://127.0.0.1:8081'
$videoDatabase = Join-Path (Get-Location) ('data/video-demo-' + [guid]::NewGuid().ToString('N') + '.db')
$env:DATABASE_URL = 'sqlite:///' + $videoDatabase.Replace('\', '/')
& .venv/Scripts/python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8082
```

每次重錄使用新的展示資料庫，保留原有資料。此模式只供本機展示。

3. 在專案根目錄的第三個 PowerShell 視窗執行：

```powershell
& tools/demo-video/.venv/Scripts/python.exe tools/demo-video/prepare_video_data.py
& tools/demo-video/.venv/Scripts/python.exe tools/demo-video/tts.py
& tools/demo-video/.venv/Scripts/python.exe tools/demo-video/record.py
& tools/demo-video/.venv/Scripts/python.exe tools/demo-video/assemble.py
```

每一步成功後再執行下一步。`prepare_video_data.py` 只接受明確啟用的本機 demo 服務；`record.py` 會新增展示工單與案例。結果位於 `tools/demo-video/output/`，暫存檔位於 `tools/demo-video/build/`，兩者均不加入 Git。

## 調整與驗證

- 修改旁白：編輯 `narration.json` 後重新執行 `tts.py`、`record.py`、`assemble.py`。
- 修改鏡頭：編輯 `record.py`；片頭與片尾位於 `cards/`。
- 驗證資料準備與專案路徑：安裝主專案測試依賴後，在專案根目錄執行 `.venv/Scripts/python.exe -m pytest tools/demo-video/tests -q`，應顯示 3 passed。

本次搬移已驗證資料準備、相對路徑與 ffmpeg 啟動；沒有重新錄製完整影片。
