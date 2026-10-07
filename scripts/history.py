"""台股每日個股歷史資料(上市 + 上櫃):開高低收、成交金額、三大法人買賣超股數。

每個交易日存一個檔:data/history/YYYY/YYYY-MM-DD.json.gz
  {"date", "taiex": [收盤, 漲跌%], "s": {代號: [名稱, 開, 高, 低, 收, 漲跌%, 成交金額(元), 外資, 投信, 自營商]}}
外資含外資自營商;法人數字單位為股。

用法:
  python scripts/history.py backfill 2023-10-01   # 回補到指定日期(新到舊,已有的跳過,可中斷續跑)
其他腳本用 load_days() / update_recent() 讀寫。
"""
import gzip
import json
import os
import re
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIST = os.path.join(ROOT, "data", "history")
CLOSED = os.path.join(HIST, "closed.json")
TZ = timezone(timedelta(hours=8))
STOCK = re.compile(r"^[1-9]\d{3}$")   # 只收一般股票,排除 ETF、權證
UA = {"User-Agent": "Mozilla/5.0 (market-radar; +https://github.com/soso99872/market-radar)"}
PAUSE = 3.5   # 證交所建議每 5 秒不超過 3 次請求

# 欄位索引
NAME, OPEN, HIGH, LOW, CLOSE, CHG, VALUE, FOREIGN, TRUST, DEALER = range(10)


def get(url):
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            if attempt == 3:
                raise
            wait = 20 * (attempt + 1)
            print("retry in %ds: %s %s" % (wait, url, e), file=sys.stderr)
            time.sleep(wait)


def num(s):
    s = str(s).replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def fetch_day(d):
    """回傳某日資料;非交易日(或尚未公布)回傳 None。"""
    ymd = d.strftime("%Y%m%d")
    slash = d.strftime("%Y/%m/%d").replace("/", "%2F")

    t86 = get("https://www.twse.com.tw/rwd/zh/fund/T86?date=%s&selectType=ALLBUT0999&response=json" % ymd)
    if t86.get("stat") != "OK" or not t86.get("data"):
        return None
    time.sleep(PAUSE)
    mi = get("https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date=%s&type=ALLBUT0999&response=json" % ymd)
    time.sleep(PAUSE)
    tp3 = get("https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade?type=Daily&sect=EW&date=%s&response=json" % slash)
    time.sleep(1)
    tpq = get("https://www.tpex.org.tw/www/zh-tw/afterTrading/otc?date=%s&type=EW&response=json" % slash)
    time.sleep(1)

    px, taiex = {}, None
    for t in mi.get("tables", []):
        f = t.get("fields") or []
        if "證券代號" in f and "收盤價" in f:
            ix = {k: f.index(k) for k in ("證券代號", "證券名稱", "開盤價", "最高價", "最低價", "收盤價",
                                          "漲跌(+/-)", "漲跌價差", "成交金額")}
            for r in t["data"]:
                c, close = r[ix["證券代號"]].strip(), num(r[ix["收盤價"]])
                if not STOCK.match(c) or not close:
                    continue
                diff = num(r[ix["漲跌價差"]]) or 0.0
                if "-" in r[ix["漲跌(+/-)"]]:
                    diff = -diff
                prev = close - diff
                px[c] = [r[ix["證券名稱"]].strip(), num(r[ix["開盤價"]]) or close, num(r[ix["最高價"]]) or close,
                         num(r[ix["最低價"]]) or close, close, round(diff / prev * 100, 2) if prev else 0.0,
                         int(num(r[ix["成交金額"]]) or 0)]
        elif f and f[0] == "指數" and taiex is None:
            for r in t.get("data", []):
                if r[0].strip() == "發行量加權股價指數":
                    pct = num(r[4]) or 0.0
                    taiex = [num(r[1]), -abs(pct) if "-" in r[2] else pct]
    for t in tpq.get("tables", []):
        for r in t.get("data", []):
            c, close = r[0].strip(), num(r[2])
            if not STOCK.match(c) or not close:
                continue
            diff = num(r[3]) or 0.0
            prev = close - diff
            px[c] = [r[1].strip(), num(r[4]) or close, num(r[5]) or close, num(r[6]) or close, close,
                     round(diff / prev * 100, 2) if prev else 0.0, int(num(r[8]) or 0)]

    # 上市先公布、上櫃還沒出來時先不存,等下一次排程,避免把上櫃當成沒成交、法人為 0 存進歷史
    if not any(STOCK.match(r[0].strip()) for t in tpq.get("tables", []) for r in t.get("data", [])) \
            or not (tp3.get("tables") or [{}])[0].get("data"):
        print("TPEx not ready for", d, file=sys.stderr)
        return None

    flows = {}
    for r in t86["data"]:
        c = r[0].strip()
        if STOCK.match(c):
            flows[c] = (num(r[4]) + num(r[7]), num(r[10]), num(r[11]))
    tables = tp3.get("tables") or [{}]
    for r in tables[0].get("data", []):
        c = r[0].strip()
        if STOCK.match(c):
            flows[c] = (num(r[10]), num(r[13]), num(r[22]))

    s = {}
    for c, row in px.items():
        fo, tr, de = flows.get(c, (0, 0, 0))
        s[c] = row + [int(fo or 0), int(tr or 0), int(de or 0)]
    return {"date": d.isoformat(), "taiex": taiex, "s": s}


def path_for(iso):
    return os.path.join(HIST, iso[:4], iso + ".json.gz")


def save_day(day):
    p = path_for(day["date"])
    os.makedirs(os.path.dirname(p), exist_ok=True)
    # mtime=0 讓同樣內容產生同樣的檔案,避免 git 出現無意義的變更
    with open(p, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as f:
        f.write(json.dumps(day, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def load_day(iso):
    with gzip.open(path_for(iso), "rt", encoding="utf-8") as f:
        return json.load(f)


def all_dates():
    out = []
    for y in sorted(os.listdir(HIST)) if os.path.isdir(HIST) else []:
        if y.isdigit():
            out += [n[:10] for n in os.listdir(os.path.join(HIST, y)) if n.endswith(".json.gz")]
    return sorted(out)


def load_days(n=None):
    """讀最近 n 個交易日(None = 全部),舊 → 新。"""
    ds = all_dates()
    if n:
        ds = ds[-n:]
    return [load_day(x) for x in ds]


def _closed():
    try:
        with open(CLOSED, encoding="utf-8") as f:
            return set(json.load(f))
    except FileNotFoundError:
        return set()


def _save_closed(closed):
    os.makedirs(HIST, exist_ok=True)
    with open(CLOSED, "w", encoding="utf-8") as f:
        json.dump(sorted(closed), f, indent=0)


def walk(start, stop, limit=None):
    """從 start 往回走到 stop,抓缺少的交易日。limit = 最多新抓幾天。"""
    closed, now, fetched = _closed(), datetime.now(TZ), 0
    d = start
    while d >= stop:
        iso = d.isoformat()
        if d.weekday() < 5 and iso not in closed and not os.path.exists(path_for(iso)):
            print("fetch", iso, file=sys.stderr, flush=True)
            day = fetch_day(d)
            time.sleep(PAUSE)
            if day:
                save_day(day)
                fetched += 1
            elif d < now.date():
                closed.add(iso)   # 今天查無資料可能只是還沒公布,不記成休市
                _save_closed(closed)
            if limit and fetched >= limit:
                break
        d -= timedelta(days=1)
    _save_closed(closed)
    return fetched


def latest_available_date():
    now = datetime.now(TZ)
    # 法人資料約 16:30 後公布,之前今天不算
    return now.date() if now.hour >= 17 else now.date() - timedelta(days=1)


def update_recent(days_back=10):
    """每日排程用:補齊最近幾天。"""
    end = latest_available_date()
    return walk(end, end - timedelta(days=days_back))


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "backfill":
        stop = date.fromisoformat(sys.argv[2])
        n = walk(latest_available_date(), stop)
        print("done, fetched", n, "days")
    else:
        print(__doc__)
