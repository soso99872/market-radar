"""正式回補前先抓兩天,確認舊格式解析得出來;任何一天抓不到或家數太少就失敗,不浪費好幾小時。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datetime import date
import backfill_old as B
for d in (date(2010, 1, 5), date(2013, 6, 3), date(2018, 1, 3)):
    day, msg = B.fetch_day(d)
    print(d, msg, flush=True)
    assert day and len(day["s"]) > 1000 and day["taiex"], "解析失敗:%s %s" % (d, msg)
    r = day["s"].get("2330"); print("  2330", r); assert r and r[4] > 0
