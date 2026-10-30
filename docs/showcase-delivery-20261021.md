# 2026-10-21 對外面試展示交付

## 分享入口

- [公開面試展示：影片、逐字稿、三分鐘指南與互動工作台](https://predictfix-mobile-demo.ruru0109lee.chatgpt.site)
- [實機影片 MP4](https://predictfix-mobile-demo.ruru0109lee.chatgpt.site/media/predictfix-demo.mp4)
- [操作說明與本機準備](demo-guide.md)

網站開放任何持有連結者瀏覽，不需登入、安裝或 API Key。所有內容皆為虛構展示資料，未連接正式資料庫、現場設備或即時 AI。

## 發布識別

| 項目 | 值 |
| --- | --- |
| Sites 版本 | 3 |
| Sites project | `appgprj_6acf905600148191889ba3c3491ddc86` |
| Sites source commit | `0d9fa76f2a7abe506057beef891f2bb9b9605d02` |
| Deployment | `appgdep_6ad7a039f24c8191bc8df3577b1bf1d3` |
| Deployment status | `succeeded` |
| 網站存取 | `public`，revision 2 |
| MP4 SHA-256 | `cb3e7232bf2ca505b587c390e14624e38178a585027a1a04d4780455fd26a0ce` |

公開網站原始碼由 Sites 正式來源庫管理，發布封裝與上述提交一致。專案中的 `sites/predictfix-mobile/dist/` 保留 FastAPI 內嵌與本機預覽使用的輕量工作台；公開版另加入面試首頁、影片及逐字稿，沒有改動後端行為或內嵌資產路由。

## 已驗證

| 檢查 | 結果 |
| --- | --- |
| 未登入公開存取 | 使用新的 HTTP 客戶端逐一請求，未提供 Cookie、Authorization 或存取繞過權杖；首頁、JS、CSS、封面與 MP4 全部 HTTP 200，未導向登入頁。 |
| 部署內容 | JS、CSS、封面、影片與封裝原始檔逐位元一致；HTML 僅多出 Cloudflare 注入的腳本，排除此附加項後一致。 |
| 影音完整性 | H.264／AAC，1920×1080，30 fps，60.7 秒；全片影音解碼 exit 0，共 1821 幀。 |
| 公開網站播放 | 瀏覽器播放至 60.7 秒，`ended=true`，無媒體錯誤；字幕內嵌在影片中，頁面另有完整旁白逐字稿。 |
| 操作指南 | 依五步指南完成來源核對、核准、資格派工、工程師紀錄、驗收失敗阻擋、改回通過後提交、主管結案、案例發布。 |
| 狀態保存與重設 | 案例在重新整理後仍保留；重設先顯示確認視窗，確認後回到初始展示資料。 |
| 響應式版面 | 桌面、390 px 及 320 px 寬度預覽通過；手機版無橫向溢出，五個導覽入口可見。 |
| JavaScript | `node --check` 通過；瀏覽器檢查未見應用程式錯誤。 |

上述操作流程在發布前的相同來源版本完成，發布後另驗證匿名存取、資產一致與全片播放。手機檢查使用瀏覽器視窗尺寸模擬，沒有宣稱實體 iOS／Android 裝置驗收。

目前影片託管對 Range 請求回傳整個檔案（HTTP 200），未提供 HTTP 206 分段回應；首次載入約 13 MB，已驗證完整循序播放。頁面提供單獨 MP4 連結與逐字稿作為替代觀看方式。

## 與既有回歸紀錄的關係

PR #10 已合併至 main，提交為 `9108e329066dc2256e91021556c36271d2a58b10`。
[合併後 CI](https://github.com/mina201199/predictfix-ai-factory/actions/runs/39455295043) 的 tests、container、postgres 三個 job 通過，其中 pytest 為 161 項、零失敗、零錯誤、零跳過。

此紀錄屬於既有後端版本；本次對外交付變更是 Sites 網站與專案文件。公開互動版的瀏覽器檢查不取代後端權限或現場設備驗收。
