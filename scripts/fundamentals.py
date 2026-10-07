"""個股基本面快照:本益比、股價淨值比、殖利率(最新交易日)與最新月營收。

輸出 data/fundamentals/latest.json
  {"date", "rev_month", "val": {代號: [本益比, 淨值比, 殖利率%]}, "rev": {代號: [年增%, 月增%, 累計年增%]}}
本益比為 None 代表虧損或無資料。只有最新一期,沒有歷史,所以這些數字只供參考、沒有回測。
"""
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import history  # noqa: E402

OUT = os.path.join(history.ROOT, "data", "fundamentals", "latest.json")


def num(s):
    v = history.num(s)
    return None if v is None else round(v, 2)


def valuations(iso):
    d = datetime.strptime(iso, "%Y-%m-%d")
    out = {}
    tw = history.get("https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?date=%s&selectType=ALL&response=json"
                     % d.strftime("%Y%m%d"))
    f = tw.get("fields") or []
    if tw.get("stat") == "OK" and "本益比" in f:
        i_pe, i_pb, i_y = f.index("本益比"), f.index("股價淨值比"), f.index("殖利率(%)")
        for r in tw["data"]:
            c = r[0].strip()
            if history.STOCK.match(c):
                out[c] = [num(r[i_pe]), num(r[i_pb]), num(r[i_y])]
    time.sleep(history.PAUSE)
    tp = history.get("https://www.tpex.org.tw/www/zh-tw/afterTrading/peQryDate?date=%s&response=json"
                     % d.strftime("%Y/%m/%d").replace("/", "%2F"))
    for t in tp.get("tables", []):
        f = t.get("fields") or []
        if "本益比" not in f:
            continue
        i_pe, i_pb, i_y = f.index("本益比"), f.index("股價淨值比"), f.index("殖利率(%)")
        for r in t.get("data", []):
            c = r[0].strip()
            if history.STOCK.match(c):
                out[c] = [num(r[i_pe]), num(r[i_pb]), num(r[i_y])]
    return out


def revenue():
    out, ym = {}, None
    for url in ("https://openapi.twse.com.tw/v1/opendata/t187ap05_L",
                "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"):
        for r in history.get(url):
            c = str(r.get("公司代號", "")).strip()
            if not history.STOCK.match(c):
                continue
            ym = ym or r.get("資料年月")
            out[c] = [num(r.get("營業收入-去年同月增減(%)")), num(r.get("營業收入-上月比較增減(%)")),
                      num(r.get("累計營業收入-前期比較增減(%)"))]
        time.sleep(1)
    if ym and len(ym) == 5:   # 民國年月 11508 → 2026-08
        ym = "%d-%s" % (int(ym[:3]) + 1911, ym[3:])
    return ym, out


def main():
    ds = history.all_dates()
    if not ds:
        sys.exit("沒有歷史資料")
    iso = ds[-1]
    val = valuations(iso)
    ym, rev = revenue()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"date": iso, "rev_month": ym, "val": val, "rev": rev}, f, ensure_ascii=False, separators=(",", ":"))
    print("fundamentals", iso, "val", len(val), "rev", ym, len(rev))


if __name__ == "__main__":
    main()
