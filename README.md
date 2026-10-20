# 盤前雷達

台美股盤前晨報網站。雲端排程每個交易日 06:00(台北時間)依 `REPORT_GUIDE.md` 產生 `data/YYYY-MM-DD.json` 並 push,GitHub Pages 自動更新。

- `index.html`:網站(純靜態,無需建置)
- `data/`:每日報告與 `index.json` 日期索引
- `scripts/fetch_quotes.py`:用 yfinance 抓行情
- `scripts/validate.py`:檢查報告格式

本機預覽:`python -m http.server` 後開 http://localhost:8000

## 板塊資金頁(sectors.html)

- `.github/workflows/market-data.yml` 每個交易日台北 05:10 與 17:40 執行:抓行情到 `data/quotes.json`、抓證交所與櫃買中心的個股三大法人買賣超,算出 `data/sectors/latest.json` 與 `data/flows/market.json`。
- 板塊分類在 `data/sectors/themes.json`,直接編輯代號清單即可(推上去會自動重算);名稱以交易所資料為準。
- 金額 = 買賣超股數 × 當日收盤價(估算)。

## 起漲雷達頁(radar.html)

- `scripts/signals.py` 由同一個 workflow 執行,依序產生落後補漲(`scripts/laggard.py` → `data/radar/laggard.json`)與起漲雷達名單(`scripts/radar.py` → `data/radar/latest.json`)。laggard 失敗只印警告,radar 照常輸出。
- 題材分類在 `data/sectors/topics.json`(比 `themes.json` 細,一檔可屬多個題材);改完跑 `python scripts/topics.py check` 驗證格式與 4★ 以上覆蓋率。
- 條件標籤:`latest.json` 每檔有 `tags`,判定規則寫在最上層 `tag_defs`(網頁「?」直接顯示這段文字)。
- 網頁篩選器的自訂篩選存在瀏覽器 `localStorage`(`radar.filters`),3 步驟引導的收合狀態存 `radar.guide`。
- 測試:`python -m unittest discover -s tests -v`。

## Telegram 推播(scripts/notify.py)

- 收盤後那次(17:40)或手動執行 workflow 時,推送新進 4★/5★ 與落後補漲新名單。需要 repo secrets:`TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`,選填 `TELEGRAM_THREAD_ID`(群組話題)。沒設定就略過,不會讓排程失敗。
- 同一資料日只推一次,狀態記在 `data/radar/notify_state.json`。
- 本機預覽訊息(不送出、不改狀態檔):`python scripts/notify.py --dry-run`。
