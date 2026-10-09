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
