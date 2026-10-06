# 盤前雷達

台美股盤前晨報網站。雲端排程每個交易日 07:30(台北時間)依 `REPORT_GUIDE.md` 產生 `data/YYYY-MM-DD.json` 並 push,GitHub Pages 自動更新。

- `index.html`:網站(純靜態,無需建置)
- `data/`:每日報告與 `index.json` 日期索引
- `scripts/fetch_quotes.py`:用 yfinance 抓行情
- `scripts/validate.py`:檢查報告格式

本機預覽:`python -m http.server` 後開 http://localhost:8000
