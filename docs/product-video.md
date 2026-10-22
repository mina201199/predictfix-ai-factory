# 展示影片與來源

面試官可在 [公開展示首頁](https://predictfix-mobile-demo.ruru0109lee.chatgpt.site) 直接播放實機影片、展開中文逐字稿，再依同頁指南操作互動展示；也可 [單獨開啟 MP4](https://predictfix-mobile-demo.ruru0109lee.chatgpt.site/media/predictfix-demo.mp4)，不需登入。

公開成品使用下表第一支實機影片：60.7 秒、1920×1080、H.264／AAC，含中文旁白與內嵌字幕。2026-10-21 已完成整支影音解碼檢查及瀏覽器播放驗證。影片逐字稿來自 `tools/demo-video/narration.json`；第二支影片的 SRT 不適用於這支實機影片。

目前保留兩種 60 秒影片，皆使用虛構展示資料：

| 成品 | 用途 | 來源 |
| --- | --- | --- |
| [實機操作影片](media/predictfix-demo.mp4) | 中文旁白、實際操作維修流程 | 原主線 `tools/demo-video/`，製作方法見其 README |
| 本機產品介紹 `artifacts/video/AI-Factory-60s-zh-TW.mp4` | 實際介面截圖剪輯與字幕，並非連續操作錄影 | 2026-10-08 本機產出；額外 MP4 與封面保留本機，不包含在 checkout |

產品介紹附有 [SRT 字幕](../artifacts/video/AI-Factory-60s-zh-TW.srt)、
本機封面 `artifacts/video/poster.jpg` 及 [分鏡](../artifacts/video/storyboard.json)。
不將錄影片段當成正式上線或真實工廠驗收證據。

`scripts/create_product_video.py` 保存當時的製作腳本。重製需要 Windows
微軟正黑體、NumPy、Pillow、額外的 `imageio-ffmpeg`，以及分鏡內指定的
`artifacts/` 截圖。這些原始截圖維持本機忽略檔案，乾淨 checkout 不含
全部輸入素材；直接觀看成品不需要安裝上述工具。

2026-10-20 Git 命令列未配置推送認證；改以已連接的 GitHub 工具交付，
但連接器傳送額外 MP4 時回傳 HTTP 500。未刪除原檔；版本管理納入字幕、
分鏡、腳本及 [本機成品雜湊](../artifacts/video/local-deliverables.json)。
原始 WAV、逐幕 JPG、編碼日誌及網站 tar.gz 保留本機，不作為交付來源。
容器不包含產品影片，避免增加應用程式映像大小。
