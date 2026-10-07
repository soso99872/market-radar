"""抓取台股上市櫃三大法人個股買賣超與收盤價,計算各板塊資金流向。

用法: python scripts/fetch_flows.py
- 每個交易日的原始資料快取在 data/flows/raw/YYYY-MM-DD.json,只抓缺少的日期。
- 輸出 data/sectors/latest.json(板塊頁面用)與 data/flows/market.json(大盤三大法人金額,晨報用)。
- 金額 = 買賣超股數 × 當日收盤價,屬估算值。
只用標準函式庫,方便在 GitHub Actions 直接跑。
"""
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "flows", "raw")
CLOSED = os.path.join(ROOT, "data", "flows", "closed.json")
THEMES = os.path.join(ROOT, "data", "sectors", "themes.json")
OUT = os.path.join(ROOT, "data", "sectors", "latest.json")
MARKET = os.path.join(ROOT, "data", "flows", "market.json")
SCREENS = os.path.join(ROOT, "data", "screens", "latest.json")

TZ = timezone(timedelta(hours=8))
DAYS = 21          # 21 個交易日 → 可算 20 日累計與 20 日漲跌
KEEP = 30          # 原始快取保留的交易日數
STOCK = re.compile(r"^[1-9]\d{3}$")   # 只收一般股票,排除 ETF、權證
UA = {"User-Agent": "Mozilla/5.0 (market-radar; +https://github.com/soso99872/market-radar)"}


def get(url):
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            if attempt == 2:
                raise
            print("retry", url, e, file=sys.stderr)
            time.sleep(5)


def num(s):
    s = str(s).replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def fetch_day(d):
    """回傳某日的個股資料;非交易日(或資料尚未公布)回傳 None。"""
    ymd = d.strftime("%Y%m%d")
    slash = d.strftime("%Y/%m/%d")

    t86 = get("https://www.twse.com.tw/rwd/zh/fund/T86?date=%s&selectType=ALLBUT0999&response=json" % ymd)
    if t86.get("stat") != "OK" or not t86.get("data"):
        return None
    time.sleep(3)
    mi = get("https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date=%s&type=ALLBUT0999&response=json" % ymd)
    time.sleep(3)
    tp3 = get("https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade?type=Daily&sect=EW&date=%s&response=json" % slash.replace("/", "%2F"))
    time.sleep(1)
    tpq = get("https://www.tpex.org.tw/www/zh-tw/afterTrading/otc?date=%s&type=EW&response=json" % slash.replace("/", "%2F"))
    time.sleep(1)

    px = {}   # code -> (name, close, chg_pct, 成交金額)
    taiex = None
    for t in mi.get("tables", []):
        f = t.get("fields") or []
        if "證券代號" in f and "收盤價" in f:
            ic, iname, iclose = f.index("證券代號"), f.index("證券名稱"), f.index("收盤價")
            isign, idiff, ival = f.index("漲跌(+/-)"), f.index("漲跌價差"), f.index("成交金額")
            for r in t["data"]:
                c, close, diff = r[ic].strip(), num(r[iclose]), num(r[idiff])
                if not STOCK.match(c) or not close:
                    continue
                diff = diff or 0.0
                if "-" in r[isign]:
                    diff = -diff
                prev = close - diff
                px[c] = (r[iname].strip(), close, round(diff / prev * 100, 2) if prev else 0.0, num(r[ival]) or 0)
        elif f and f[0] == "指數" and taiex is None:
            for r in t.get("data", []):
                if r[0].strip() == "發行量加權股價指數":
                    pct = num(r[4])
                    if "-" in r[2]:
                        pct = -abs(pct or 0)
                    taiex = [num(r[1]), pct]
    for t in tpq.get("tables", []):
        for r in t.get("data", []):
            c, close, diff = r[0].strip(), num(r[2]), num(r[3])
            if not STOCK.match(c) or not close:
                continue
            diff = diff or 0.0
            prev = close - diff
            px[c] = (r[1].strip(), close, round(diff / prev * 100, 2) if prev else 0.0, num(r[8]) or 0)

    flows = {}  # code -> (foreign, trust, dealer) 股數
    for r in t86["data"]:
        c = r[0].strip()
        if STOCK.match(c):
            flows[c] = (num(r[4]) + num(r[7]), num(r[10]), num(r[11]))
    tables = tp3.get("tables") or [{}]
    for r in tables[0].get("data", []):
        c = r[0].strip()
        if STOCK.match(c):
            flows[c] = (num(r[10]), num(r[13]), num(r[22]))

    stocks = {}
    for c, (name, close, chg, value) in px.items():
        fo, tr, de = flows.get(c, (0.0, 0.0, 0.0))
        stocks[c] = [name, close, chg, int(fo), int(tr), int(de), int(value)]
    return {"date": d.strftime("%Y-%m-%d"), "taiex": taiex, "stocks": stocks}


def fetch_market(d):
    """大盤三大法人買賣金額(億元),給晨報用。"""
    j = get("https://www.twse.com.tw/rwd/zh/fund/BFI82U?type=day&dayDate=%s&response=json" % d.strftime("%Y%m%d"))
    if j.get("stat") != "OK":
        return None
    v = {r[0].strip(): num(r[3]) for r in j.get("data", [])}

    def yi(*keys):
        vals = [v[k] for k in keys if v.get(k) is not None]
        return round(sum(vals) / 1e8, 2) if vals else None

    return {
        "date": d.strftime("%Y-%m-%d"),
        "fetched_at": datetime.now(TZ).isoformat(timespec="minutes"),
        "foreign": yi("外資及陸資(不含外資自營商)", "外資自營商"),
        "trust": yi("投信"),
        "dealer": yi("自營商(自行買賣)", "自營商(避險)"),
        "total": yi("合計"),
        "unit": "億元(上市)",
        "source": "https://www.twse.com.tw/zh/trading/foreign/bfi82u.html",
    }


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def collect():
    os.makedirs(RAW, exist_ok=True)
    closed = set(load_json(CLOSED, []))
    now = datetime.now(TZ)
    # 法人資料約 16:30 後公布,之前今天不算
    d = now.date() if now.hour >= 17 else now.date() - timedelta(days=1)
    days, walked = [], 0
    while len(days) < DAYS and walked < 60:
        iso = d.isoformat()
        path = os.path.join(RAW, iso + ".json")
        if d.weekday() < 5 and iso not in closed:
            if os.path.exists(path):
                days.append(load_json(path, None))
            else:
                print("fetch", iso, file=sys.stderr)
                day = fetch_day(d)
                time.sleep(3)
                if day:
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(day, f, ensure_ascii=False, separators=(",", ":"))
                    days.append(day)
                elif d < now.date():
                    closed.add(iso)   # 今天查無資料可能只是還沒公布,不記成休市
        d -= timedelta(days=1)
        walked += 1
    with open(CLOSED, "w", encoding="utf-8") as f:
        json.dump(sorted(closed)[-120:], f, ensure_ascii=False, indent=0)
    # 清掉過舊的快取
    keep = {x["date"] for x in days}
    old = sorted(n for n in os.listdir(RAW) if n.endswith(".json"))
    for n in old[:-KEEP]:
        if n[:-5] not in keep:
            os.remove(os.path.join(RAW, n))
    return list(reversed(days))  # 舊 → 新


def yi(shares, close):
    return shares * close / 1e8


def build(days):
    themes = load_json(THEMES, [])
    last = days[-1]
    dates = [x["date"] for x in days]
    n = len(days)
    out, missing = [], []

    def ret(code, w):
        """w 日漲跌幅(%);w=1 用當日漲跌。"""
        if w == 1:
            s = last["stocks"].get(code)
            return s[2] if s else None
        if n <= w:
            return None
        a, b = days[-1 - w]["stocks"].get(code), last["stocks"].get(code)
        return round((b[1] / a[1] - 1) * 100, 2) if a and b and a[1] else None

    for th in themes:
        codes = [c for c in th["codes"] if c in last["stocks"]]
        missing += [c for c in th["codes"] if c not in last["stocks"]]
        if not codes:
            continue
        # 每日、每檔的買賣超金額(億)
        per = []
        for day in days:
            row = {}
            for c in codes:
                s = day["stocks"].get(c)
                if s:
                    row[c] = (yi(s[3], s[1]), yi(s[4], s[1]), yi(s[5], s[1]))
            per.append(row)
        daily = [round(sum(sum(v) for v in row.values()), 2) for row in per]

        win, members = {}, {c: {"code": c, "name": last["stocks"][c][0], "close": last["stocks"][c][1]} for c in codes}
        for w in (1, 5, 20):
            span = per[-w:]
            f = sum(v[0] for row in span for v in row.values())
            t = sum(v[1] for row in span for v in row.values())
            dl = sum(v[2] for row in span for v in row.values())
            net_by = {c: sum(sum(row[c]) for row in span if c in row) for c in codes}
            rets = [r for r in (ret(c, w) for c in codes) if r is not None]
            pos = sorted(net_by, key=net_by.get, reverse=True)
            neg = sorted(net_by, key=net_by.get)
            total = f + t + dl
            leader = pos[0] if total >= 0 else neg[0]
            win[str(w)] = {
                "net": round(total, 2), "foreign": round(f, 2), "trust": round(t, 2), "dealer": round(dl, 2),
                "chg": round(sum(rets) / len(rets), 2) if rets else None,
                "buyers": sum(1 for v in net_by.values() if v > 0),
                "leader": members[leader]["name"],
                "partial": n < w + (0 if w == 1 else 1),
            }
            for c in codes:
                members[c][str(w)] = [ret(c, w), round(net_by[c], 2)]

        # 資金連續流入/流出天數
        sgn = 1 if daily[-1] > 0 else -1 if daily[-1] < 0 else 0
        streak = 0
        for v in reversed(daily):
            if sgn and (v > 0) == (sgn > 0) and v != 0:
                streak += 1
            else:
                break
        avg5 = sum(daily[-6:-1]) / 5 if n >= 6 else None
        pace = None
        if avg5 is not None and sgn:
            if sgn > 0:
                pace = "流入加速" if daily[-1] > max(avg5, 0) else "流入放緩"
            else:
                pace = "流出加速" if daily[-1] < min(avg5, 0) else "流出放緩"
        n1, n5 = win["1"]["net"], win["5"]["net"]
        status = ("資金流入" if n1 > 0 else "流入轉弱") if n5 > 0 else ("資金回流" if n1 > 0 else "資金流出")

        out.append({
            "id": th["id"], "name": th["name"], "desc": th.get("desc", ""), "count": len(codes),
            "status": status, "streak": streak * sgn, "pace": pace,
            "daily": daily[-20:], "w": win,
            "members": sorted(members.values(), key=lambda m: -abs(m["5"][1])),
        })

    if missing:
        print("代號不在今日資料中(已略過):", ", ".join(sorted(set(missing))), file=sys.stderr)
    return {
        "date": last["date"],
        "generated_at": datetime.now(TZ).isoformat(timespec="minutes"),
        "dates": dates[-20:],
        "taiex": last.get("taiex"),
        "note": "金額以各交易日收盤價 × 三大法人買賣超股數估算,單位億元;板塊漲跌為成分股等權平均。",
        "themes": out,
    }


def contrarian(days, themes):
    """逆勢買超:區間內股價下跌、三大法人卻淨買超的個股。

    依法人買超佔區間成交金額的比例排序(同樣買 1 億,小型股的意義比台積電大),
    並要求一定的買超金額,過濾掉成交稀少的小票。
    """
    last = days[-1]
    tags = {}
    for th in themes:
        for c in th["codes"]:
            tags.setdefault(c, []).append(th["name"])
    out = {}
    for w, min_net in ((1, 0.3), (5, 1.0)):
        if len(days) <= w:
            continue
        span = days[-w:]
        rows = []
        for c, s in last["stocks"].items():
            base = days[-1 - w]["stocks"].get(c) if w > 1 else None
            chg = s[2] if w == 1 else (round((s[1] / base[1] - 1) * 100, 2) if base and base[1] else None)
            if chg is None or chg >= 0:
                continue
            f = t = d = value = 0.0
            for day in span:
                x = day["stocks"].get(c)
                if x:
                    f, t, d = f + yi(x[3], x[1]), t + yi(x[4], x[1]), d + yi(x[5], x[1])
                    value += (x[6] if len(x) > 6 else 0) / 1e8
            net = f + t + d
            if net < min_net:
                continue
            # 法人連續買超天數(不限於區間)
            streak = 0
            for day in reversed(days):
                x = day["stocks"].get(c)
                if x and x[3] + x[4] + x[5] > 0:
                    streak += 1
                else:
                    break
            trust_streak = 0
            for day in reversed(days):
                x = day["stocks"].get(c)
                if x and x[4] > 0:
                    trust_streak += 1
                else:
                    break
            rows.append({
                "code": c, "name": s[0], "close": s[1], "chg": chg,
                "net": round(net, 2), "foreign": round(f, 2), "trust": round(t, 2), "dealer": round(d, 2),
                "ratio": round(net / value * 100, 1) if value else None,
                "streak": streak, "trust_streak": trust_streak, "themes": tags.get(c, []),
            })
        rows.sort(key=lambda r: -(r["ratio"] if r["ratio"] is not None else 0))
        out[str(w)] = rows[:40]
    return {
        "date": last["date"],
        "generated_at": datetime.now(TZ).isoformat(timespec="minutes"),
        "note": "股價下跌但三大法人淨買超的個股,依買超佔成交金額比例排序;當日門檻 0.3 億、5 日門檻 1 億。只呈現事實,不構成投資建議。",
        "contrarian": out,
    }


def main():
    days = collect()
    if not days:
        sys.exit("沒有任何交易日資料")
    result = build(days)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
    os.makedirs(os.path.dirname(SCREENS), exist_ok=True)
    with open(SCREENS, "w", encoding="utf-8") as f:
        json.dump(contrarian(days, load_json(THEMES, [])), f, ensure_ascii=False, separators=(",", ":"))
    try:
        m = fetch_market(datetime.strptime(days[-1]["date"], "%Y-%m-%d"))
        if m:
            with open(MARKET, "w", encoding="utf-8") as f:
                json.dump(m, f, ensure_ascii=False, indent=1)
    except Exception as e:  # noqa: BLE001
        print("BFI82U 失敗:", e, file=sys.stderr)
    print("OK", result["date"], len(result["themes"]), "themes")


if __name__ == "__main__":
    main()
