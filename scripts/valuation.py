"""個股本益比、股價淨值比、殖利率的每月快照(每月最後一個有資料的交易日),用來算每檔股票自己的歷史評價區間。

每月一個檔:data/valuation/YYYY-MM.json  {"date": 快照日, "s": {代號: [本益比, 淨值比, 殖利率%]}}
本益比為 None 代表虧損或無資料。

用法:
  python scripts/valuation.py backfill 2019-01   # 回補(已有的跳過)
  python scripts/valuation.py                     # 更新本月與上月
"""
import json
import os
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import history  # noqa: E402

DIR = os.path.join(history.ROOT, "data", "valuation")


def _num(s):
    v = history.num(s)
    return None if v is None or v <= 0 else round(v, 2)


def _parse(fields, data, out):
    try:
        i_pe, i_pb = fields.index("本益比"), fields.index("股價淨值比")
        i_y = fields.index("殖利率(%)")
    except ValueError:
        return
    for r in data:
        c = str(r[0]).strip()
        if history.STOCK.match(c):
            out[c] = [_num(r[i_pe]), _num(r[i_pb]), _num(r[i_y])]


def fetch(d):
    """回傳某日上市 + 上櫃評價;上市查無資料回傳 None。"""
    tw = history.get("https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?date=%s&selectType=ALL&response=json"
                     % d.strftime("%Y%m%d"))
    if tw.get("stat") != "OK" or not tw.get("data"):
        return None
    out = {}
    _parse(tw.get("fields") or [], tw["data"], out)
    time.sleep(history.PAUSE + 1)
    tp = history.get("https://www.tpex.org.tw/www/zh-tw/afterTrading/peQryDate?date=%s&response=json"
                     % d.strftime("%Y/%m/%d").replace("/", "%2F"))
    n_tw = len(out)
    for t in tp.get("tables", []):
        _parse(t.get("fields") or [], t.get("data") or [], out)
    if len(out) - n_tw < 100:   # 上櫃沒抓到,不要存半套
        return None
    return out


def month_end_candidates(y, m):
    d = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
    today = date.today()
    out = []
    while d.month == m and len(out) < 8:
        if d.weekday() < 5 and d < today:
            out.append(d)
        d -= timedelta(days=1)
    return out


def path_for(y, m):
    return os.path.join(DIR, "%04d-%02d.json" % (y, m))


def run_month(y, m, force=False):
    p = path_for(y, m)
    if os.path.exists(p) and not force:
        return False
    for d in month_end_candidates(y, m):
        s = fetch(d)
        time.sleep(history.PAUSE + 1)
        if s:
            os.makedirs(DIR, exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"date": d.isoformat(), "s": s}, f, separators=(",", ":"))
            print("valuation", d, len(s), file=sys.stderr, flush=True)
            return True
    print("no data", y, m, file=sys.stderr)
    return False


def load_all():
    """{(年, 月): {"date", "s"}}"""
    out = {}
    if os.path.isdir(DIR):
        for n in sorted(os.listdir(DIR)):
            if n.endswith(".json"):
                with open(os.path.join(DIR, n), encoding="utf-8") as f:
                    out[(int(n[:4]), int(n[5:7]))] = json.load(f)
    return out


if __name__ == "__main__":
    t = date.today()
    if len(sys.argv) >= 3 and sys.argv[1] == "backfill":
        y, m = map(int, sys.argv[2].split("-"))
        while (y, m) <= (t.year, t.month):
            run_month(y, m)
            y, m = (y, m + 1) if m < 12 else (y + 1, 1)
        print("done")
    else:
        # 本月(月中就用最近一個交易日,每次覆蓋)與上月
        prev = (t.year, t.month - 1) if t.month > 1 else (t.year - 1, 12)
        run_month(*prev)
        run_month(t.year, t.month, force=True)
