# 盤前雷達 — 每日報告產生指南

這份文件是給每天 07:30(台北時間)自動執行的排程 agent 看的。網站 `index.html` 會讀 `data/index.json` 和 `data/YYYY-MM-DD.json` 來顯示報告。

## 每日流程

1. 用 `TZ=Asia/Taipei date +%F` 取得今天日期(以下稱 DATE)。
2. 讀行情:GitHub Actions 每個交易日台北 06:15 會先把行情抓好放在 `data/quotes.json`(雲端排程的網路連不到 Yahoo 與證交所,所以不要自己跑 fetch_quotes.py)。
   - 確認 `fetched_at` 是今天(台北時間);是的話,把它的 `markets` 與 `tsm_adr_premium_pct` 原樣放進報告,`failed` 裡的代號改用網路搜尋補(查不到就省略該項,不可捏造)。
   - 如果 `fetched_at` 不是今天,先 `git pull origin main` 再看一次;還是舊的,就全部改用網路搜尋取得收盤數字,`spark` 省略,並在 sources 註明來源。
   - 台股前一交易日三大法人金額讀 `data/flows/market.json`(證交所官方數字,date 要是前一交易日),直接填進 `tw_flows` 的 foreign / trust / dealer,不要用新聞上的數字取代。
   - `data/sectors/latest.json` 有各板塊近 1/5/20 日法人買賣超(`themes[].w`)與資金連續流入流出天數(`streak`),可以拿來寫 `sector_watch` 與台股相關的 key_points;引用時以這份資料為準。
3. 用 WebSearch / WebFetch 研究以下內容(優先用 Reuters、Bloomberg、CNBC、WSJ、鉅亨網、經濟日報、工商時報、MoneyDJ、證交所、期交所):
   - 隔夜美股收盤重點:主要漲跌原因、領漲/領跌族群、重要個股消息。
   - 今天與本週的經濟日曆(美國與台灣):事件、台北時間、市場預期值、前值。Investing.com、Trading Economics、Forex Factory 都可以。
   - 今天與近幾天的重要財報(美股大型股、台股權值股、法說會)。
   - 台股籌碼的其他部分:外資台指期未平倉淨口數、融資餘額增減(三大法人金額已在 `data/flows/market.json`)。
   - Fed 官員談話、台灣央行、關稅與出口管制、地緣政治等政策事件。
4. 寫入 `data/DATE.json`(格式見下方),並把 DATE 加到 `data/index.json` 的 `dates` 陣列最前面(不重複,新到舊排序)。若 `data/sample.json` 還存在且 `data/index.json` 有 `"sample"`,刪掉 sample 檔並從 dates 移除。
5. `python scripts/validate.py data/DATE.json`,不通過就修正到通過為止。
6. 只提交你寫的報告檔:`git add data/DATE.json data/index.json && git commit -m "晨報 DATE"`(若有刪 sample 也一併 add)。不要改動 `data/quotes.json`、`data/flows/`、`data/sectors/`,那些由 GitHub Actions 維護。
7. `git pull --rebase origin main && git push origin HEAD:main`(GitHub Actions 可能剛推過資料,所以要先 rebase)。

## 撰寫原則

- 全部用**繁體中文**,台北時間。
- **不可捏造數字。** 查不到的預期值寫 `null`,網站會顯示「—」。每個重點都要能在 `sources` 找到出處。
- 影響說明要寫成**條件式**,並指出預期差:例如「CPI 高於 2.9% 預期 → 降息預期降溫、殖利率上升 → 科技成長股承壓;低於預期則相反」。
- 說明**傳導路徑**:事件 → 利率/匯率/資金 → 哪些產業、哪些市場。台股要特別寫出和美股、台積電 ADR、新台幣、外資動向的連動。
- 不給個股的買賣建議、目標價或進出場點。可以說「哪些族群可能受影響、往哪個方向」。
- `key_points` 寫 4–7 則,依重要性排序;`headline` 一句話、40 字以內。
- `sentiment` 是你對今天開盤風險情緒的綜合判斷:score -2(明顯偏空)到 +2(明顯偏多),label 對應 偏空/中性/偏多,summary 一兩句說明理由。

## JSON 格式

```jsonc
{
  "date": "2026-10-07",
  "generated_at": "2026-10-07T07:42+08:00",
  "headline": "一句話總結今天最重要的事",
  "sentiment": { "label": "偏多", "score": 1, "summary": "理由" },
  "markets": [ /* 直接沿用 fetch_quotes.py 的 markets */
    { "group": "美股指數", "items": [
      { "symbol": "^SOX", "name": "費城半導體", "unit": "", "decimals": 2,
        "last": 5240.12, "change": 92.6, "change_pct": 1.8, "as_of": "2026-10-06",
        "spark": [5100, 5150, 5240.12] } ] }
  ],
  "tsm_adr_premium_pct": 18.4,          // 沒有就 null
  "key_points": [
    { "title": "標題", "detail": "2–4 句說明發生什麼、為什麼重要、怎麼傳導",
      "impact": "利多 | 利空 | 中性 | 視數據而定",
      "market": "美股 | 台股 | 台美股",
      "sectors": ["半導體", "AI 伺服器"] }
  ],
  "calendar": [
    { "date": "2026-10-07", "time": "20:30", "region": "美 | 台 | 其他",
      "event": "美國 9 月 CPI 年增率", "forecast": "2.9%", "previous": "3.0%",
      "importance": "高 | 中 | 低",
      "impact_note": "高於預期 → …;低於預期 → …" }
  ],
  "earnings": [
    { "region": "美 | 台", "ticker": "NVDA", "name": "輝達", "date": "2026-10-07",
      "timing": "盤前 | 盤後 | 法說會 HH:MM", "note": "市場關注點" }
  ],
  "tw_flows": {                          // 前一交易日;查不到的欄位填 null
    "date": "2026-10-06",
    "foreign": -125.3, "trust": 18.2, "dealer": -6.1,   // 億元,正數=買超
    "foreign_futures_net_oi": -21500,                    // 口,正數=淨多單
    "margin_change": 12.4,                               // 億元
    "note": "一兩句解讀"
  },
  "sector_watch": [
    { "sector": "半導體", "view": "偏多 | 中性 | 偏空", "reason": "一句話" }
  ],
  "risks": ["今天需要留意的風險,一句一則"],
  "sources": [ { "title": "來源標題", "url": "https://..." } ]
}
```
