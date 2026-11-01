"""回補 2010–2018 的每日個股資料,格式與 scripts/history.py 完全相同(data/history/YYYY/YYYY-MM-DD.json.gz)。

和 history.fetch_day 的差別只有一個:證交所三大法人(T86)從 2012-05-02 才有,
更早的日子上市法人欄位記 0;上櫃法人 2019 年前查無資料,一律記 0(只影響「外資 20 日大賣」陷阱,該陷阱在這段期間不會觸發)。
其餘欄位、還原方式、存檔格式都沿用 history.py 的函式。

用法:python research/oos-2010/backfill_old.py 2014        # 回補整年(已有的跳過,可續跑)
"""
import os, sys, time, json
from datetime import date, timedelta
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
import history as H

T86_START = date(2012, 5, 2)
LOG = []


def fetch_day(d):
    ymd = d.strftime("%Y%m%d")
    slash = d.strftime("%Y/%m/%d").replace("/", "%2F")
    flows = {}
    if d >= T86_START:
        t86 = H.get("https://www.twse.com.tw/rwd/zh/fund/T86?date=%s&selectType=ALLBUT0999&response=json" % ymd)
        time.sleep(H.PAUSE)
        if t86.get("stat") == "OK" and t86.get("data"):
            for r in t86["data"]:
                c = r[0].strip()
                if H.STOCK.match(c):
                    flows[c] = (H.num(r[4]) + H.num(r[7]), H.num(r[10]), H.num(r[11]))
    mi = H.get("https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date=%s&type=ALLBUT0999&response=json" % ymd)
    time.sleep(H.PAUSE)
    if mi.get("stat") != "OK":
        return None, "MI_INDEX " + str(mi.get("stat"))
    tpq = H.get("https://www.tpex.org.tw/www/zh-tw/afterTrading/otc?date=%s&type=EW&response=json" % slash)
    time.sleep(1)
    tp3 = {}   # 上櫃法人(dailyTrade)2019 年前查無資料(探測 2008~2018 皆 0 筆),不抓

    px, taiex = {}, None
    for t in mi.get("tables", []):
        f = t.get("fields") or []
        if "證券代號" in f and "收盤價" in f:
            ix = {k: f.index(k) for k in ("證券代號", "證券名稱", "開盤價", "最高價", "最低價", "收盤價",
                                          "漲跌(+/-)", "漲跌價差", "成交金額")}
            for r in t["data"]:
                c, close = r[ix["證券代號"]].strip(), H.num(r[ix["收盤價"]])
                if not H.STOCK.match(c) or not close:
                    continue
                diff = H.num(r[ix["漲跌價差"]]) or 0.0
                if "-" in r[ix["漲跌(+/-)"]]:
                    diff = -diff
                prev = close - diff
                px[c] = [r[ix["證券名稱"]].strip(), H.num(r[ix["開盤價"]]) or close, H.num(r[ix["最高價"]]) or close,
                         H.num(r[ix["最低價"]]) or close, close, round(diff / prev * 100, 2) if prev else 0.0,
                         int(H.num(r[ix["成交金額"]]) or 0)]
        elif f and f[0] == "指數" and taiex is None:
            for r in t.get("data", []):
                if r[0].strip() == "發行量加權股價指數":
                    pct = H.num(r[4]) or 0.0
                    taiex = [H.num(r[1]), -abs(pct) if "-" in r[2] else pct]
    n_otc = 0
    for t in tpq.get("tables", []):
        for r in t.get("data", []):
            c, close = r[0].strip(), H.num(r[2])
            if not H.STOCK.match(c) or not close:
                continue
            diff = H.num(r[3]) or 0.0
            prev = close - diff
            px[c] = [r[1].strip(), H.num(r[4]) or close, H.num(r[5]) or close, H.num(r[6]) or close, close,
                     round(diff / prev * 100, 2) if prev else 0.0, int(H.num(r[8]) or 0)]
            n_otc += 1
    tables = tp3.get("tables") or [{}]
    for r in tables[0].get("data", []):
        c = r[0].strip()
        if H.STOCK.match(c):
            flows[c] = (H.num(r[10]), H.num(r[13]), H.num(r[22]))
    if not px:
        return None, "no prices"
    s = {}
    for c, row in px.items():
        fo, tr, de = flows.get(c, (0, 0, 0))
        s[c] = row + [int(fo or 0), int(tr or 0), int(de or 0)]
    return {"date": d.isoformat(), "taiex": taiex, "s": s}, "ok twse=%d otc=%d flows=%d" % (len(px) - n_otc, n_otc, len(flows))


def main(year):
    d, stop = date(year, 12, 31), date(year, 1, 1)
    out_log = os.path.join(os.path.dirname(os.path.abspath(__file__)), "log-%d.txt" % year)
    with open(out_log, "a", encoding="utf-8") as lg:
        while d >= stop:
            iso = d.isoformat()
            if d.weekday() < 5 and not os.path.exists(H.path_for(iso)):
                for attempt in range(3):
                    try:
                        day, msg = fetch_day(d)
                        break
                    except Exception as e:  # noqa: BLE001
                        day, msg = None, "ERR %s" % e
                        time.sleep(30)
                if day:
                    H.save_day(day)
                lg.write("%s %s\n" % (iso, msg)); lg.flush()
                print(iso, msg, flush=True)
                time.sleep(H.PAUSE)
            d -= timedelta(days=1)


if __name__ == "__main__":
    main(int(sys.argv[1]))
