"""抓取台股上市櫃三大法人個股買賣超與收盤價,計算各板塊資金流向。

用法: python scripts/fetch_flows.py
- 個股歷史資料由 scripts/history.py 維護(data/history/),這裡只補最近幾天。
- 輸出 data/sectors/latest.json(板塊頁面用)與 data/flows/market.json(大盤三大法人金額,晨報用)。
- 金額 = 買賣超股數 × 當日收盤價,屬估算值。
只用標準函式庫,方便在 GitHub Actions 直接跑。
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import history  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THEMES = os.path.join(ROOT, "data", "sectors", "themes.json")
OUT = os.path.join(ROOT, "data", "sectors", "latest.json")
MARKET = os.path.join(ROOT, "data", "flows", "market.json")
SCREENS = os.path.join(ROOT, "data", "screens", "latest.json")

TZ = timezone(timedelta(hours=8))
DAYS = 21          # 21 個交易日 → 可算 20 日累計與 20 日漲跌


def get(url):
    return history.get(url)


def num(s):
    return history.num(s)


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
    """補齊最近的交易日,回傳最近 DAYS 天,轉成本檔使用的格式(舊 → 新)。"""
    history.update_recent()
    days = []
    for day in history.load_days(DAYS):
        days.append({"date": day["date"], "taiex": day.get("taiex"), "stocks": {
            c: [r[history.NAME], r[history.CLOSE], r[history.CHG], r[history.FOREIGN], r[history.TRUST],
                r[history.DEALER], r[history.VALUE]] for c, r in day["s"].items()}})
    return days


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
            # 流動性:近 20 日平均成交金額至少 1 億,過濾成交稀少的小型股
            vals = [day["stocks"][c][6] for day in days[-20:] if c in day["stocks"]]
            if not vals or sum(vals) / len(vals) < 1e8:
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
        "note": "股價下跌但三大法人淨買超的個股,依買超佔成交金額比例排序;當日門檻 0.3 億、5 日門檻 1 億,並排除近 20 日平均成交金額不到 1 億的個股。只呈現事實,不構成投資建議。",
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
