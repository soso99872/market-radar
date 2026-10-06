"""抓取台美股行情,輸出 markets 區塊 JSON 到 stdout。

用法: pip install yfinance && python scripts/fetch_quotes.py > /tmp/quotes.json
失敗的代號會放進 "failed",由排程 agent 改用網路搜尋補齊。
"""
import json
import sys
from datetime import datetime, timezone, timedelta

GROUPS = [
    ("美股指數", [
        ("^GSPC", "S&P 500", 2, ""),
        ("^IXIC", "那斯達克", 2, ""),
        ("^DJI", "道瓊工業", 2, ""),
        ("^SOX", "費城半導體", 2, ""),
    ]),
    ("台股", [
        ("^TWII", "加權指數", 2, ""),
        ("^TWOII", "櫃買指數", 2, ""),
        ("2330.TW", "台積電", 1, "元"),
        ("TSM", "台積電 ADR", 2, "USD"),
    ]),
    ("權值股", [
        ("NVDA", "輝達", 2, "USD"),
        ("AAPL", "蘋果", 2, "USD"),
        ("MSFT", "微軟", 2, "USD"),
        ("2317.TW", "鴻海", 1, "元"),
        ("2454.TW", "聯發科", 0, "元"),
    ]),
    ("利率・匯率", [
        ("^TNX", "美 10 年債殖利率", 3, "%"),
        ("DX-Y.NYB", "美元指數", 2, ""),
        ("TWD=X", "美元/新台幣", 3, ""),
        ("JPY=X", "美元/日圓", 2, ""),
    ]),
    ("商品・情緒", [
        ("^VIX", "VIX 恐慌指數", 2, ""),
        ("CL=F", "WTI 原油", 2, "USD"),
        ("GC=F", "黃金", 1, "USD"),
        ("BTC-USD", "比特幣", 0, "USD"),
    ]),
]


def main():
    import yfinance as yf

    symbols = [s for _, items in GROUPS for s, *_ in items]
    hist = yf.download(symbols, period="1mo", interval="1d", group_by="ticker",
                       auto_adjust=False, progress=False, threads=True)

    markets, failed, closes = [], [], {}
    for group, items in GROUPS:
        out = []
        for sym, name, decimals, unit in items:
            try:
                s = hist[sym]["Close"].dropna()
                if len(s) < 2:
                    raise ValueError("no data")
                last, prev = float(s.iloc[-1]), float(s.iloc[-2])
                closes[sym] = last
                out.append({
                    "symbol": sym, "name": name, "unit": unit, "decimals": decimals,
                    "last": round(last, 4), "change": round(last - prev, 4),
                    "change_pct": round((last / prev - 1) * 100, 2),
                    "as_of": s.index[-1].strftime("%Y-%m-%d"),
                    "spark": [round(float(v), 4) for v in s.iloc[-15:]],
                })
            except Exception as e:  # noqa: BLE001
                failed.append({"symbol": sym, "name": name, "error": str(e)[:120]})
        markets.append({"group": group, "items": out})

    # ADR 溢價:1 股 ADR = 5 股台積電
    premium = None
    if all(k in closes for k in ("TSM", "2330.TW", "TWD=X")):
        premium = round((closes["TSM"] * closes["TWD=X"] / 5 / closes["2330.TW"] - 1) * 100, 2)

    tz = timezone(timedelta(hours=8))
    json.dump({
        "fetched_at": datetime.now(tz).isoformat(timespec="minutes"),
        "markets": markets,
        "tsm_adr_premium_pct": premium,
        "failed": failed,
    }, sys.stdout, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
