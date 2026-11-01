"""回補 2004–2009 每日個股資料(格式同 data/history)。依 PROTOCOL.md:log 只記筆數,不印價格。
和 oos-2010/backfill_old.py 的差別:
  - 2009 年前 MI_INDEX 沒有指數表,加權指數改從 FMTQIK(每月一次)取,寫進同一個 taiex 欄位。
  - 上櫃行情 2007 年中以前查無資料(探測結果),那段只有上市股票。
用法:python research/oos-pre2010/backfill_pre.py 2006"""
import os, sys, time
from datetime import date, timedelta
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "scripts")); sys.path.insert(0, os.path.join(HERE, "..", "oos-2010"))
import history as H
import backfill_old as B

def taiex_month(y, m, cache={}):
    k = (y, m)
    if k not in cache:
        q = H.get("https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date=%d%02d01&response=json" % (y, m)); time.sleep(H.PAUSE)
        out = {}
        if q.get("stat") == "OK":
            f = q["fields"]; i_d, i_c, i_x = f.index("日期"), f.index("發行量加權股價指數"), f.index("漲跌點數")
            for r in q.get("data") or []:
                yy, mm, dd = r[i_d].strip().split("/"); c, x = H.num(r[i_c]), H.num(r[i_x]) or 0.0
                if c: out[date(int(yy) + 1911, int(mm), int(dd)).isoformat()] = [c, round(x / (c - x) * 100, 2) if c - x else 0.0]
        cache[k] = out
    return cache[k]

def main(year):
    d, stop = date(year, 12, 31), date(year, 1, 1)
    log = open(os.path.join(HERE, "log-%d.txt" % year), "a", encoding="utf-8")
    while d >= stop:
        iso = d.isoformat()
        if d.weekday() < 5 and not os.path.exists(H.path_for(iso)):
            day, msg = None, ""
            for attempt in range(3):
                try:
                    day, msg = B.fetch_day(d); break
                except Exception as e:  # noqa: BLE001
                    day, msg = None, "ERR %s" % str(e)[:80]; time.sleep(30)
            if day:
                if day.get("taiex") is None:
                    try: day["taiex"] = taiex_month(d.year, d.month).get(iso)
                    except Exception as e: msg += " taiexERR"  # noqa: BLE001
                    msg += " taiex=%s" % ("fmtqik" if day["taiex"] else "none")
                H.save_day(day)
            log.write("%s %s\n" % (iso, msg)); log.flush(); print(iso, msg, flush=True)
            time.sleep(H.PAUSE)
        d -= timedelta(days=1)

if __name__ == "__main__":
    main(int(sys.argv[1]))
