"""資料新鮮度檢查:每個來源最後一次更新是不是在預期內。排程最後執行,結果寫 data/status.json(網頁底部顯示)。
有延遲時另寫 /tmp/stale.txt,排程會據此開或更新 GitHub issue(會寄信通知);全部恢復時自動關閉。

用法:python scripts/status.py
"""
import json
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import history  # noqa: E402
import margin  # noqa: E402

ROOT = history.ROOT
NOW = datetime.now(history.TZ)
TODAY = NOW.date()


def jload(p):
    try:
        with open(os.path.join(ROOT, p), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def age_h(iso):
    try:
        return (NOW - datetime.fromisoformat(iso)).total_seconds() / 3600
    except (TypeError, ValueError):
        return None


def trading_days_missing(last_iso):
    """last_iso 之後到今天(今天要 17:40 法人資料齊了才算)應該有、卻還沒有的交易日數。休市日以 history 的紀錄為準。"""
    closed = set(json.load(open(history.CLOSED, encoding="utf-8"))) if os.path.exists(history.CLOSED) else set()
    d, n = date.fromisoformat(last_iso) + timedelta(days=1), 0
    while d <= TODAY:
        if d.weekday() < 5 and d.isoformat() not in closed and not (d == TODAY and NOW.hour + NOW.minute / 60 < 18.5):
            n += 1
        d += timedelta(days=1)
    return n


items = []


def add(key, name, last, ok, note=""):
    items.append({"key": key, "name": name, "last": last, "ok": bool(ok), "note": note})


ds = history.all_dates()
last = ds[-1] if ds else None
miss = trading_days_missing(last) if last else 99
add("history", "個股日資料(收盤、法人)", last, miss <= 1, "落後 %d 個交易日" % miss if miss > 1 else "")

q = jload("data/quotes.json") or {}
h = age_h(q.get("fetched_at"))
add("quotes", "國際行情", q.get("fetched_at"), h is not None and h <= 30, "已 %.0f 小時沒更新" % h if h and h > 30 else "")

rev = sorted(n[:7] for n in os.listdir(os.path.join(ROOT, "data", "revenue")) if n.endswith(".json"))
want = (TODAY.replace(day=1) - timedelta(days=1)) if TODAY.day >= 13 else (TODAY.replace(day=1) - timedelta(days=32))
want = want.strftime("%Y-%m")
add("revenue", "月營收", rev[-1] if rev else None, bool(rev) and rev[-1] >= want, "應有 %s" % want if rev and rev[-1] < want else "")

need = [p for p in margin.ended_periods(TODAY.year - 1, TODAY) if margin.available(p) <= TODAY.isoformat()]
need = need[-1] if need else None
for key, name, path in (("margin", "季度毛利率", "data/margin/cum.json"), ("quality", "季報(地雷檢查)", "data/quality/pl.json")):
    db = jload(path) or {}
    have = max((p for v in db.values() for p in v), default=None)
    add(key, name, have, have is not None and (need is None or have >= need), "應有 %s" % need if have and need and have < need else "")

al = jload("data/quality/alerts.json") or {}
h = age_h(al.get("fetched_at"))
add("alerts", "處置 / 注意股", al.get("fetched_at"), h is not None and h <= 30, "已 %.0f 小時沒更新" % h if h and h > 30 else "")

es = jload("data/estimates/latest.json") or {}
h = age_h(es.get("fetched_at"))
add("estimates", "分析師預估", es.get("fetched_at"), h is not None and h <= 36, "已 %.0f 小時沒更新" % h if h and h > 36 else "")

rd = jload("data/radar/latest.json") or {}
add("radar", "起漲雷達與評級", rd.get("date"), rd.get("date") == last, "比日資料舊" if rd.get("date") != last else "")

ix = jload("data/index.json") or {}
top = (ix.get("dates") or [None])[0]
expect = TODAY.isoformat() if NOW.hour + NOW.minute / 60 >= 6.7 else (TODAY - timedelta(days=1)).isoformat()
weekday_expect = date.fromisoformat(expect).weekday() < 5
add("report", "晨報", top, (not weekday_expect) or (top or "") >= expect, "最新一份是 %s" % top if weekday_expect and (top or "") < expect else "")

stale = [x for x in items if not x["ok"]]
doc = {"checked_at": NOW.isoformat(timespec="minutes"), "ok": not stale, "items": items}
with open(os.path.join(ROOT, "data", "status.json"), "w", encoding="utf-8") as f:
    json.dump(doc, f, ensure_ascii=False, indent=1)
for x in stale:
    print("::warning::資料延遲:%s %s(最後 %s)" % (x["name"], x["note"], x["last"]))
flag = os.environ.get("STALE_FILE")
if flag:
    with open(flag, "w", encoding="utf-8") as f:
        f.write("\n".join("- **%s**:%s(最後一筆 %s)" % (x["name"], x["note"], x["last"]) for x in stale))
print("status:", "全部正常" if not stale else "%d 項延遲" % len(stale))
