"""上市櫃公司月營收歷史(公開資訊觀測站彙總表)。

每月一個檔:data/revenue/YYYY-MM.json  {代號: [當月營收(千元), 年增%, 月增%]}
營收在次月 10 日前公告,回測時視為次月 11 日起才知道。

用法:
  python scripts/revenue.py backfill 2022-01   # 回補到指定月份(已有的跳過)
  python scripts/revenue.py                     # 更新最近 3 個月
"""
import html
import json
import os
import re
import sys
import time
import urllib.request
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import history  # noqa: E402

DIR = os.path.join(history.ROOT, "data", "revenue")
ROW = re.compile(r"<tr[^>]*>\s*<td[^>]*>\s*(\d{4})\s*</td>\s*<td[^>]*>[^<]*</td>((?:\s*<td[^>]*>[^<]*</td>){5})", re.I)
CELL = re.compile(r"<td[^>]*>([^<]*)</td>", re.I)


def fetch_month(y, m):
    out = {}
    for mkt in ("sii", "otc"):
        for kind in ("0", "1"):   # 0 = 國內公司,1 = 外國企業(KY)
            url = "https://mopsov.twse.com.tw/nas/t21/%s/t21sc03_%d_%d_%s.html" % (mkt, y - 1911, m, kind)
            try:
                req = urllib.request.Request(url, headers=history.UA)
                with urllib.request.urlopen(req, timeout=40) as r:
                    t = r.read().decode("big5", "replace")
            except Exception as e:  # noqa: BLE001
                print("skip", url, e, file=sys.stderr)
                continue
            for code, cells in ROW.findall(t):
                v = [history.num(html.unescape(x)) for x in CELL.findall(cells)]
                # 當月營收、上月營收、去年當月營收、上月比較增減%、去年同月增減%
                if v and v[0] is not None:
                    out[code] = [int(v[0]), None if v[4] is None else round(v[4], 2), None if v[3] is None else round(v[3], 2)]
            time.sleep(2)
    return out


def path_for(y, m):
    return os.path.join(DIR, "%04d-%02d.json" % (y, m))


def months_back(y, m, stop):
    while (y, m) >= stop:
        yield y, m
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)


def last_month():
    t = date.today()
    return (t.year, t.month - 1) if t.month > 1 else (t.year - 1, 12)


def run(stop, refresh=0):
    os.makedirs(DIR, exist_ok=True)
    n = 0
    for i, (y, m) in enumerate(months_back(*last_month(), stop)):
        p = path_for(y, m)
        if os.path.exists(p) and i >= refresh:
            continue
        d = fetch_month(y, m)
        if len(d) < 500:   # 尚未公布完整
            print("incomplete", y, m, len(d), file=sys.stderr)
            continue
        with open(p, "w", encoding="utf-8") as f:
            json.dump(d, f, separators=(",", ":"))
        n += 1
        print("revenue", y, m, len(d), file=sys.stderr, flush=True)
    return n


def load_all():
    """{(年, 月): {代號: [營收, 年增, 月增]}}"""
    out = {}
    if os.path.isdir(DIR):
        for n in sorted(os.listdir(DIR)):
            if n.endswith(".json"):
                with open(os.path.join(DIR, n), encoding="utf-8") as f:
                    out[(int(n[:4]), int(n[5:7]))] = json.load(f)
    return out


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "backfill":
        y, m = map(int, sys.argv[2].split("-"))
        print("done", run((y, m)))
    else:
        # 每日排程:補最近 3 個月(當月營收陸續公布,前 2 個月重抓一次確保完整)
        y, m = last_month()
        stop = (y, m - 2) if m > 2 else (y - 1, m + 10)
        print("done", run(stop, refresh=2))
